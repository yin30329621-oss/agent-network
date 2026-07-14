from datetime import UTC, datetime
from types import SimpleNamespace

from agent_network.evidence.document_bm25 import tokenize
from agent_network.evidence.document_chunker import DocumentChunk
from agent_network.evidence.offline_retrieval import (
    EvidenceSelectionConfig,
    FactBatchBudgetConfig,
    OfflineBm25EvidenceRetriever,
    build_claim_query,
    estimate_fact_batch_budget,
)


FETCHED_AT = datetime(2026, 7, 14, tzinfo=UTC)


def _chunk(
    chunk_id: str,
    text: str,
    *,
    document_id: str,
    product: str = "Rancher Manager",
    component: str = "Cluster Agent",
    version: str | None = "v2.14",
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        canonical_url="https://ranchermanager.docs.rancher.com/fixture",
        final_url="https://ranchermanager.docs.rancher.com/fixture",
        product=product,
        component=component,
        document_type="reference",
        document_title=document_id,
        section_heading="Overview",
        section_heading_level=2,
        section_order=0,
        chunk_order=0,
        text=text,
        character_count=len(text),
        source_fetched_at=FETCHED_AT,
        product_version=version,
        heading_path=["Overview"],
    )


def _claim(
    claim_id: str,
    text: str,
    *,
    product: str | None = "Rancher Manager",
    component: str | None = "Cluster Agent",
    version: str | None = None,
    entities: list[str] | None = None,
):
    return SimpleNamespace(
        claim_id=claim_id,
        normalized_claim=text,
        product=product,
        component=component,
        version_scope=SimpleNamespace(exact=version),
        entities=[SimpleNamespace(value=value) for value in (entities or [])],
    )


def _retriever(config: EvidenceSelectionConfig | None = None) -> OfflineBm25EvidenceRetriever:
    return OfflineBm25EvidenceRetriever(
        [
            _chunk(
                "cluster",
                "The cattle-cluster-agent maintains a reverse tunnel to Rancher Server.",
                document_id="cluster-agent",
            ),
            _chunk(
                "rbac",
                "A ServiceAccount receives RBAC permissions through a RoleBinding.",
                document_id="rbac",
                component="ServiceAccount",
            ),
            _chunk(
                "fleet",
                "Fleet Agent deploys Bundle GitOps resources to target clusters.",
                document_id="fleet-bundle",
                product="Fleet",
                component="Fleet Agent",
            ),
            _chunk(
                "cve",
                "CVE-2025-1234 affects v2.10.3 before v2.10.4.",
                document_id="advisory",
                component="CVE",
                version="v2.10.3",
            ),
        ],
        config,
    )


def test_tokenization_preserves_technical_and_chinese_tokens() -> None:
    tokens = tokenize("CVE-2025-1234 v2.10.3 cattle-cluster-agent 集群代理")

    assert {"cve-2025-1234", "v2.10.3", "cattle-cluster-agent", "集", "集群"}.issubset(tokens)


def test_query_builder_extracts_filters_and_controlled_aliases() -> None:
    query = build_claim_query(
        _claim("zh-agent", "集群代理通过反向隧道连接 Rancher", component="反向隧道")
    )

    assert query.product_filter == "Rancher Manager"
    assert query.component_filter == "反向隧道"
    assert "reverse" in query.boosted_terms and "tunnel" in query.boosted_terms
    assert not {"cve", "v2.10.3"}.intersection(query.excluded_terms)


def test_product_component_and_no_match_filters_are_strict() -> None:
    subject = _retriever()

    fleet = subject.retrieve(
        _claim("fleet", "Bundle GitOps deployment", product="Fleet", component="Fleet Agent")
    )
    wrong_component = subject.retrieve(_claim("wrong", "reverse tunnel", component="Bundle"))
    no_match = subject.retrieve(_claim("none", "unrelated quantum toaster"))

    assert [item.document_id for item in fleet.results] == ["fleet-bundle"]
    assert wrong_component.results == []
    assert no_match.results == [] and no_match.no_match_reason == "no_matching_chunk"


def test_version_match_is_preferred_and_fallback_is_explicit() -> None:
    subject = _retriever()

    exact = subject.retrieve(
        _claim("cve", "CVE-2025-1234 v2.10.3", component="CVE", version="v2.10.3")
    )
    fallback = subject.retrieve(_claim("old", "reverse tunnel", version="v2.9"))

    assert exact.results[0].version_match is True
    assert fallback.version_fallback_used is True
    assert fallback.results[0].version_match is False
    assert "version-mismatch fallback" in fallback.results[0].evidence_limitations[1]


def test_top_k_and_excerpt_budget_are_hard_limited() -> None:
    subject = _retriever(
        EvidenceSelectionConfig(
            max_evidence_per_claim=3,
            max_excerpt_chars_per_evidence=20,
            max_total_evidence_chars_per_claim=25,
        )
    )
    result = subject.retrieve(_claim("budget", "reverse tunnel Rancher Server"), top_k=10)

    assert result.selected_count <= 3
    assert sum(len(item.text_excerpt) for item in result.results) <= 25
    assert any(
        "truncated" in limitation
        for item in result.results
        for limitation in item.evidence_limitations
    )


def test_batch_deduplicates_claims_and_reports_zero_network_and_models() -> None:
    subject = _retriever()
    claim = _claim("duplicate", "reverse tunnel")

    results, audit = subject.retrieve_batch([claim, claim])

    assert len(results) == audit.deduplicated_claims == 1
    assert audit.total_claims == 2
    assert audit.network_request_count == subject.network_request_count == 0
    assert audit.model_call_count == subject.model_call_count == 0


def test_batch_enforces_global_selected_chunk_limit() -> None:
    subject = _retriever(EvidenceSelectionConfig(max_total_selected_chunks=1))

    results, audit = subject.retrieve_batch(
        [
            _claim("agent", "reverse tunnel"),
            _claim("rbac", "ServiceAccount RoleBinding", component="ServiceAccount"),
        ]
    )

    assert audit.total_selected == 1
    assert sum(result.selected_count for result in results) == 1
    assert "batch_selected_chunk_budget_exhausted" in results[1].retrieval_warnings


def test_budget_estimate_batches_only_claims_with_evidence_and_enforces_limit() -> None:
    subject = _retriever()
    results, _audit = subject.retrieve_batch(
        [_claim("one", "reverse tunnel"), _claim("none", "quantum toaster")]
    )
    estimate = estimate_fact_batch_budget(
        results,
        FactBatchBudgetConfig(claims_per_batch=1, max_fact_batches=0),
    )

    assert estimate.estimated_fact_batches == estimate.estimated_model_calls == 1
    assert estimate.excluded_no_evidence_claims == 1
    assert estimate.budget_exceeded is True
