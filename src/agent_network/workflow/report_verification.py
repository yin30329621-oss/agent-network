"""Report-level orchestration for offline M3.1 and M3.2 verification."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from agent_network.claim import ClaimExtractionRequest, DeterministicClaimExtractor
from agent_network.claim.evidence_adapter import (
    ClaimEvidenceAdapter,
    ClaimEvidenceAdapterBatchResult,
    ClaimEvidenceAdapterResult,
    RetrievalProvider,
)
from agent_network.claim.evidence_decision import EvidenceDecisionBatch, FactReviewInput
from agent_network.claim.fact_adapter import (
    FactReviewInputAdapter,
    FactReviewInputAdapterBatchResult,
)
from agent_network.claim.fact_coordinator_adapter import (
    DualFactCoordinatorIntegrationResult,
    FactReviewInputCoordinatorAdapter,
)
from agent_network.claim.fact_review import DualFactReviewCoordinator
from agent_network.claim.registry import ClaimRegistry


@dataclass(frozen=True, slots=True)
class OfflineReportVerificationConfig:
    top_k: int = 5
    source_name: str | None = None
    enable_dual_fact: bool = False
    reviewer_batch_size: int = 3


@dataclass(slots=True)
class OfflineReportVerificationResult:
    artifact: dict[str, Any]
    extraction: Any
    evidence: ClaimEvidenceAdapterBatchResult
    fact_inputs: FactReviewInputAdapterBatchResult
    dual_fact: DualFactCoordinatorIntegrationResult | None = None


class OfflineReportVerificationOrchestrator:
    """Compose extraction, evidence, Fact input, and optional Dual Fact adapters."""

    def __init__(
        self,
        retriever: RetrievalProvider,
        *,
        extractor: DeterministicClaimExtractor | None = None,
        config: OfflineReportVerificationConfig | None = None,
        coordinator: DualFactReviewCoordinator | None = None,
    ) -> None:
        self.retriever = retriever
        self.extractor = extractor or DeterministicClaimExtractor()
        self.config = config or OfflineReportVerificationConfig()
        self.coordinator = coordinator

    def run_file(
        self,
        report_path: str | Path,
        *,
        output_path: str | Path | None = None,
        source_name: str | None = None,
    ) -> OfflineReportVerificationResult:
        path = Path(report_path)
        result = self.run(
            path.read_text(encoding="utf-8"),
            source_name=source_name or self.config.source_name or path.name,
            source_file=str(path),
        )
        if output_path is not None:
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(result.artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return result

    def run(
        self,
        document_text: str,
        *,
        source_name: str | None = None,
        source_file: str | None = None,
    ) -> OfflineReportVerificationResult:
        stable_source = source_name or self.config.source_name or "report.md"
        extraction = self.extractor.extract(
            ClaimExtractionRequest(document_text=document_text, source_name=stable_source)
        )
        registry = ClaimRegistry(extraction.claims)
        evidence = ClaimEvidenceAdapter(self.retriever).adapt(registry)
        fact_inputs = FactReviewInputAdapter().adapt(
            _build_decision_batch(registry, evidence)
        )
        dual_fact = None
        if self.config.enable_dual_fact:
            if self.coordinator is None:
                raise ValueError("enable_dual_fact requires a DualFactReviewCoordinator")
            dual_fact = FactReviewInputCoordinatorAdapter(self.coordinator).review(
                _merge_fact_inputs(registry, evidence, fact_inputs)
            )
        artifact = _build_artifact(
            extraction=extraction,
            evidence=evidence,
            fact_inputs=fact_inputs,
            dual_fact=dual_fact,
            source_name=stable_source,
            source_file=source_file,
        )
        return OfflineReportVerificationResult(
            artifact, extraction, evidence, fact_inputs, dual_fact
        )


def _build_decision_batch(
    registry: ClaimRegistry,
    evidence: ClaimEvidenceAdapterBatchResult,
) -> EvidenceDecisionBatch:
    claims = {claim.claim_id: claim for claim in registry}
    decisions = []
    review_inputs: list[FactReviewInput] = []
    for result in evidence.results:
        if result.failure is not None or result.retrieval is None or result.decision is None:
            continue
        claim = claims.get(result.claim_id)
        if claim is None:
            continue
        decisions.append(result.decision)
        review_inputs.append(
            FactReviewInput(
                claim=claim.to_dict(),
                decision=result.decision.to_dict(),
                retrieval=result.retrieval.to_dict(),
            )
        )
    status_counts: dict[str, int] = {}
    for decision in decisions:
        status = decision.status.value
        status_counts[status] = status_counts.get(status, 0) + 1
    return EvidenceDecisionBatch(
        decisions=decisions,
        review_inputs=review_inputs,
        status_counts=status_counts,
        network_request_count=evidence.network_request_count,
        model_call_count=evidence.model_call_count,
    )


def _merge_fact_inputs(
    registry: ClaimRegistry,
    evidence: ClaimEvidenceAdapterBatchResult,
    fact_inputs: FactReviewInputAdapterBatchResult,
) -> FactReviewInputAdapterBatchResult:
    failures = [item.failure for item in evidence.results if item.failure is not None]
    failures.extend(fact_inputs.failure_slots)
    claim_ids = [claim.claim_id for claim in registry]
    return FactReviewInputAdapterBatchResult(
        inputs=fact_inputs.inputs,
        failure_slots=failures,
        claim_ids=claim_ids,
        total_count=len(claim_ids),
        ready_count=fact_inputs.ready_count,
        failed_count=len(claim_ids) - fact_inputs.ready_count,
        cost_metadata=dict(fact_inputs.cost_metadata),
        results=fact_inputs.results,
    )


def _build_artifact(
    *,
    extraction: Any,
    evidence: ClaimEvidenceAdapterBatchResult,
    fact_inputs: FactReviewInputAdapterBatchResult,
    dual_fact: DualFactCoordinatorIntegrationResult | None,
    source_name: str,
    source_file: str | None,
) -> dict[str, Any]:
    evidence_records = [_evidence_record(item) for item in evidence.results]
    failure_slots = [item.failure.to_dict() for item in evidence.results if item.failure]
    failure_slots.extend(item.to_dict() for item in fact_inputs.failure_slots)
    if dual_fact is not None:
        failure_slots.extend(item.to_dict() for item in dual_fact.failure_slots)
    failure_by_claim = {
        str(item["claim_id"]): item for item in failure_slots if item.get("claim_id")
    }
    claim_ids = [claim.claim_id for claim in extraction.claims]
    reconciliation_by_claim = {
        item.claim_id: item for item in dual_fact.reconciliations
    } if dual_fact is not None else {}
    reconciliation = []
    for claim_id in claim_ids:
        item = reconciliation_by_claim.get(claim_id)
        failure = failure_by_claim.get(claim_id, {})
        reconciliation.append(
            {
                "claim_id": claim_id,
                "status": item.status.value if item else "not_reviewed",
                "needs_manual_review": item.needs_manual_review if item else True,
                "failure_stage": failure.get("stage"),
                "failure_code": failure.get("code"),
            }
        )
    if dual_fact is None:
        fact_a: list[object] = []
        fact_b: list[object] = []
        call_metadata: dict[str, object] = {
            "model_call_count": int(evidence.model_call_count),
            "network_request_count": int(evidence.network_request_count),
        }
        reconciliation_executed = False
        model_calls = int(evidence.model_call_count)
    else:
        fact_a = [item.fact_a.to_dict() if item.fact_a else None for item in dual_fact.reconciliations]
        fact_b = [item.fact_b.to_dict() if item.fact_b else None for item in dual_fact.reconciliations]
        call_metadata = dict(dual_fact.cost_metadata)
        reconciliation_executed = True
        model_calls = int(dual_fact.cost_metadata.get("actual_reviewer_calls", 0))
    return {
        "metadata": {
            "schema_version": "v0.4-m3",
            "workflow": "offline_report_verification",
            "source_file": source_file,
            "source_name": source_name,
            "enable_dual_fact": dual_fact is not None,
        },
        "claims": extraction.to_dict(),
        "evidence": {
            "results": evidence_records,
            "failure_slots": [item for item in failure_slots if item.get("claim_id")],
        },
        "fact_review": {
            "fact_a": fact_a,
            "fact_b": fact_b,
            "call_metadata": call_metadata,
            "failure_slots": [item for item in failure_slots if item.get("claim_id")],
        },
        "reconciliation": reconciliation,
        "statistics": {
            "total_claim_count": len(claim_ids),
            "ready_claim_count": fact_inputs.ready_count,
            "failed_claim_count": len(claim_ids) - fact_inputs.ready_count,
            "model_call_count": model_calls,
            "network_request_count": int(evidence.network_request_count),
            "reconciliation_executed": reconciliation_executed,
        },
    }


def _evidence_record(result: ClaimEvidenceAdapterResult) -> dict[str, Any]:
    return {
        "claim_id": result.claim_id,
        "retrieval": result.retrieval.to_dict() if result.retrieval else None,
        "decision": result.decision.to_dict() if result.decision else None,
        "failure": result.failure.to_dict() if result.failure else None,
    }