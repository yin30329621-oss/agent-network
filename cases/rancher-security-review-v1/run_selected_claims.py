"""Run the manually selected case Claims through the existing offline pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_network.claim import Claim, ClaimRegistry
from agent_network.claim.evidence_adapter import ClaimEvidenceAdapter
from agent_network.claim.evidence_decision import EvidenceDecisionBatch, FactReviewInput
from agent_network.claim.fact_adapter import FactReviewInputAdapter
from agent_network.claim.fact_coordinator_adapter import FactReviewInputCoordinatorAdapter
from agent_network.claim.fact_review import (
    DualFactReviewCoordinator,
    DualReviewBudget,
    FakeFactReviewer,
)
from agent_network.evidence.offline_retrieval import RetrievalResult


CASE_DIR = Path(__file__).resolve().parent
CLAIMS_PATH = CASE_DIR / "output" / "claims.json"
CANDIDATES_PATH = CASE_DIR / "output" / "fact-review-candidates.json"
DEFAULT_OUTPUT = CASE_DIR / "output" / "verification" / "selected-claims-verification.json"


class NoLocalEvidenceRetriever:
    """Explicit offline boundary used until this case has an evidence fixture."""

    network_request_count = 0
    model_call_count = 0

    def retrieve(self, claim: Claim, *, top_k: int | None = None) -> RetrievalResult:
        return RetrievalResult(
            claim_id=claim.claim_id,
            query_terms=[claim.normalized_text or claim.text],
            candidate_count=0,
            filtered_candidate_count=0,
            selected_count=0,
            top_k=top_k or 5,
            results=[],
            no_match_reason="case_has_no_local_evidence_fixture",
        )


def run(
    *,
    output_path: Path = DEFAULT_OUTPUT,
    batch_size: int = 3,
    offline: bool = False,
) -> dict[str, Any]:
    if not offline:
        raise ValueError("--offline is required; this runner has no network mode")
    if batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    registry = _load_selected_registry()
    retriever = NoLocalEvidenceRetriever()
    evidence = ClaimEvidenceAdapter(retriever).adapt(registry)
    decision_batch = _decision_batch(registry, evidence)
    fact_inputs = FactReviewInputAdapter().adapt(decision_batch)

    fact_a = FakeFactReviewer("fact_a")
    fact_b = FakeFactReviewer("fact_b")
    fact_a.config = type("Config", (), {"max_tokens": 4000, "timeout_seconds": 90})()
    fact_b.config = type("Config", (), {"max_tokens": 2200, "timeout_seconds": 180})()
    coordinator = DualFactReviewCoordinator(
        fact_a,
        fact_b,
        budget=DualReviewBudget(
            claims_per_batch=batch_size,
            max_batches=max(10, len(fact_inputs.inputs)),
            max_expected_output_tokens_per_batch=batch_size * 300,
        ),
    )
    dual_fact = FactReviewInputCoordinatorAdapter(coordinator).review(fact_inputs)
    claim_ids = [claim.claim_id for claim in registry]
    reconciliation_by_id = {item.claim_id: item for item in dual_fact.reconciliations}
    failure_by_id = {item.claim_id: item for item in dual_fact.failure_slots}

    reconciliation = []
    for claim_id in claim_ids:
        item = reconciliation_by_id.get(claim_id)
        failure = failure_by_id.get(claim_id)
        reconciliation.append(
            {
                "claim_id": claim_id,
                "status": item.status.value if item else "not_reviewed",
                "needs_manual_review": item.needs_manual_review if item else True,
                "failure_stage": failure.stage if failure else None,
                "failure_code": failure.code if failure else None,
            }
        )

    artifact = {
        "metadata": {
            "schema_version": "v0.4-case-selected-claims-v1",
            "case": "rancher-security-review-v1",
            "workflow": "selected_claims_dual_fact_offline",
            "evidence_mode": "no_local_evidence_fixture",
            "reviewer_mode": "fake",
            "batch_size": batch_size,
        },
        "claims": {
            "source": str(CLAIMS_PATH.relative_to(CASE_DIR.parent.parent)),
            "selected_source": str(CANDIDATES_PATH.relative_to(CASE_DIR.parent.parent)),
            "claims": [claim.to_dict() for claim in registry],
        },
        "evidence": {
            "results": [
                {
                    "claim_id": item.claim_id,
                    "retrieval": item.retrieval.to_dict() if item.retrieval else None,
                    "decision": item.decision.to_dict() if item.decision else None,
                    "failure": item.failure.to_dict() if item.failure else None,
                }
                for item in evidence.results
            ],
            "failure_slots": [item.failure.to_dict() for item in evidence.results if item.failure],
        },
        "fact_review": {
            "fact_a": [item.fact_a.to_dict() if item.fact_a else None for item in dual_fact.reconciliations],
            "fact_b": [item.fact_b.to_dict() if item.fact_b else None for item in dual_fact.reconciliations],
            "failure_slots": [item.to_dict() for item in dual_fact.failure_slots],
            "call_metadata": {
                **dual_fact.cost_metadata,
                "reviewer_mode": "fake",
                "model_call_count": 0,
                "network_request_count": 0,
            },
        },
        "reconciliation": reconciliation,
        "statistics": {
            "input_claim_count": len(claim_ids),
            "ready_claim_count": fact_inputs.ready_count,
            "failed_claim_count": fact_inputs.failed_count,
            "planned_reviewer_calls": int(dual_fact.cost_metadata.get("estimated_reviewer_calls", 0)),
            "fact_a_batches": int(dual_fact.cost_metadata.get("estimated_reviewer_calls", 0)) // 2,
            "fact_b_batches": int(dual_fact.cost_metadata.get("estimated_reviewer_calls", 0)) // 2,
            "actual_reviewer_batches": int(dual_fact.cost_metadata.get("actual_reviewer_calls", 0)),
            "model_call_count": 0,
            "network_request_count": 0,
            "claim_id_aligned": claim_ids == evidence.claim_ids == fact_inputs.claim_ids == dual_fact.claim_ids,
            "reconciliation_status_distribution": _status_distribution(reconciliation),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def _load_selected_registry() -> ClaimRegistry:
    claims_payload = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    candidate_payload = json.loads(CANDIDATES_PATH.read_text(encoding="utf-8"))
    by_id = {str(item["claim_id"]): item for item in claims_payload["claims"]}
    selected_ids = [str(item) for item in candidate_payload["selected_claim_ids"]]
    if len(selected_ids) != candidate_payload["selected_count"]:
        raise ValueError("candidate selected_count does not match selected_claim_ids")
    missing = [claim_id for claim_id in selected_ids if claim_id not in by_id]
    if missing:
        raise ValueError(f"candidate Claim IDs are missing from claims.json: {missing}")
    return ClaimRegistry(Claim.model_validate(by_id[claim_id]) for claim_id in selected_ids)


def _decision_batch(registry: ClaimRegistry, evidence) -> EvidenceDecisionBatch:
    claims = {claim.claim_id: claim for claim in registry}
    decisions = [item.decision for item in evidence.results if item.decision is not None]
    review_inputs = [
        FactReviewInput(
            claim=claims[item.claim_id].to_dict(),
            decision=item.decision.to_dict(),
            retrieval=item.retrieval.to_dict(),
        )
        for item in evidence.results
        if item.failure is None and item.decision is not None and item.retrieval is not None
    ]
    status_counts: dict[str, int] = {}
    for decision in decisions:
        status_counts[decision.status.value] = status_counts.get(decision.status.value, 0) + 1
    return EvidenceDecisionBatch(
        decisions=decisions,
        review_inputs=review_inputs,
        status_counts=status_counts,
        network_request_count=evidence.network_request_count,
        model_call_count=evidence.model_call_count,
    )


def _status_distribution(items: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        status = str(item["status"])
        result[status] = result.get(status, 0) + 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    artifact = run(output_path=args.output, batch_size=args.batch_size, offline=args.offline)
    print(json.dumps(artifact["statistics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
