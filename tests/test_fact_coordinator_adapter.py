from agent_network.claim.evidence_adapter import AdapterFailure
from agent_network.claim.evidence_decision import FactReviewInput
from agent_network.claim.fact_adapter import FactReviewInputAdapterBatchResult
from agent_network.claim.fact_coordinator_adapter import FactReviewInputCoordinatorAdapter
from agent_network.claim.fact_review import (
    DualFactReviewCoordinator,
    DualReviewBudget,
    FactReviewResult,
    FakeFactReviewer,
)


def make_input(claim_id: str) -> FactReviewInput:
    evidence = {"chunk_id": f"chunk-{claim_id}", "text": "official evidence"}
    return FactReviewInput(
        claim={"claim_id": claim_id, "text": f"claim {claim_id}"},
        decision={
            "claim_id": claim_id,
            "status": "verified_candidate",
            "evidence": [evidence],
        },
        retrieval={
            "claim_id": claim_id,
            "results": [evidence],
        },
    )


def make_adapter_result(*inputs: FactReviewInput) -> FactReviewInputAdapterBatchResult:
    return FactReviewInputAdapterBatchResult(
        inputs=list(inputs),
        failure_slots=[],
        claim_ids=[item.claim["claim_id"] for item in inputs],
        total_count=len(inputs),
        ready_count=len(inputs),
        failed_count=0,
        cost_metadata={
            "adapter_model_call_count": 0,
            "network_request_count": 0,
        },
    )


def make_coordinator(fact_a=None, fact_b=None) -> DualFactReviewCoordinator:
    return DualFactReviewCoordinator(
        fact_a or FakeFactReviewer("fact_a"),
        fact_b or FakeFactReviewer("fact_b"),
        budget=DualReviewBudget(max_claims_per_batch=3),
    )


def test_ready_adapter_inputs_enter_coordinator_and_preserve_claim_id() -> None:
    fact_a = FakeFactReviewer("fact_a")
    fact_b = FakeFactReviewer("fact_b")
    result = FactReviewInputCoordinatorAdapter(make_coordinator(fact_a, fact_b)).review(
        make_adapter_result(make_input("c1"))
    )

    assert result.claim_ids == ["c1"]
    assert [item.claim_id for item in result.reconciliations] == ["c1"]
    assert [item["claim"]["claim_id"] for item in fact_a.received_batches[0]] == ["c1"]
    assert [item["claim"]["claim_id"] for item in fact_b.received_batches[0]] == ["c1"]
    assert result.cost_metadata["estimated_reviewer_calls"] == 2
    assert result.cost_metadata["actual_reviewer_calls"] == 2


def test_failure_claim_does_not_enter_fact_reviewers() -> None:
    fact_a = FakeFactReviewer("fact_a")
    fact_b = FakeFactReviewer("fact_b")
    adapter_result = make_adapter_result(make_input("c1"))
    adapter_result.claim_ids.append("c2")
    adapter_result.failure_slots.append(
        AdapterFailure("c2", "retrieval", "retrieval_failed", "Evidence unavailable.")
    )
    adapter_result.total_count = 2
    adapter_result.failed_count = 1

    result = FactReviewInputCoordinatorAdapter(make_coordinator(fact_a, fact_b)).review(
        adapter_result
    )

    assert [item.claim_id for item in result.reconciliations] == ["c1"]
    assert [slot.claim_id for slot in result.failure_slots] == ["c2"]
    assert [item["claim"]["claim_id"] for item in fact_a.received_batches[0]] == ["c1"]
    assert [item["claim"]["claim_id"] for item in fact_b.received_batches[0]] == ["c1"]


def test_empty_adapter_result_does_not_call_coordinator_reviewers() -> None:
    fact_a = FakeFactReviewer("fact_a")
    fact_b = FakeFactReviewer("fact_b")
    result = FactReviewInputCoordinatorAdapter(make_coordinator(fact_a, fact_b)).review(
        make_adapter_result()
    )

    assert result.reconciliations == []
    assert result.failure_slots == []
    assert result.total_count == 0
    assert result.cost_metadata["estimated_reviewer_calls"] == 0
    assert fact_a.received_batches == []
    assert fact_b.received_batches == []


def test_coordinator_preserves_fact_a_and_fact_b_input_isolation() -> None:
    def mutate_fact_a(item: dict[str, object]) -> FactReviewResult:
        decision = item["decision"]
        assert isinstance(decision, dict)
        evidence = decision["evidence"]
        assert isinstance(evidence, list)
        evidence[0]["chunk_id"] = "mutated-by-a"
        return FactReviewResult("fact_a", "candidate_only", "candidate_only", [], "A")

    def inspect_fact_b(item: dict[str, object]) -> FactReviewResult:
        return FactReviewResult(
            "fact_b",
            "candidate_only",
            "candidate_only",
            [],
            str(item["decision"]),
        )

    fact_a = FakeFactReviewer("fact_a", handler=mutate_fact_a)
    fact_b = FakeFactReviewer("fact_b", handler=inspect_fact_b)
    adapter_result = make_adapter_result(make_input("c1"))

    FactReviewInputCoordinatorAdapter(make_coordinator(fact_a, fact_b)).review(
        adapter_result
    )

    assert fact_b.received_batches[0][0]["decision"]["evidence"][0]["chunk_id"] == "chunk-c1"
    assert adapter_result.inputs[0].decision["evidence"][0]["chunk_id"] == "chunk-c1"

def test_fact_a_and_fact_b_use_batch_call_count() -> None:
    fact_a = FakeFactReviewer("fact_a")
    fact_b = FakeFactReviewer("fact_b")
    inputs = [make_input(f"c{index}") for index in range(4)]

    result = FactReviewInputCoordinatorAdapter(make_coordinator(fact_a, fact_b)).review(
        make_adapter_result(*inputs)
    )

    assert result.cost_metadata["estimated_reviewer_calls"] == 4
    assert result.cost_metadata["actual_reviewer_calls"] == 4
    assert len(fact_a.received_batches) == 2
    assert len(fact_b.received_batches) == 2
    assert [len(batch) for batch in fact_a.received_batches] == [2, 2]
    assert [len(batch) for batch in fact_b.received_batches] == [2, 2]