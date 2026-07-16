"""M2.2b integration boundary for ready Fact review inputs."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_network.claim.evidence_adapter import AdapterFailure
from agent_network.claim.fact_adapter import FactReviewInputAdapterBatchResult
from agent_network.claim.fact_review import (
    DualFactReviewCoordinator,
    FactReconciliation,
)


@dataclass(slots=True)
class DualFactCoordinatorIntegrationResult:
    """Coordinator output together with adapter failure slots."""

    claim_ids: list[str]
    reconciliations: list[FactReconciliation]
    failure_slots: list[AdapterFailure]
    total_count: int
    ready_count: int
    failed_count: int
    cost_metadata: dict[str, int | bool] = field(default_factory=dict)


class FactReviewInputCoordinatorAdapter:
    """Pass only ready adapter inputs to the existing coordinator."""

    def __init__(self, coordinator: DualFactReviewCoordinator) -> None:
        self.coordinator = coordinator

    def review(
        self, adapter_result: FactReviewInputAdapterBatchResult
    ) -> DualFactCoordinatorIntegrationResult:
        failure_slots = list(adapter_result.failure_slots)
        input_ids = [
            str(review_input.claim["claim_id"])
            for review_input in adapter_result.inputs
        ]
        estimated_calls = 0
        actual_reviewer_calls = 0
        if adapter_result.inputs:
            estimate = self.coordinator.estimate(adapter_result.inputs)
            estimated_calls = estimate.estimated_total_calls
            if estimate.budget_exceeded:
                failure_slots.extend(
                    _failure(claim_id, "budget_exceeded", "Coordinator budget was exceeded.")
                    for claim_id in input_ids
                )
                return self._result(
                    adapter_result,
                    input_ids,
                    [],
                    failure_slots,
                    estimated_calls,
                    actual_reviewer_calls,
                )
            try:
                reconciliations = self.coordinator.review_batch(adapter_result.inputs)
                actual_reviewer_calls = estimated_calls
            except Exception:
                failure_slots.extend(
                    _failure(claim_id, "coordinator_failed", "Dual Fact review failed.")
                    for claim_id in input_ids
                )
                return self._result(
                    adapter_result,
                    input_ids,
                    [],
                    failure_slots,
                    estimated_calls,
                    actual_reviewer_calls,
                )
        else:
            reconciliations = []

        aligned, alignment_failures = _align_reconciliations(
            input_ids, reconciliations
        )
        failure_slots.extend(alignment_failures)
        return self._result(
            adapter_result,
            input_ids,
            aligned,
            failure_slots,
            estimated_calls,
            actual_reviewer_calls,
        )

    def _result(
        self,
        adapter_result: FactReviewInputAdapterBatchResult,
        input_ids: list[str],
        reconciliations: list[FactReconciliation],
        failure_slots: list[AdapterFailure],
        estimated_calls: int,
        actual_reviewer_calls: int,
    ) -> DualFactCoordinatorIntegrationResult:
        return DualFactCoordinatorIntegrationResult(
            claim_ids=list(adapter_result.claim_ids),
            reconciliations=reconciliations,
            failure_slots=failure_slots,
            total_count=adapter_result.total_count,
            ready_count=len(reconciliations),
            failed_count=len(failure_slots),
            cost_metadata={
                "estimated_reviewer_calls": estimated_calls,
                "actual_reviewer_calls": actual_reviewer_calls,
                "coordinator_model_call_count": int(
                    self.coordinator.model_call_count
                ),
                "adapter_model_call_count": int(
                    adapter_result.cost_metadata.get("adapter_model_call_count", 0)
                ),
                "network_request_count": int(
                    adapter_result.cost_metadata.get("network_request_count", 0)
                ),
            },
        )


def _align_reconciliations(
    input_ids: list[str], reconciliations: list[FactReconciliation]
) -> tuple[list[FactReconciliation], list[AdapterFailure]]:
    aligned: list[FactReconciliation] = []
    failures: list[AdapterFailure] = []
    for index, claim_id in enumerate(input_ids):
        reconciliation = reconciliations[index] if index < len(reconciliations) else None
        if reconciliation is None or reconciliation.claim_id != claim_id:
            failures.append(
                _failure(
                    claim_id,
                    "reconciliation_alignment",
                    "Reconciliation Claim ID did not match the input Claim ID.",
                )
            )
            continue
        aligned.append(reconciliation)
    if len(reconciliations) > len(input_ids):
        failures.extend(
            _failure(
                reconciliation.claim_id,
                "reconciliation_alignment",
                "Reconciliation returned an unexpected Claim ID.",
            )
            for reconciliation in reconciliations[len(input_ids) :]
        )
    return aligned, failures


def _failure(claim_id: str, code: str, message: str) -> AdapterFailure:
    return AdapterFailure(
        claim_id=claim_id,
        stage="coordinator",
        code=code,
        safe_message=message,
    )
