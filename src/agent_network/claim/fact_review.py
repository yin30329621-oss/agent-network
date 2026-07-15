"""Mock-only dual Fact review and deterministic reconciliation contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
from math import ceil
from typing import Callable, Protocol

from agent_network.claim.evidence_decision import FactReviewInput


class ReviewAuditStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    INVALID_CITATION = "invalid_citation"


class ReconciliationStatus(StrEnum):
    CONSENSUS = "consensus"
    ENGINE_CHALLENGED = "engine_challenged"
    REVIEWER_DISAGREEMENT = "reviewer_disagreement"
    INVALID_CITATION = "invalid_citation"
    SINGLE_REVIEWER_AVAILABLE = "single_reviewer_available"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class CanonicalFactStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    MANUAL_REVIEW = "manual_review"
    UNKNOWN = "unknown"


def normalize_fact_status(status: object) -> CanonicalFactStatus:
    value = str(status or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "active": CanonicalFactStatus.SUPPORTED,
        "supported": CanonicalFactStatus.SUPPORTED,
        "verified": CanonicalFactStatus.SUPPORTED,
        "verified_candidate": CanonicalFactStatus.SUPPORTED,
        "partially_supported": CanonicalFactStatus.PARTIALLY_SUPPORTED,
        "candidate_only": CanonicalFactStatus.PARTIALLY_SUPPORTED,
        "unsupported": CanonicalFactStatus.UNSUPPORTED,
        "not_supported": CanonicalFactStatus.UNSUPPORTED,
        "withdrawn": CanonicalFactStatus.UNSUPPORTED,
        "insufficient_evidence": CanonicalFactStatus.INSUFFICIENT_EVIDENCE,
        "unverifiable": CanonicalFactStatus.INSUFFICIENT_EVIDENCE,
        "manual_review": CanonicalFactStatus.MANUAL_REVIEW,
        "manual_review_required": CanonicalFactStatus.MANUAL_REVIEW,
        "needs_review": CanonicalFactStatus.MANUAL_REVIEW,
    }
    return aliases.get(value, CanonicalFactStatus.UNKNOWN)


@dataclass(slots=True)
class FactReviewResult:
    reviewer_id: str
    decision: str
    recommended_status: str
    cited_chunk_ids: list[str]
    reasoning_summary: str
    limitations: list[str] = field(default_factory=list)
    audit_status: ReviewAuditStatus = ReviewAuditStatus.COMPLETED
    parse_status: str = "parsed"
    audit_warnings: list[str] = field(default_factory=list)
    claim_id: str | None = None
    response_metadata: dict[str, object] = field(default_factory=dict)
    normalized_status: str = ""

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["audit_status"] = self.audit_status.value
        return result


class FactReviewer(Protocol):
    reviewer_id: str

    def review_batch(self, inputs: list[dict[str, object]]) -> list[FactReviewResult]: ...


class FakeFactReviewer:
    """Deterministic test adapter; receives only its own copied input batch."""

    def __init__(
        self,
        reviewer_id: str,
        handler: Callable[[dict[str, object]], FactReviewResult] | None = None,
        fail: bool = False,
    ) -> None:
        self.reviewer_id = reviewer_id
        self.handler = handler
        self.fail = fail
        self.received_batches: list[list[dict[str, object]]] = []

    def review_batch(self, inputs: list[dict[str, object]]) -> list[FactReviewResult]:
        self.received_batches.append(deepcopy(inputs))
        if self.fail:
            raise RuntimeError("mock reviewer failed")
        return [
            self.handler(item)
            if self.handler is not None
            else FactReviewResult(self.reviewer_id, "candidate_only", "candidate_only", [], "Mock")
            for item in inputs
        ]


@dataclass(frozen=True, slots=True)
class DualReviewBudget:
    claims_per_batch: int | None = None
    max_claims_per_batch: int = 3
    max_batches: int = 10
    max_output_tokens_per_call: int = 1200
    max_estimated_tokens: int | None = None
    max_input_tokens_per_batch: int = 8000
    expected_output_tokens_per_claim: int = 300
    max_expected_output_tokens_per_batch: int = 1200
    max_evidence_chars_per_batch: int = 8000
    output_safety_ratio: float = 0.8

    @property
    def effective_max_claims_per_batch(self) -> int:
        return self.claims_per_batch or self.max_claims_per_batch


@dataclass(slots=True)
class DualReviewBudgetEstimate:
    estimated_fact_a_calls: int
    estimated_fact_b_calls: int
    estimated_total_calls: int
    estimated_tokens: int
    budget_exceeded: bool
    batch_sizes: list[int] = field(default_factory=list)
    provider_estimates: dict[str, dict[str, int | bool]] = field(default_factory=dict)


@dataclass(slots=True)
class FactReconciliation:
    claim_id: str
    status: ReconciliationStatus
    fact_a: FactReviewResult | None
    fact_b: FactReviewResult | None
    warnings: list[str] = field(default_factory=list)
    needs_manual_review: bool = False
    manual_review_reasons: list[str] = field(default_factory=list)
    review_priority: str = "normal"

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "status": self.status.value,
            "fact_a": self.fact_a.to_dict() if self.fact_a else None,
            "fact_b": self.fact_b.to_dict() if self.fact_b else None,
            "warnings": list(self.warnings),
            "needs_manual_review": self.needs_manual_review,
            "manual_review_reasons": list(self.manual_review_reasons),
            "review_priority": self.review_priority,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "FactReconciliation":
        def result_from_dict(raw: object) -> FactReviewResult | None:
            if not isinstance(raw, dict):
                return None
            audit_value = raw.get("audit_status", ReviewAuditStatus.COMPLETED)
            try:
                audit_status = ReviewAuditStatus(str(audit_value))
            except ValueError:
                audit_status = ReviewAuditStatus.COMPLETED
            def strings(name: str) -> list[str]:
                values = raw.get(name, [])
                return [item for item in values if isinstance(item, str)] if isinstance(values, list) else []
            metadata = raw.get("response_metadata", {})
            return FactReviewResult(
                reviewer_id=str(raw.get("reviewer_id", "")),
                decision=str(raw.get("decision", "")),
                recommended_status=str(raw.get("recommended_status", "")),
                cited_chunk_ids=strings("cited_chunk_ids"),
                reasoning_summary=str(raw.get("reasoning_summary", "")),
                limitations=strings("limitations"),
                audit_status=audit_status,
                parse_status=str(raw.get("parse_status", "parsed")),
                audit_warnings=strings("audit_warnings"),
                claim_id=str(raw["claim_id"]) if raw.get("claim_id") is not None else None,
                response_metadata=dict(metadata) if isinstance(metadata, dict) else {},
                normalized_status=str(raw.get("normalized_status", "")),
            )
        return cls(
            claim_id=str(value.get("claim_id", "")),
            status=ReconciliationStatus(str(value.get("status", ReconciliationStatus.MANUAL_REVIEW_REQUIRED))),
            fact_a=result_from_dict(value.get("fact_a")),
            fact_b=result_from_dict(value.get("fact_b")),
            warnings=[
                item for item in value.get("warnings", []) if isinstance(item, str)
            ] if isinstance(value.get("warnings", []), list) else [],
            needs_manual_review=bool(value.get("needs_manual_review", False)),
            manual_review_reasons=[
                item for item in value.get("manual_review_reasons", []) if isinstance(item, str)
            ] if isinstance(value.get("manual_review_reasons", []), list) else [],
            review_priority=str(value.get("review_priority", "normal")),
        )


class DualFactReviewCoordinator:
    def __init__(
        self, fact_a: FactReviewer, fact_b: FactReviewer, budget: DualReviewBudget | None = None
    ) -> None:
        self.fact_a, self.fact_b = fact_a, fact_b
        self.budget = budget or DualReviewBudget()
        self.network_request_count = 0
        self.model_call_count = 0

    def estimate(self, inputs: list[FactReviewInput]) -> DualReviewBudgetEstimate:
        limits = self._provider_limits()
        batches = self._plan_batches(inputs, limits)
        batch_sizes = [len(batch) for batch in batches] if batches is not None else []
        provider_estimates: dict[str, dict[str, int | bool]] = {}
        estimated_tokens = 0
        budget_exceeded = batches is None or len(batch_sizes) > self.budget.max_batches
        for reviewer_id, (max_tokens, timeout_seconds) in limits.items():
            input_tokens = sum(self._input_tokens(batch) for batch in batches or [])
            output_tokens = sum(
                len(batch) * self.budget.expected_output_tokens_per_claim for batch in batches or []
            )
            provider_exceeded = any(
                len(batch) * self.budget.expected_output_tokens_per_claim
                > min(
                    self.budget.max_expected_output_tokens_per_batch,
                    int(max_tokens * self.budget.output_safety_ratio),
                )
                for batch in batches or []
            )
            provider_exceeded = provider_exceeded or budget_exceeded
            provider_estimates[reviewer_id] = {
                "batch_count": len(batch_sizes),
                "estimated_input_tokens": input_tokens,
                "estimated_output_tokens": output_tokens,
                "configured_max_tokens": max_tokens,
                "timeout_seconds": timeout_seconds,
                "budget_exceeded": provider_exceeded,
            }
            estimated_tokens += input_tokens + output_tokens
        budget_exceeded = budget_exceeded or any(
            bool(value["budget_exceeded"]) for value in provider_estimates.values()
        )
        if self.budget.max_estimated_tokens is not None:
            budget_exceeded = budget_exceeded or estimated_tokens > self.budget.max_estimated_tokens
        return DualReviewBudgetEstimate(
            len(batch_sizes),
            len(batch_sizes),
            len(batch_sizes) * 2,
            estimated_tokens,
            budget_exceeded,
            batch_sizes,
            provider_estimates,
        )

    def review_batch(self, inputs: list[FactReviewInput]) -> list[FactReconciliation]:
        estimate = self.estimate(inputs)
        if estimate.budget_exceeded:
            raise ValueError("dual Fact review budget exceeded")
        reconciliations: list[FactReconciliation] = []
        batches = self._plan_batches(inputs, self._provider_limits())
        if batches is None:
            raise ValueError("dual Fact review batch cannot satisfy token budget")
        for input_batch in batches:
            a_inputs = [deepcopy(item.for_fact_a()) for item in input_batch]
            b_inputs = [deepcopy(item.for_fact_b()) for item in input_batch]
            try:
                a_results = self.fact_a.review_batch(a_inputs)
            except Exception:
                a_results = []
            try:
                b_results = self.fact_b.review_batch(b_inputs)
            except Exception:
                b_results = []
            reconciliations.extend(
                self._reconcile(
                    item,
                    a_results[index] if index < len(a_results) else None,
                    b_results[index] if index < len(b_results) else None,
                )
                for index, item in enumerate(input_batch)
            )
        return reconciliations

    def _provider_limits(self) -> dict[str, tuple[int, int]]:
        limits: dict[str, tuple[int, int]] = {}
        for reviewer, fallback_timeout in (
            (self.fact_a, 90),
            (self.fact_b, 180),
        ):
            config = getattr(reviewer, "config", None)
            reviewer_id = str(getattr(reviewer, "reviewer_id", "reviewer"))
            limits[reviewer_id] = (
                int(getattr(config, "max_tokens", 1200)),
                int(getattr(config, "timeout_seconds", fallback_timeout)),
            )
        return limits

    def _plan_batches(
        self,
        inputs: list[FactReviewInput],
        provider_limits: dict[str, tuple[int, int]],
    ) -> list[list[FactReviewInput]] | None:
        if not inputs:
            return []
        max_claims = self.budget.effective_max_claims_per_batch
        if max_claims <= 0:
            return None
        batch_count = ceil(len(inputs) / max_claims)
        base, remainder = divmod(len(inputs), batch_count)
        sizes = [base + (index < remainder) for index in range(batch_count)]
        batches: list[list[FactReviewInput]] = []
        offset = 0
        for size in sizes:
            batches.append(inputs[offset : offset + size])
            offset += size
        index = 0
        while index < len(batches):
            batch = batches[index]
            if self._batch_within_budget(batch, provider_limits):
                index += 1
                continue
            if len(batch) <= 1:
                return None
            midpoint = (len(batch) + 1) // 2
            batches[index : index + 1] = [batch[:midpoint], batch[midpoint:]]
        return batches

    def _batch_within_budget(
        self,
        batch: list[FactReviewInput],
        provider_limits: dict[str, tuple[int, int]],
    ) -> bool:
        if not batch:
            return False
        if self._input_tokens(batch) > self.budget.max_input_tokens_per_batch:
            return False
        evidence_chars = sum(
            len(str(entry.get("text", "")))
            for item in batch
            for entry in item.decision.get("evidence", [])
            if isinstance(entry, dict)
        )
        if evidence_chars > self.budget.max_evidence_chars_per_batch:
            return False
        expected_output = len(batch) * self.budget.expected_output_tokens_per_claim
        if expected_output > self.budget.max_expected_output_tokens_per_batch:
            return False
        return all(
            expected_output <= int(max_tokens * self.budget.output_safety_ratio)
            for max_tokens, _ in provider_limits.values()
        )

    @staticmethod
    def _input_tokens(batch: list[FactReviewInput]) -> int:
        return sum(
            ceil(len(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True)) / 4)
            for item in batch
        )

    def _reconcile(
        self, item: FactReviewInput, a: FactReviewResult | None, b: FactReviewResult | None
    ) -> FactReconciliation:
        claim_id = item.claim["claim_id"]
        allowed = {entry["chunk_id"] for entry in item.decision.get("evidence", [])}
        invalid = [
            result
            for result in (a, b)
            if result
            and (
                result.audit_status == ReviewAuditStatus.INVALID_CITATION
                or not set(result.cited_chunk_ids).issubset(allowed)
            )
        ]
        if invalid:
            for result in invalid:
                result.audit_status = ReviewAuditStatus.INVALID_CITATION
                result.audit_warnings.append("unknown_chunk_id_rejected")
                result.cited_chunk_ids = [
                    value for value in result.cited_chunk_ids if value in allowed
                ]
            return FactReconciliation(
                claim_id,
                ReconciliationStatus.INVALID_CITATION,
                a,
                b,
                needs_manual_review=True,
                manual_review_reasons=["invalid_citation"],
                review_priority="high",
            )
        available_a = a if a and a.audit_status != ReviewAuditStatus.FAILED else None
        available_b = b if b and b.audit_status != ReviewAuditStatus.FAILED else None
        if available_a is None and available_b is None:
            return FactReconciliation(
                claim_id,
                ReconciliationStatus.MANUAL_REVIEW_REQUIRED,
                a,
                b,
                needs_manual_review=True,
                manual_review_reasons=["both_reviewers_unavailable"],
                review_priority="high",
            )
        if available_a is None or available_b is None:
            return FactReconciliation(
                claim_id,
                ReconciliationStatus.SINGLE_REVIEWER_AVAILABLE,
                a,
                b,
                needs_manual_review=True,
                manual_review_reasons=["single_reviewer_available"],
                review_priority="high",
            )
        a_status = normalize_fact_status(available_a.recommended_status)
        b_status = normalize_fact_status(available_b.recommended_status)
        available_a.normalized_status = a_status.value
        available_b.normalized_status = b_status.value
        engine_status = normalize_fact_status(item.decision.get("status"))
        blocked_engine_statuses = {
            CanonicalFactStatus.UNSUPPORTED,
            CanonicalFactStatus.INSUFFICIENT_EVIDENCE,
            CanonicalFactStatus.MANUAL_REVIEW,
        }
        positive_reviewer_statuses = {
            CanonicalFactStatus.SUPPORTED,
            CanonicalFactStatus.PARTIALLY_SUPPORTED,
        }
        if (
            engine_status in blocked_engine_statuses
            and (a_status in positive_reviewer_statuses or b_status in positive_reviewer_statuses)
        ) or (
            engine_status == CanonicalFactStatus.PARTIALLY_SUPPORTED
            and (a_status == CanonicalFactStatus.SUPPORTED or b_status == CanonicalFactStatus.SUPPORTED)
        ):
            return FactReconciliation(
                claim_id,
                ReconciliationStatus.MANUAL_REVIEW_REQUIRED,
                a,
                b,
                needs_manual_review=True,
                manual_review_reasons=["evidence_gate_blocked_upgrade"],
                review_priority="high",
            )
        if a_status == b_status:
            status = (
                ReconciliationStatus.ENGINE_CHALLENGED
                if a_status != engine_status
                else ReconciliationStatus.CONSENSUS
            )
            return FactReconciliation(claim_id, status, a, b)
        return FactReconciliation(
            claim_id,
            ReconciliationStatus.REVIEWER_DISAGREEMENT,
            a,
            b,
            needs_manual_review=True,
            manual_review_reasons=["reviewer_status_disagreement"],
            review_priority="normal",
        )
