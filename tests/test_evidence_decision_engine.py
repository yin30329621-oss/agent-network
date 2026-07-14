from pathlib import Path

from agent_network.claim import Claim, ClaimType
from agent_network.claim.evidence_decision import EvidenceDecisionEngine, EvidenceDecisionStatus
from agent_network.claim.evidence_decision_benchmark import benchmark_decisions
from agent_network.evidence.offline_retrieval import RetrievalResult, SelectedEvidence


def claim(text: str = "Cluster Agent connects to Rancher Server") -> Claim:
    return Claim(
        claim_id="claim-1",
        text=text,
        normalized_text=text.lower(),
        product="Rancher Manager",
        component="Cluster Agent",
        claim_type=ClaimType.ARCHITECTURE,
    )


def evidence(
    text: str,
    *,
    version: bool | None = True,
    terms: list[str] | None = None,
    product_match: bool = True,
    component_match: bool | None = True,
    heading: str = "Cluster Agent",
) -> SelectedEvidence:
    return SelectedEvidence(
        chunk_id="chunk-1",
        document_id="doc-1",
        canonical_url="https://ranchermanager.docs.rancher.com/doc",
        heading_path=[heading],
        text_excerpt=text,
        bm25_score=2.0,
        final_score=2.1,
        matched_terms=terms or ["cluster", "agent"],
        product_match=product_match,
        component_match=component_match,
        version_match=version,
        document_type="reference",
        source_priority=100,
        selection_reason="fixture",
        evidence_limitations=[],
    )


def retrieval(items: list[SelectedEvidence]) -> RetrievalResult:
    return RetrievalResult(
        "claim-1", ["cluster", "agent"], len(items), len(items), len(items), 3, items
    )


def test_decision_statuses_are_conservative_and_auditable() -> None:
    engine = EvidenceDecisionEngine()
    verified = engine.decide(
        claim(), retrieval([evidence("Cluster Agent connects to Rancher Server")])
    )
    candidate = engine.decide(
        claim(),
        retrieval([evidence("Cluster Agent tunnel", product_match=False, heading="Overview")]),
    )
    version = engine.decide(claim(), retrieval([evidence("Cluster Agent connects", version=False)]))
    manual = engine.decide(
        claim(),
        retrieval(
            [
                evidence(
                    "Cluster overview", terms=["cluster"], product_match=False, heading="Overview"
                )
            ]
        ),
    )

    assert verified.status == EvidenceDecisionStatus.VERIFIED_CANDIDATE
    assert candidate.status == EvidenceDecisionStatus.CANDIDATE_ONLY
    assert version.status == EvidenceDecisionStatus.VERSION_MISMATCH
    assert manual.status == EvidenceDecisionStatus.MANUAL_REVIEW_REQUIRED
    assert all(item.rule_audit for item in [verified, candidate, version, manual])


def test_remaining_decision_statuses_are_covered() -> None:
    engine = EvidenceDecisionEngine()
    contradicted = engine.decide(
        claim(), retrieval([evidence("not cluster agent connects to rancher server")])
    )
    partial = engine.decide(claim(), retrieval([evidence("Cluster Agent tunnel")]))
    insufficient = engine.decide(claim(), retrieval([]))
    conflicting = engine.decide(
        claim(),
        retrieval(
            [
                evidence("Cluster Agent connects to Rancher Server"),
                evidence("not cluster agent connects to rancher server"),
            ]
        ),
    )
    assert contradicted.status == EvidenceDecisionStatus.CONTRADICTED_CANDIDATE
    assert partial.status == EvidenceDecisionStatus.PARTIALLY_SUPPORTED
    assert insufficient.status == EvidenceDecisionStatus.INSUFFICIENT_EVIDENCE
    assert conflicting.status == EvidenceDecisionStatus.CONFLICTING_EVIDENCE


def test_batch_fact_inputs_are_identical_and_have_no_model_or_network_access() -> None:
    batch = EvidenceDecisionEngine().decide_batch(
        [(claim(), retrieval([evidence("Cluster Agent tunnel")]))]
    )

    payload = batch.review_inputs[0]
    assert payload.for_fact_a() == payload.for_fact_b()
    assert batch.model_call_count == batch.network_request_count == 0
    assert "output" not in payload.to_dict()


def test_offline_decision_benchmark_fixture_covers_primary_statuses() -> None:
    cases = Path("benchmarks/fixtures/evidence-decision-v1/cases.json").read_text(encoding="utf-8")
    assert all(
        status in cases
        for status in (
            "verified_candidate",
            "candidate_only",
            "version_mismatch",
            "manual_review_required",
        )
    )


def test_offline_decision_benchmark_metrics_are_deterministic() -> None:
    engine = EvidenceDecisionEngine()
    decisions = [
        engine.decide(claim(), retrieval([evidence("Cluster Agent connects to Rancher Server")])),
        engine.decide(claim(), retrieval([])),
    ]
    metrics = benchmark_decisions(
        [
            EvidenceDecisionStatus.VERIFIED_CANDIDATE,
            EvidenceDecisionStatus.INSUFFICIENT_EVIDENCE,
        ],
        decisions,
    )

    assert metrics.to_dict() == {
        "total_cases": 2,
        "correct_status_count": 2,
        "precision": 1.0,
        "citation_accuracy": 0.5,
        "manual_review_rate": 0.0,
    }
