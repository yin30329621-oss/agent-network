from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from agent_network.evidence.cached_official_evidence import CachedEvidenceIndexBuilder
from agent_network.prompts import PromptRegistry
from agent_network.schemas import ReviewRequest
from agent_network.workflow import ReviewWorkflow


FETCHED_AT = "2026-07-13T00:00:00+00:00"


def _stable_hash(value: dict) -> str:
    stable = {key: item for key, item in value.items() if key != "source_fetched_at"}
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256(raw).hexdigest()


def _write_cached_document(
    root: Path,
    document_id: str,
    *,
    component: str,
    text: str,
) -> None:
    document_root = root / "case" / "documents" / document_id
    document_root.mkdir(parents=True)
    url = f"https://ranchermanager.docs.rancher.com/fixture/{document_id}"
    cleaned = {
        "document_id": document_id,
        "canonical_url": url,
        "final_url": url,
        "product": "Rancher Manager",
        "component": component,
        "document_type": "reference",
        "title": f"{component} reference",
        "plain_text": text,
        "headings": [component],
        "sections": [{"heading": component, "heading_level": 2, "text": text, "order": 0}],
        "source_fetched_at": FETCHED_AT,
        "source_response_size_bytes": len(text.encode()),
    }
    raw = f"<html><main>{text}</main></html>".encode()
    metadata = {
        "document_id": document_id,
        "canonical_url": url,
        "final_url": url,
        "product": "Rancher Manager",
        "component": component,
        "document_type": "reference",
        "fetched_at": FETCHED_AT,
        "synced_at": FETCHED_AT,
        "status_code": 200,
        "content_type": "text/html",
        "response_size_bytes": len(raw),
        "raw_content_sha256": sha256(raw).hexdigest(),
        "cleaned_content_sha256": _stable_hash(cleaned),
        "etag": None,
        "last_modified": None,
        "cleaner_version": "1",
        "sync_status": "fetched",
    }
    (document_root / "raw.html").write_bytes(raw)
    (document_root / "cleaned.json").write_text(json.dumps(cleaned), encoding="utf-8")
    (document_root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


class _StubLlm:
    def __init__(self, chunk_ids: list[str] | None = None) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.chunk_ids = chunk_ids or []
        self.last_response_audit = {}

    def complete(self, **kwargs) -> str:
        self.calls += 1
        self.prompts.append(kwargs["user_prompt"])
        return json.dumps(
            {
                "summary": "review result",
                "evidence_chunk_ids": self.chunk_ids,
                "findings": [
                    {
                        "severity": "low",
                        "location": "Summary",
                        "issue": "Evidence review",
                        "reason": "A claim needs a citation.",
                        "evidence_needed": "Official evidence",
                        "reference": None,
                        "suggestion": "Add a citation.",
                        "confidence": 0.7,
                    }
                ],
            }
        )


def _workflow(root: Path, llm: _StubLlm, **local_overrides: object) -> ReviewWorkflow:
    local_config: dict[str, object] = {
        "cache_directory": "case",
        "document_ids": ["cluster", "rbac"],
        "max_documents": 2,
        "max_chunks_per_document": 1,
        "min_documents_in_results": 2,
        "min_score": 0.0,
        "min_matched_terms": 1,
        "exclude_navigation_like": True,
    }
    local_config.update(local_overrides)
    workflow = ReviewWorkflow.from_llm(
        llm=llm,
        prompts=PromptRegistry("prompts"),
        fact_local_cache_builder=CachedEvidenceIndexBuilder(cache_root=root),
        fact_evidence_config={
            "enabled": True,
            "provider": "local_cache",
            "allow_network": False,
            "top_k": 5,
            "max_chars_per_evidence": 1600,
            "max_total_evidence_chars": 6000,
            "local_cache": local_config,
        },
    )
    workflow.merge_agent.model = "test-merge"
    return workflow


def _request() -> ReviewRequest:
    return ReviewRequest(
        markdown="# Report",
        fact_evidence_query={
            "claim_id": "cluster-rbac",
            "query_text": "Cluster Agent ServiceAccount RBAC downstream cluster",
        },
    )


def test_local_cache_injects_multidocument_evidence_and_keeps_four_calls(tmp_path: Path) -> None:
    _write_cached_document(
        tmp_path,
        "cluster",
        component="Cluster Agent",
        text="Cluster Agent maintains a connection to Rancher Server for downstream clusters. " * 5,
    )
    _write_cached_document(
        tmp_path,
        "rbac",
        component="RBAC",
        text="ServiceAccount and RBAC grant access to downstream cluster resources. " * 5,
    )
    llm = _StubLlm()
    workflow = _workflow(tmp_path, llm)

    result = workflow.run(_request())
    fact = result.agent_reviews[0]

    assert llm.calls == 4
    assert fact.evidence_provider == "local_cache"
    assert fact.evidence_network_request_count == 0
    assert fact.evidence_loaded_document_count == 2
    assert fact.evidence_returned_document_count == 2
    assert fact.evidence_returned_evidence_count == 2
    assert fact.evidence_selected_document_ids == ["cluster", "rbac"]
    assert "<official_evidence_context>" in llm.prompts[0]
    assert '"document_id":"cluster"' in llm.prompts[0]
    assert '"document_id":"rbac"' in llm.prompts[0]
    assert "raw.html" not in llm.prompts[0]


def test_local_cache_failures_and_no_match_degrade_without_network(tmp_path: Path) -> None:
    _write_cached_document(
        tmp_path,
        "cluster",
        component="Cluster Agent",
        text="Cluster Agent connects to Rancher Server. " * 6,
    )
    _write_cached_document(tmp_path, "rbac", component="RBAC", text="RBAC access rules. " * 15)
    metadata_path = tmp_path / "case" / "documents" / "rbac" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["cleaned_content_sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    partial = _workflow(tmp_path, _StubLlm()).run_only(_request(), "fact").agent_reviews[0]
    no_match = (
        _workflow(tmp_path, _StubLlm())
        .run_only(
            ReviewRequest(
                markdown="# Report", fact_evidence_query={"query_text": "unrelated vocabulary"}
            ),
            "fact",
        )
        .agent_reviews[0]
    )

    assert partial.retrieval_status == "partial_success"
    assert partial.evidence_failed_document_count == 1
    assert partial.evidence_cache_failures[0]["error_code"] == "checksum_mismatch"
    assert partial.evidence_network_request_count == 0
    assert no_match.retrieval_status == "no_chunk_match"
    assert no_match.evidence_chunk_ids == []
    assert no_match.evidence_relation is not None
    assert no_match.evidence_relation.value == "absence_of_support"


def test_missing_cache_and_invalid_provider_degrade_without_fixture_fallback(
    tmp_path: Path,
) -> None:
    missing = (
        _workflow(tmp_path, _StubLlm(), cache_directory="missing")
        .run_only(_request(), "fact")
        .agent_reviews[0]
    )
    invalid = (
        ReviewWorkflow.from_llm(
            llm=_StubLlm(),
            prompts=PromptRegistry("prompts"),
            fact_evidence_config={"enabled": True, "provider": "unknown"},
        )
        .run_only(_request(), "fact")
        .agent_reviews[0]
    )

    assert missing.retrieval_status == "all_documents_failed"
    assert missing.evidence_relation is not None
    assert missing.evidence_relation.value == "unavailable"
    assert missing.evidence_cache_failures[0]["error_code"] == "cache_not_found"
    assert invalid.retrieval_status == "retrieval_error"
    assert invalid.evidence_provider == "unknown"
    assert invalid.evidence_used is False


def test_local_cache_keeps_citation_validation_and_deterministic_limits(tmp_path: Path) -> None:
    _write_cached_document(
        tmp_path,
        "cluster",
        component="Cluster Agent",
        text="Cluster Agent connects to Rancher Server through a tunnel." * 100,
    )
    _write_cached_document(
        tmp_path,
        "rbac",
        component="RBAC",
        text="ServiceAccount RBAC grants cluster access." * 100,
    )
    llm = _StubLlm(["unknown"])
    workflow = _workflow(
        tmp_path,
        llm,
        max_chunks_per_document=1,
        min_documents_in_results=2,
    )
    workflow.fact_evidence_config["top_k"] = 2
    workflow.fact_evidence_config["max_chars_per_evidence"] = 20
    workflow.fact_evidence_config["max_total_evidence_chars"] = 30

    fact = workflow.run_only(_request(), "fact").agent_reviews[0]

    assert fact.evidence_chunk_ids == []
    assert fact.evidence_warnings == ["unknown_evidence_chunk_id:unknown"]
    assert fact.evidence_returned_evidence_count == 2
    assert fact.evidence_network_request_count == 0
    assert '"text_truncated":true' in llm.prompts[0]
