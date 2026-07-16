"""Model-free EvidenceDecisionBatch to FactReviewInput adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_network.claim.evidence_adapter import AdapterFailure
from agent_network.claim.evidence_decision import (
    EvidenceDecisionBatch,
    FactReviewInput,
)


@dataclass(slots=True)
class FactReviewInputAdapterResult:
    """One ordered adapter slot, either ready for review or failed."""

    claim_id: str
    input: FactReviewInput | None = None
    failure: AdapterFailure | None = None


@dataclass(slots=True)
class FactReviewInputAdapterBatchResult:
    """Stable M2.2a output with ready inputs and explicit failure slots."""

    inputs: list[FactReviewInput]
    failure_slots: list[AdapterFailure]
    claim_ids: list[str]
    total_count: int
    ready_count: int
    failed_count: int
    cost_metadata: dict[str, int | bool] = field(default_factory=dict)
    results: list[FactReviewInputAdapterResult] = field(default_factory=list)


class FactReviewInputAdapter:
    """Adapt completed evidence decisions without performing any I/O."""

    def adapt(self, batch: EvidenceDecisionBatch) -> FactReviewInputAdapterBatchResult:
        slots: list[FactReviewInputAdapterResult] = []
        inputs: list[FactReviewInput] = []
        failures: list[AdapterFailure] = []
        claim_ids = [
            str(review_input.claim.get("claim_id", ""))
            for review_input in batch.review_inputs
        ]
        decision_by_claim: dict[str, Any] = {}
        duplicate_decision_ids: set[str] = set()
        for decision in batch.decisions:
            claim_id = str(decision.claim_id)
            if claim_id in decision_by_claim:
                duplicate_decision_ids.add(claim_id)
            decision_by_claim[claim_id] = decision

        for index, review_input in enumerate(batch.review_inputs):
            claim_id = str(review_input.claim.get("claim_id", ""))
            decision = decision_by_claim.get(claim_id)
            if decision is None and index < len(batch.decisions):
                decision = batch.decisions[index]
            failure = self._validate_slot(
                review_input,
                decision,
                duplicate_decision_ids,
            )
            slot = FactReviewInputAdapterResult(claim_id=claim_id)
            if failure is None:
                slot.input = review_input
                inputs.append(review_input)
            else:
                slot.failure = failure
                failures.append(failure)
            slots.append(slot)

        return FactReviewInputAdapterBatchResult(
            inputs=inputs,
            failure_slots=failures,
            claim_ids=claim_ids,
            total_count=len(claim_ids),
            ready_count=len(inputs),
            failed_count=len(failures),
            cost_metadata={
                "model_call_count": int(batch.model_call_count),
                "network_request_count": int(batch.network_request_count),
                "adapter_model_call_count": 0,
                "adapter_network_request_count": 0,
            },
            results=slots,
        )

    @staticmethod
    def _validate_slot(
        review_input: FactReviewInput,
        decision: Any,
        duplicate_decision_ids: set[str],
    ) -> AdapterFailure | None:
        claim_id = str(review_input.claim.get("claim_id", ""))
        if not claim_id:
            return AdapterFailure(
                claim_id="",
                stage="alignment",
                code="claim_id_missing",
                safe_message="FactReviewInput is missing a Claim ID.",
            )
        if decision is None:
            return AdapterFailure(
                claim_id=claim_id,
                stage="alignment",
                code="decision_claim_id_missing",
                safe_message="Evidence decision did not match the Claim ID.",
            )
        if str(decision.claim_id) != claim_id:
            return AdapterFailure(
                claim_id=claim_id,
                stage="alignment",
                code="decision_claim_id_mismatch",
                safe_message="Evidence decision has a different Claim ID.",
            )
        if claim_id in duplicate_decision_ids:
            return AdapterFailure(
                claim_id=claim_id,
                stage="alignment",
                code="duplicate_decision_claim_id",
                safe_message="Multiple evidence decisions matched the Claim ID.",
            )

        decision_payload = review_input.decision
        retrieval_payload = review_input.retrieval
        if decision_payload.get("claim_id") != claim_id:
            return AdapterFailure(
                claim_id=claim_id,
                stage="alignment",
                code="decision_input_claim_id_mismatch",
                safe_message="FactReviewInput decision has a different Claim ID.",
            )
        if retrieval_payload.get("claim_id") != claim_id:
            return AdapterFailure(
                claim_id=claim_id,
                stage="alignment",
                code="retrieval_claim_id_mismatch",
                safe_message="FactReviewInput retrieval has a different Claim ID.",
            )

        decision_chunks = _chunk_ids(decision_payload.get("evidence"))
        retrieval_chunks = _chunk_ids(retrieval_payload.get("results"))
        if not decision_chunks.issubset(retrieval_chunks):
            return AdapterFailure(
                claim_id=claim_id,
                stage="alignment",
                code="evidence_source_mismatch",
                safe_message="Decision evidence was not present in retrieval results.",
            )
        cited_chunks = _chunk_ids(decision_payload.get("cited_chunk_ids"))
        if not cited_chunks.issubset(decision_chunks):
            return AdapterFailure(
                claim_id=claim_id,
                stage="citation",
                code="invalid_citation",
                safe_message="Citation did not reference decision evidence.",
            )
        return None


def _chunk_ids(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    if value and all(isinstance(item, str) for item in value):
        return set(value)
    return {
        str(item["chunk_id"])
        for item in value
        if isinstance(item, dict) and isinstance(item.get("chunk_id"), str)
    }
