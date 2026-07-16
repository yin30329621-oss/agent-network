from agent_network.claim.evidence_decision import (
    EvidenceDecision,
    EvidenceDecisionBatch,
    EvidenceDecisionStatus,
    FactReviewInput,
    RuleAudit,
    RuleConfidence,
)
from agent_network.claim.fact_adapter import FactReviewInputAdapter
from agent_network.evidence.offline_retrieval import RetrievalResult, SelectedEvidence


def make_batch(*, claim_id: str = "c1", decision_claim_id: str | None = None) -> EvidenceDecisionBatch:
    evidence = SelectedEvidence(
        chunk_id="chunk-1",
        document_id="doc-1",
        canonical_url="https://docs.example.test/doc-1",
        heading_path=["Rancher", "Support"],
        text_excerpt="Rancher supports the integration.",
        bm25_score=1.0,
        final_score=1.0,
        matched_terms=["rancher", "supports"],
        product_match=True,
        component_match=None,
        version_match=True,
        document_type="official",
        source_priority=1,
        selection_reason="test",
        evidence_limitations=[],
    )
    retrieval = RetrievalResult(
        claim_id=claim_id,
        query_terms=["rancher", "supports"],
        candidate_count=1,
        filtered_candidate_count=1,
        selected_count=1,
        top_k=5,
        results=[evidence],
    )
    decision = EvidenceDecision(
        claim_id=decision_claim_id or claim_id,
        status=EvidenceDecisionStatus.VERIFIED_CANDIDATE,
        confidence=RuleConfidence.HIGH,
        evidence=[evidence],
        sufficiency_score=3,
        rule_audit=[RuleAudit("test", True, "test")],
    )
    review_input = FactReviewInput(
        claim={"claim_id": claim_id, "text": "Rancher supports the integration."},
        decision=decision.to_dict(),
        retrieval=retrieval.to_dict(),
    )
    return EvidenceDecisionBatch(
        decisions=[decision],
        review_inputs=[review_input],
        status_counts={decision.status.value: 1},
    )


def test_fact_adapter_converts_success_and_preserves_evidence() -> None:
    batch = make_batch()
    batch.review_inputs[0].decision["cited_chunk_ids"] = ["chunk-1"]
    result = FactReviewInputAdapter().adapt(batch)

    assert result.claim_ids == ["c1"]
    assert result.total_count == 1
    assert result.ready_count == 1
    assert result.failed_count == 0
    assert result.inputs[0].decision["evidence"][0]["chunk_id"] == "chunk-1"
    assert result.inputs[0].retrieval["results"][0]["chunk_id"] == "chunk-1"
    assert result.inputs[0].decision["cited_chunk_ids"] == ["chunk-1"]

    assert result.failure_slots == []


def test_fact_adapter_rejects_misaligned_decision() -> None:
    result = FactReviewInputAdapter().adapt(
        make_batch(decision_claim_id="different-claim")
    )

    assert result.ready_count == 0
    assert result.failed_count == 1
    assert result.failure_slots[0].code == "decision_claim_id_mismatch"
    assert result.results[0].input is None


def test_fact_adapter_preserves_failure_slot_for_missing_decision() -> None:
    batch = make_batch()
    batch.decisions = []

    result = FactReviewInputAdapter().adapt(batch)

    assert result.claim_ids == ["c1"]
    assert result.failed_count == 1
    assert result.failure_slots[0].code == "decision_claim_id_missing"


def test_fact_adapter_rejects_citation_outside_decision_evidence() -> None:
    batch = make_batch()
    batch.review_inputs[0].decision["cited_chunk_ids"] = ["unknown-chunk"]

    result = FactReviewInputAdapter().adapt(batch)

    assert result.ready_count == 0
    assert result.failure_slots[0].code == "invalid_citation"


def test_fact_adapter_empty_input_has_zero_cost() -> None:
    result = FactReviewInputAdapter().adapt(
        EvidenceDecisionBatch([], [], {})
    )

    assert result.inputs == []
    assert result.failure_slots == []
    assert result.total_count == 0
    assert result.ready_count == 0
    assert result.failed_count == 0
    assert result.cost_metadata["model_call_count"] == 0
    assert result.cost_metadata["network_request_count"] == 0
    assert result.cost_metadata["adapter_model_call_count"] == 0
    assert result.cost_metadata["adapter_network_request_count"] == 0
