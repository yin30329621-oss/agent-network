from datetime import UTC, datetime

import pytest

from agent_network.evidence.document_bm25 import (
    Bm25Config,
    Bm25Error,
    Bm25SearchQuery,
    OfficialDocumentBm25Index,
    tokenize,
)
from agent_network.evidence.document_chunker import DocumentChunk


FETCHED_AT = datetime(2026, 7, 13, tzinfo=UTC)


def chunk(
    chunk_id: str,
    text: str,
    *,
    document_id: str = "rancher-cluster-agent",
    product: str = "Rancher Manager",
    component: str = "Cluster Agent",
    document_type: str = "reference",
    title: str = "Cluster Agent Architecture",
    heading: str = "Reverse tunnel",
    section_order: int = 0,
    chunk_order: int = 0,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        canonical_url="https://ranchermanager.docs.rancher.com/fixture",
        final_url="https://ranchermanager.docs.rancher.com/fixture",
        product=product,
        component=component,
        document_type=document_type,
        document_title=title,
        section_heading=heading,
        section_heading_level=2,
        section_order=section_order,
        chunk_order=chunk_order,
        text=text,
        character_count=len(text),
        source_fetched_at=FETCHED_AT,
    )


def corpus() -> list[DocumentChunk]:
    return [
        chunk("cluster", "The cattle-cluster-agent maintains a reverse tunnel over TLS."),
        chunk(
            "fleet",
            "Fleet Bundle deploys GitOps resources.",
            document_id="fleet-bundle",
            product="Fleet",
            component="Fleet Agent",
            title="Fleet Bundle",
            heading="Bundle deployment",
            section_order=1,
        ),
        chunk(
            "rbac",
            "ServiceAccount RBAC permissions require a RoleBinding.",
            document_id="rancher-rbac",
            component="ServiceAccount",
            title="ServiceAccount RBAC",
            heading="Permissions",
            section_order=2,
        ),
        chunk(
            "cve",
            "CVE-2025-1234 affects v2.10.3 before v2.10.4.",
            document_id="security-advisory",
            component="Secret",
            document_type="security_advisory",
            title="Security advisory",
            heading="CVE-2025-1234",
            section_order=3,
        ),
        chunk(
            "chinese",
            "Cluster Agent 通过反向隧道连接 Rancher Server。",
            document_id="zh-cluster-agent",
            heading="反向隧道",
            section_order=4,
        ),
    ]


def test_technical_tokens_are_preserved_and_normalized() -> None:
    tokens = tokenize("CVE-2025-1234 v2.10.3 cattle-cluster-agent ServiceAccount\u200b")

    assert tokens == ["cve-2025-1234", "v2.10.3", "cattle-cluster-agent", "serviceaccount"]


def test_keyword_search_and_fixed_title_heading_weighting() -> None:
    title_match = chunk("title", "ordinary body", title="Reverse Tunnel Guide", heading="Overview")
    body_match = chunk("body", "reverse tunnel", title="General Guide", heading="Overview")

    results = OfficialDocumentBm25Index([body_match, title_match]).search(
        Bm25SearchQuery("reverse tunnel", top_k=2)
    )

    assert [result.chunk.chunk_id for result in results] == ["title", "body"]
    assert results[0].matched_terms == ["reverse", "tunnel"]
    assert [result.rank for result in results] == [1, 2]


def test_product_component_document_type_and_document_id_filters() -> None:
    index = OfficialDocumentBm25Index(corpus())

    assert [
        result.chunk.chunk_id for result in index.search(Bm25SearchQuery("bundle", product="Fleet"))
    ] == ["fleet"]
    assert index.search(Bm25SearchQuery("bundle", product="Rancher Manager")) == []
    assert [
        result.chunk.chunk_id
        for result in index.search(Bm25SearchQuery("rbac", component="ServiceAccount"))
    ] == ["rbac"]
    assert [
        result.chunk.chunk_id
        for result in index.search(
            Bm25SearchQuery("cve-2025-1234", document_type="security_advisory")
        )
    ] == ["cve"]
    assert [
        result.chunk.chunk_id
        for result in index.search(Bm25SearchQuery("reverse", document_id="rancher-cluster-agent"))
    ] == ["cluster"]


def test_chinese_and_mixed_language_queries_retrieve_expected_chunks() -> None:
    index = OfficialDocumentBm25Index(corpus())

    chinese = index.search(Bm25SearchQuery("反向隧道"))
    mixed = index.search(Bm25SearchQuery("Cluster Agent 反向隧道"))

    assert chinese[0].chunk.chunk_id == "chinese"
    assert "反" in chinese[0].matched_terms
    assert mixed[0].chunk.chunk_id == "chinese"


def test_cve_version_and_hyphenated_component_queries_are_exact() -> None:
    index = OfficialDocumentBm25Index(corpus())

    assert index.search(Bm25SearchQuery("CVE-2025-1234"))[0].chunk.chunk_id == "cve"
    assert index.search(Bm25SearchQuery("v2.10.3"))[0].chunk.chunk_id == "cve"
    assert index.search(Bm25SearchQuery("cattle-cluster-agent"))[0].chunk.chunk_id == "cluster"


def test_stopwords_do_not_produce_results_or_matched_terms() -> None:
    index = OfficialDocumentBm25Index(corpus())

    with pytest.raises(Bm25Error) as error:
        index.search(Bm25SearchQuery("the and of"))

    assert error.value.code == "empty_query"


def test_equal_scores_and_input_order_use_stable_tiebreakers() -> None:
    first = chunk("b", "unique", document_id="alpha", section_order=1, chunk_order=1)
    second = chunk("a", "unique", document_id="alpha", section_order=1, chunk_order=0)
    forward = OfficialDocumentBm25Index([first, second]).search(Bm25SearchQuery("unique", top_k=2))
    reverse = OfficialDocumentBm25Index([second, first]).search(Bm25SearchQuery("unique", top_k=2))

    assert [result.chunk.chunk_id for result in forward] == ["a", "b"]
    assert [result.chunk.chunk_id for result in forward] == [
        result.chunk.chunk_id for result in reverse
    ]
    assert forward[0].score == forward[1].score


def test_repeated_search_is_deterministic_and_excludes_zero_scores() -> None:
    index = OfficialDocumentBm25Index(corpus())
    query = Bm25SearchQuery("reverse tunnel", top_k=10)

    assert index.search(query) == index.search(query)
    assert index.search(Bm25SearchQuery("not-in-corpus")) == []
    assert index.network_request_count == 0
    assert index.model_call_count == 0


def test_duplicate_ids_empty_index_and_invalid_parameters_are_rejected() -> None:
    duplicate = chunk("duplicate", "one")
    with pytest.raises(Bm25Error) as duplicate_error:
        OfficialDocumentBm25Index([duplicate, chunk("duplicate", "two")])
    with pytest.raises(Bm25Error) as empty_error:
        OfficialDocumentBm25Index([]).search(Bm25SearchQuery("query"))
    with pytest.raises(Bm25Error) as top_k_error:
        OfficialDocumentBm25Index(corpus()).search(Bm25SearchQuery("query", top_k=0))
    with pytest.raises(Bm25Error) as k1_error:
        Bm25Config(k1=0)
    with pytest.raises(Bm25Error) as b_error:
        Bm25Config(b=1.1)

    assert duplicate_error.value.code == "duplicate_chunk_id"
    assert empty_error.value.code == "empty_index"
    assert top_k_error.value.code == "invalid_top_k"
    assert k1_error.value.code == b_error.value.code == "invalid_config"


def test_small_in_memory_index_handles_one_thousand_chunks() -> None:
    chunks = [
        chunk(f"chunk-{index}", f"token {index}", document_id=f"doc-{index}")
        for index in range(1000)
    ]

    results = OfficialDocumentBm25Index(chunks).search(Bm25SearchQuery("token 999"))

    assert results[0].chunk.chunk_id == "chunk-999"
