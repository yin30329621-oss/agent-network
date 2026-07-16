from agent_network.claim.fact_review import (
    DualFactReviewCoordinator,
    DualReviewBudget,
    FactReviewResult,
    FakeFactReviewer,
)
from agent_network.evidence.offline_retrieval import RetrievalResult, SelectedEvidence
from agent_network.workflow.report_verification import (
    OfflineReportVerificationConfig,
    OfflineReportVerificationOrchestrator,
)


REPORT = """# Technical Report

Rancher supports downstream integration.

Rancher uses TLS encryption.
"""


class DualFactRetriever:
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
            selection_reason="dual-fact-test",
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


def coordinator(fact_a=None, fact_b=None) -> DualFactReviewCoordinator:
    return DualFactReviewCoordinator(
        fact_a or FakeFactReviewer("fact_a"),
        fact_b or FakeFactReviewer("fact_b"),
        budget=DualReviewBudget(max_claims_per_batch=3),
    )


def test_dual_fact_workflow_populates_review_and_reconciliation_artifacts() -> None:
    fact_a = FakeFactReviewer("fact_a")
    fact_b = FakeFactReviewer("fact_b")
    result = OfflineReportVerificationOrchestrator(
        DualFactRetriever(),
        config=OfflineReportVerificationConfig(enable_dual_fact=True),
        coordinator=coordinator(fact_a, fact_b),
    ).run(REPORT)

    assert result.dual_fact is not None
    assert result.artifact["metadata"]["enable_dual_fact"] is True
    assert len(result.artifact["fact_review"]["fact_a"]) == 2
    assert len(result.artifact["fact_review"]["fact_b"]) == 2
    assert len(result.artifact["reconciliation"]) == 2
    assert result.artifact["fact_review"]["call_metadata"]["actual_reviewer_calls"] == 2
    assert result.artifact["statistics"]["reconciliation_executed"] is True


def test_dual_fact_fact_a_and_fact_b_are_isolated() -> None:
    def mutate_a(item: dict[str, object]) -> FactReviewResult:
        decision = item["decision"]
        assert isinstance(decision, dict)
        evidence = decision["evidence"]
        assert isinstance(evidence, list)
        evidence[0]["chunk_id"] = "changed-by-a"
        return FactReviewResult("fact_a", "candidate_only", "candidate_only", [], "A")

    def inspect_b(item: dict[str, object]) -> FactReviewResult:
        return FactReviewResult(
            "fact_b", "candidate_only", "candidate_only", [], str(item["decision"])
        )

    fact_a = FakeFactReviewer("fact_a", handler=mutate_a)
    fact_b = FakeFactReviewer("fact_b", handler=inspect_b)
    result = OfflineReportVerificationOrchestrator(
        DualFactRetriever(),
        config=OfflineReportVerificationConfig(enable_dual_fact=True),
        coordinator=coordinator(fact_a, fact_b),
    ).run(REPORT)

    assert result.artifact["fact_review"]["fact_b"][0]["reasoning_summary"].find(
        "changed-by-a"
    ) == -1
    assert result.fact_inputs.inputs[0].decision["evidence"][0]["chunk_id"].startswith(
        "chunk-"
    )


def test_dual_fact_failure_routing_keeps_claim_id_and_excludes_failed_reviewer_input() -> None:
    fact_a = FakeFactReviewer("fact_a")
    fact_b = FakeFactReviewer("fact_b")
    result = OfflineReportVerificationOrchestrator(
        DualFactRetriever(failing_text="TLS"),
        config=OfflineReportVerificationConfig(enable_dual_fact=True),
        coordinator=coordinator(fact_a, fact_b),
    ).run(REPORT)

    claim_ids = [item["claim_id"] for item in result.artifact["reconciliation"]]
    failure_ids = [item["claim_id"] for item in result.artifact["fact_review"]["failure_slots"]]
    assert len(claim_ids) == 2
    assert len(failure_ids) >= 1
    assert len(fact_a.received_batches[0]) == 1
    assert len(fact_b.received_batches[0]) == 1
    assert result.artifact["statistics"]["network_request_count"] == 0
