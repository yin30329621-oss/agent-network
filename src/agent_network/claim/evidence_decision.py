"""Deterministic, model-free evidence decisions for a shared Fact review input."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from agent_network.claim.claim import Claim
from agent_network.evidence.offline_retrieval import RetrievalResult, SelectedEvidence


class EvidenceDecisionStatus(StrEnum):
    VERIFIED_CANDIDATE = "verified_candidate"
    CONTRADICTED_CANDIDATE = "contradicted_candidate"
    PARTIALLY_SUPPORTED = "partially_supported"
    CANDIDATE_ONLY = "candidate_only"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    VERSION_MISMATCH = "version_mismatch"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class RuleConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class RuleAudit:
    rule_id: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"rule_id": self.rule_id, "passed": self.passed, "detail": self.detail}


@dataclass(slots=True)
class EvidenceDecision:
    claim_id: str
    status: EvidenceDecisionStatus
    confidence: RuleConfidence
    evidence: list[SelectedEvidence]
    sufficiency_score: int
    rule_audit: list[RuleAudit]
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "claim_id": self.claim_id,
            "status": self.status.value,
            "confidence": self.confidence.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "sufficiency_score": self.sufficiency_score,
            "rule_audit": [item.to_dict() for item in self.rule_audit],
            "limitations": self.limitations,
        }


@dataclass(frozen=True, slots=True)
class FactReviewInput:
    """The exact same immutable contract is supplied to Fact A and Fact B."""

    claim: dict[str, Any]
    decision: dict[str, Any]
    retrieval: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"claim": self.claim, "decision": self.decision, "retrieval": self.retrieval}

    def for_fact_a(self) -> dict[str, Any]:
        return self.to_dict()

    def for_fact_b(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(slots=True)
class EvidenceDecisionBatch:
    decisions: list[EvidenceDecision]
    review_inputs: list[FactReviewInput]
    status_counts: dict[str, int]
    network_request_count: int = 0
    model_call_count: int = 0


class EvidenceDecisionEngine:
    """Conservative rules; relevance never becomes factual support by itself."""

    def decide(self, claim: Claim, retrieval: RetrievalResult) -> EvidenceDecision:
        evidence = list(retrieval.results)
        audit = [
            RuleAudit("has_evidence", bool(evidence), "Top-K evidence is present."),
            RuleAudit(
                "version_match",
                not any(item.version_match is False for item in evidence),
                "No selected evidence has a version mismatch.",
            ),
        ]
        if not evidence:
            return EvidenceDecision(
                claim.claim_id,
                EvidenceDecisionStatus.INSUFFICIENT_EVIDENCE,
                RuleConfidence.LOW,
                [],
                0,
                audit,
                [retrieval.no_match_reason or "No evidence was selected."],
            )
        if any(item.version_match is False for item in evidence):
            return EvidenceDecision(
                claim.claim_id,
                EvidenceDecisionStatus.VERSION_MISMATCH,
                RuleConfidence.LOW,
                evidence,
                0,
                audit,
                ["Version-mismatch evidence cannot verify this claim."],
            )
        support = [_contains_claim(claim, item) for item in evidence]
        contradiction = [_explicit_contradiction(claim, item) for item in evidence]
        audit.extend(
            [
                RuleAudit(
                    "exact_claim_text", any(support), "An excerpt contains the normalized claim."
                ),
                RuleAudit(
                    "explicit_contradiction",
                    any(contradiction),
                    "An excerpt explicitly negates the claim.",
                ),
            ]
        )
        score = max((_sufficiency(item, claim) for item in evidence), default=0)
        if any(support) and any(contradiction):
            status, confidence = EvidenceDecisionStatus.CONFLICTING_EVIDENCE, RuleConfidence.LOW
        elif any(contradiction):
            status, confidence = (
                EvidenceDecisionStatus.CONTRADICTED_CANDIDATE,
                RuleConfidence.MEDIUM,
            )
        elif any(support):
            status, confidence = EvidenceDecisionStatus.VERIFIED_CANDIDATE, RuleConfidence.HIGH
        elif score >= 3:
            status, confidence = EvidenceDecisionStatus.PARTIALLY_SUPPORTED, RuleConfidence.MEDIUM
        elif score >= 2:
            status, confidence = EvidenceDecisionStatus.CANDIDATE_ONLY, RuleConfidence.LOW
        else:
            status, confidence = EvidenceDecisionStatus.MANUAL_REVIEW_REQUIRED, RuleConfidence.LOW
        return EvidenceDecision(
            claim.claim_id,
            status,
            confidence,
            evidence,
            score,
            audit,
            ["Deterministic evidence decision; no semantic model judgment was used."],
        )

    def decide_batch(self, pairs: list[tuple[Claim, RetrievalResult]]) -> EvidenceDecisionBatch:
        decisions = [self.decide(claim, retrieval) for claim, retrieval in pairs]
        review_inputs = [
            FactReviewInput(claim.to_dict(), decision.to_dict(), retrieval.to_dict())
            for (claim, retrieval), decision in zip(pairs, decisions, strict=True)
        ]
        counts: dict[str, int] = {}
        for decision in decisions:
            counts[decision.status.value] = counts.get(decision.status.value, 0) + 1
        return EvidenceDecisionBatch(decisions, review_inputs, counts)


def _contains_claim(claim: Claim, evidence: SelectedEvidence) -> bool:
    normalized = (claim.normalized_text or claim.text).casefold().strip()
    excerpt = evidence.text_excerpt.casefold()
    return (
        len(normalized) >= 12
        and normalized in excerpt
        and f"not {normalized}" not in excerpt
        and f"does not {normalized}" not in excerpt
    )


def _explicit_contradiction(claim: Claim, evidence: SelectedEvidence) -> bool:
    text = evidence.text_excerpt.casefold()
    normalized = (claim.normalized_text or claim.text).casefold()
    return f"not {normalized}" in text or f"does not {normalized}" in text


def _sufficiency(evidence: SelectedEvidence, claim: Claim) -> int:
    claim_terms = set((claim.normalized_text or claim.text).casefold().split())
    return sum(
        (
            len(evidence.matched_terms) >= 2,
            bool(claim_terms.intersection(" ".join(evidence.heading_path).casefold().split())),
            evidence.product_match and evidence.component_match is not False,
            evidence.version_match is not False,
        )
    )
