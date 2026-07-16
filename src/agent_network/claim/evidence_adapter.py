"""Offline ClaimRegistry to EvidenceDecision adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent_network.claim.claim import Claim
from agent_network.claim.evidence_decision import (
    EvidenceDecision,
    EvidenceDecisionEngine,
)
from agent_network.claim.registry import ClaimRegistry
from agent_network.evidence.offline_retrieval import RetrievalResult


class RetrievalProvider(Protocol):
    """Offline retrieval boundary used by the adapter."""

    network_request_count: int
    model_call_count: int

    def retrieve(self, claim: Claim, *, top_k: int | None = None) -> RetrievalResult: ...


@dataclass(frozen=True, slots=True)
class EvidenceAdapterConfig:
    """Explicit limits for one offline adapter run."""

    top_k: int = 5
    cache_directory: str | None = None
    document_ids: tuple[str, ...] | None = None
    document_type: str | None = None
    offline_only: bool = True

    def __post_init__(self) -> None:
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")
        if not self.offline_only:
            raise ValueError("M2.1 only supports offline retrieval")


@dataclass(frozen=True, slots=True)
class AdapterFailure:
    claim_id: str
    stage: str
    code: str
    safe_message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "claim_id": self.claim_id,
            "stage": self.stage,
            "code": self.code,
            "safe_message": self.safe_message,
        }


@dataclass(frozen=True, slots=True)
class ClaimEvidenceAdapterRequest:
    registry: ClaimRegistry
    config: EvidenceAdapterConfig = field(default_factory=EvidenceAdapterConfig)


@dataclass(slots=True)
class ClaimEvidenceAdapterResult:
    claim_id: str
    retrieval: RetrievalResult | None = None
    decision: EvidenceDecision | None = None
    failure: AdapterFailure | None = None


@dataclass(slots=True)
class ClaimEvidenceAdapterBatchResult:
    results: list[ClaimEvidenceAdapterResult]
    total_claim_count: int
    completed_claim_count: int
    failed_claim_count: int
    status_distribution: dict[str, int] = field(default_factory=dict)
    evidence_coverage_count: int = 0
    model_call_count: int = 0
    network_request_count: int = 0

    @property
    def claim_ids(self) -> list[str]:
        return [result.claim_id for result in self.results]


class ClaimEvidenceAdapter:
    """Compose existing offline retrieval and deterministic evidence decisions."""

    def __init__(
        self,
        retriever: RetrievalProvider,
        *,
        decision_engine: EvidenceDecisionEngine | None = None,
        config: EvidenceAdapterConfig | None = None,
    ) -> None:
        self.retriever = retriever
        self.decision_engine = decision_engine or EvidenceDecisionEngine()
        self.config = config or EvidenceAdapterConfig()

    def adapt(
        self, request: ClaimEvidenceAdapterRequest | ClaimRegistry
    ) -> ClaimEvidenceAdapterBatchResult:
        if isinstance(request, ClaimEvidenceAdapterRequest):
            registry = request.registry
            config = request.config
        else:
            registry = request
            config = self.config
        results = [
            ClaimEvidenceAdapterResult(claim_id=claim.claim_id) for claim in registry
        ]
        pairs: list[tuple[Claim, RetrievalResult]] = []
        pair_indexes: list[int] = []

        for index, claim in enumerate(registry):
            try:
                retrieval = self.retriever.retrieve(claim, top_k=config.top_k)
            except Exception:
                results[index].failure = AdapterFailure(
                    claim_id=claim.claim_id,
                    stage="retrieval",
                    code="retrieval_failed",
                    safe_message="Evidence retrieval failed.",
                )
                continue

            results[index].retrieval = retrieval
            if retrieval.claim_id != claim.claim_id:
                results[index].failure = AdapterFailure(
                    claim_id=claim.claim_id,
                    stage="alignment",
                    code="claim_id_mismatch",
                    safe_message="Retrieval result did not match the Claim ID.",
                )
                continue
            pairs.append((claim, retrieval))
            pair_indexes.append(index)

        if pairs:
            try:
                decision_batch = self.decision_engine.decide_batch(pairs)
            except Exception:
                for index, (claim, _) in zip(pair_indexes, pairs, strict=True):
                    results[index].failure = AdapterFailure(
                        claim_id=claim.claim_id,
                        stage="decision",
                        code="decision_failed",
                        safe_message="Evidence decision failed.",
                    )
            else:
                decisions = {decision.claim_id: decision for decision in decision_batch.decisions}
                for index, (claim, _) in zip(pair_indexes, pairs, strict=True):
                    decision = decisions.get(claim.claim_id)
                    if decision is None:
                        results[index].failure = AdapterFailure(
                            claim_id=claim.claim_id,
                            stage="alignment",
                            code="decision_claim_id_missing",
                            safe_message="Evidence decision did not contain the Claim ID.",
                        )
                    else:
                        results[index].decision = decision

        status_distribution: dict[str, int] = {}
        evidence_coverage_count = 0
        completed = 0
        for result in results:
            if result.failure is not None:
                continue
            completed += 1
            if result.decision is not None:
                status = result.decision.status.value
                status_distribution[status] = status_distribution.get(status, 0) + 1
            if result.retrieval is not None and result.retrieval.results:
                evidence_coverage_count += 1

        return ClaimEvidenceAdapterBatchResult(
            results=results,
            total_claim_count=len(results),
            completed_claim_count=completed,
            failed_claim_count=len(results) - completed,
            status_distribution=status_distribution,
            evidence_coverage_count=evidence_coverage_count,
            model_call_count=int(getattr(self.retriever, "model_call_count", 0)),
            network_request_count=int(getattr(self.retriever, "network_request_count", 0)),
        )
