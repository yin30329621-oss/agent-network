from pathlib import Path

from agent_network.evidence.offline_retrieval import RetrievalResult, SelectedEvidence
from agent_network.workflow.report_verification import (
    OfflineReportVerificationOrchestrator,
)


class OfflineTestRetriever:
    model_call_count = 0
    network_request_count = 0

    def __init__(self, failing_text: str | None = None) -> None:
        self.failing_text = failing_text
        self.calls: list[str] = []

    def retrieve(self, claim, *, top_k: int | None = None) -> RetrievalResult:
        self.calls.append(claim.claim_id)
        if self.failing_text and self.failing_text in claim.text:
            raise RuntimeError("offline retrieval failure")
        evidence = SelectedEvidence(
            chunk_id=f"chunk-{claim.claim_id}",
            document_id="doc-1",
            canonical_url="https://docs.example.test/doc-1",
            heading_path=["Report"],
            text_excerpt=claim.text,
            bm25_score=1.0,
            final_score=1.0,
            matched_terms=["rancher", "supports"],
            product_match=True,
            component_match=None,
            version_match=True,
            document_type="official",
            source_priority=1,
            selection_reason="offline-test",
            evidence_limitations=[],
        )
        return RetrievalResult(
            claim_id=claim.claim_id,
            query_terms=["rancher"],
            candidate_count=1,
            filtered_candidate_count=1,
            selected_count=1,
            top_k=top_k or 5,
            results=[evidence],
        )


REPORT = """# Technical Report

Rancher supports downstream integration.

Rancher uses TLS encryption.
"""


def test_offline_report_verification_end_to_end(tmp_path: Path) -> None:
    report = tmp_path / "report.md"
    artifact_path = tmp_path / "report-verification.json"
    report.write_text(REPORT, encoding="utf-8")
    retriever = OfflineTestRetriever()

    result = OfflineReportVerificationOrchestrator(retriever).run_file(
        report, output_path=artifact_path
    )

    assert artifact_path.exists()
    assert len(result.extraction.claims) == 2
    assert result.artifact["statistics"]["reconciliation_executed"] is False
    assert result.artifact["fact_review"]["fact_a"] == []
    assert len(result.artifact["reconciliation"]) == 2
    assert retriever.calls == [claim.claim_id for claim in result.extraction.claims]


def test_artifact_schema_and_claim_id_alignment() -> None:
    result = OfflineReportVerificationOrchestrator(OfflineTestRetriever()).run(
        REPORT, source_name="report.md"
    )
    artifact = result.artifact

    assert set(artifact) == {
        "metadata",
        "claims",
        "evidence",
        "fact_review",
        "reconciliation",
        "statistics",
    }
    claim_ids = [claim.claim_id for claim in result.extraction.claims]
    assert [item["claim_id"] for item in artifact["evidence"]["results"]] == claim_ids
    assert [item["claim_id"] for item in artifact["reconciliation"]] == claim_ids
    assert all(
        item["retrieval"]["claim_id"] == item["claim_id"]
        for item in artifact["evidence"]["results"]
    )


def test_failure_slots_are_preserved_in_evidence_and_reconciliation() -> None:
    retriever = OfflineTestRetriever(failing_text="TLS")
    result = OfflineReportVerificationOrchestrator(retriever).run(REPORT)

    failures = result.artifact["evidence"]["failure_slots"]
    assert len(failures) == 1
    failed_claim_id = failures[0]["claim_id"]
    failed_reconciliation = next(
        item for item in result.artifact["reconciliation"] if item["claim_id"] == failed_claim_id
    )
    assert failures[0]["stage"] == "retrieval"
    assert failed_reconciliation["needs_manual_review"] is True
    assert failed_reconciliation["failure_stage"] == "retrieval"
    assert failed_reconciliation["failure_code"] == "retrieval_failed"


def test_offline_orchestration_has_zero_model_and_network_calls() -> None:
    result = OfflineReportVerificationOrchestrator(OfflineTestRetriever()).run(REPORT)

    assert result.evidence.model_call_count == 0
    assert result.evidence.network_request_count == 0
    assert result.artifact["fact_review"]["call_metadata"] == {
        "model_call_count": 0,
        "network_request_count": 0,
    }
    assert result.artifact["statistics"]["model_call_count"] == 0
    assert result.artifact["statistics"]["network_request_count"] == 0
