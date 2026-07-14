from agent_network.claim import Claim, ClaimType
from agent_network.claim.evidence_decision import EvidenceDecisionEngine
from agent_network.claim.fact_review import (
    DualFactReviewCoordinator,
    DualReviewBudget,
    FactReviewResult,
    FakeFactReviewer,
    ReconciliationStatus,
)
from agent_network.evidence.offline_retrieval import RetrievalResult, SelectedEvidence


def _input():
    claim = Claim(claim_id="c1", text="Cluster Agent connects", claim_type=ClaimType.ARCHITECTURE)
    evidence = SelectedEvidence(
        "chunk-1",
        "doc-1",
        "https://ranchermanager.docs.rancher.com/doc",
        ["Cluster Agent"],
        "Cluster Agent connects",
        1,
        1,
        ["cluster", "agent"],
        True,
        True,
        True,
        "reference",
        100,
        "fixture",
        [],
    )
    retrieval = RetrievalResult("c1", ["cluster", "agent"], 1, 1, 1, 3, [evidence])
    return EvidenceDecisionEngine().decide_batch([(claim, retrieval)]).review_inputs[0]


def _reviewer(identifier: str, status: str, citations: list[str] | None = None):
    return FakeFactReviewer(
        identifier,
        lambda _item: FactReviewResult(
            identifier, status, status, citations or ["chunk-1"], "mock"
        ),
    )


def test_payloads_are_identical_and_reviewer_outputs_are_isolated() -> None:
    a, b = _reviewer("fact-a", "verified_candidate"), _reviewer("fact-b", "verified_candidate")
    result = DualFactReviewCoordinator(a, b).review_batch([_input()])
    assert a.received_batches[0] == b.received_batches[0]
    assert "fact-a" not in b.received_batches[0][0] and "fact-b" not in a.received_batches[0][0]
    assert result[0].status == ReconciliationStatus.CONSENSUS


def test_reconciliation_handles_disagreement_challenge_failure_and_invalid_citation() -> None:
    input_value = _input()
    disagreement = DualFactReviewCoordinator(
        _reviewer("fact-a", "candidate_only"), _reviewer("fact-b", "verified_candidate")
    ).review_batch([input_value])[0]
    challenged = DualFactReviewCoordinator(
        _reviewer("fact-a", "candidate_only"), _reviewer("fact-b", "candidate_only")
    ).review_batch([input_value])[0]
    invalid = DualFactReviewCoordinator(
        _reviewer("fact-a", "verified_candidate", ["unknown"]),
        _reviewer("fact-b", "verified_candidate"),
    ).review_batch([input_value])[0]
    single = DualFactReviewCoordinator(
        FakeFactReviewer("fact-a", fail=True), _reviewer("fact-b", "verified_candidate")
    ).review_batch([input_value])[0]
    failed = DualFactReviewCoordinator(
        FakeFactReviewer("fact-a", fail=True), FakeFactReviewer("fact-b", fail=True)
    ).review_batch([input_value])[0]
    assert disagreement.status == ReconciliationStatus.REVIEWER_DISAGREEMENT
    assert challenged.status == ReconciliationStatus.ENGINE_CHALLENGED
    assert invalid.status == ReconciliationStatus.INVALID_CITATION
    assert single.status == ReconciliationStatus.SINGLE_REVIEWER_AVAILABLE
    assert failed.status == ReconciliationStatus.MANUAL_REVIEW_REQUIRED


def test_dual_budget_is_batched_and_never_records_network_or_model_calls() -> None:
    coordinator = DualFactReviewCoordinator(
        _reviewer("fact-a", "verified_candidate"),
        _reviewer("fact-b", "verified_candidate"),
        DualReviewBudget(claims_per_batch=1, max_batches=1),
    )
    estimate = coordinator.estimate([_input(), _input()])
    assert (
        estimate.estimated_fact_a_calls,
        estimate.estimated_fact_b_calls,
        estimate.estimated_total_calls,
    ) == (2, 2, 4)
    assert estimate.budget_exceeded is True
    assert coordinator.network_request_count == coordinator.model_call_count == 0


def test_token_aware_planner_balances_seven_claims_into_shared_batches() -> None:
    a, b = _reviewer("fact-a", "candidate_only"), _reviewer("fact-b", "candidate_only")
    coordinator = DualFactReviewCoordinator(
        a,
        b,
        DualReviewBudget(max_claims_per_batch=3, max_batches=4),
    )
    inputs = [_input() for _ in range(7)]

    estimate = coordinator.estimate(inputs)
    results = coordinator.review_batch(inputs)

    assert estimate.batch_sizes == [3, 2, 2]
    assert estimate.estimated_fact_a_calls == estimate.estimated_fact_b_calls == 3
    assert estimate.estimated_total_calls == 6
    assert estimate.budget_exceeded is False
    assert [len(batch) for batch in a.received_batches] == [3, 2, 2]
    assert a.received_batches == b.received_batches
    assert [item.claim_id for item in results] == ["c1"] * 7
    assert all(
        provider["batch_count"] == 3 and not provider["budget_exceeded"]
        for provider in estimate.provider_estimates.values()
    )


def test_token_aware_planner_rejects_a_claim_that_cannot_fit_one_batch() -> None:
    coordinator = DualFactReviewCoordinator(
        _reviewer("fact-a", "candidate_only"),
        _reviewer("fact-b", "candidate_only"),
        DualReviewBudget(max_input_tokens_per_batch=1),
    )

    estimate = coordinator.estimate([_input(), _input()])

    assert estimate.budget_exceeded is True
    try:
        coordinator.review_batch([_input(), _input()])
    except ValueError as exc:
        assert "budget" in str(exc)
    else:
        raise AssertionError("Expected an over-budget batch to be rejected")
