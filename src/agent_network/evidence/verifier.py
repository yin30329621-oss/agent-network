"""Transparent offline verification status rules."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from agent_network.evidence.matcher import DeterministicEvidenceMatcher
from agent_network.evidence.schemas import (
    Claim,
    Evidence,
    EvidenceCoverage,
    EvidenceMatch,
    EvidenceStrength,
    VerificationResult,
    VerificationStatus,
)
from agent_network.evidence.sources import EvidenceSource


class VerificationReport(BaseModel):
    metadata: dict[str, Any]
    claim_count: int
    evidence_count: int
    status_counts: dict[str, int]
    claims: list[Claim]
    evidence: list[Evidence]
    verification_results: list[VerificationResult]
    execution_notes: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class OfflineEvidenceVerifier:
    def __init__(
        self,
        source: EvidenceSource,
        matcher: DeterministicEvidenceMatcher | None = None,
        relevance_threshold: float = 0.6,
    ) -> None:
        self.source = source
        self.matcher = matcher or DeterministicEvidenceMatcher()
        self.relevance_threshold = relevance_threshold
        self.model_call_count = 0

    def verify(self, claim: Claim) -> VerificationResult:
        verified_at = datetime.now(UTC)
        if not claim.requires_external_evidence:
            return _result(
                claim,
                VerificationStatus.NOT_APPLICABLE,
                "该 Claim 属于观点、建议或无需外部证据的内容。",
                verified_at=verified_at,
                requires_human_review=False,
            )

        evidence = self.source.search(claim)
        if not evidence:
            return _result(
                claim,
                VerificationStatus.NOT_VERIFIED,
                "未找到可用于支持或反驳该 Claim 的离线 Evidence；未验证不等于错误。",
                verified_at=verified_at,
            )

        matches = [self.matcher.match(claim, item) for item in evidence]
        by_id = {item.evidence_id: item for item in evidence}
        scoped = [
            match
            for match in matches
            if match.product_match and match.component_match and match.claim_type_match
        ]
        relevant_scoped = [
            match for match in scoped if match.effective_relevance >= self.relevance_threshold
        ]
        if relevant_scoped and all(match.version_match is False for match in relevant_scoped):
            return _result(
                claim,
                VerificationStatus.VERSION_MISMATCH,
                "Evidence 的产品和组件匹配，但版本范围与 Claim 不一致。",
                matches=matches,
                evidence=evidence,
                verified_at=verified_at,
                version_match=False,
            )

        eligible = [
            match
            for match in matches
            if match.eligible and match.effective_relevance >= self.relevance_threshold
        ]
        if not eligible:
            return _result(
                claim,
                VerificationStatus.INSUFFICIENT_EVIDENCE,
                "存在候选 Evidence，但产品、组件、类型、版本或相关性不足。",
                matches=matches,
                evidence=evidence,
                verified_at=verified_at,
            )

        selected = [by_id[match.evidence_id] for match in eligible]
        supporting = [item for item in selected if item.supports_claim]
        contradicting = [item for item in selected if item.contradicts_claim]
        if supporting and contradicting:
            status = VerificationStatus.CONFLICTING_SOURCES
            explanation = "同时存在支持和反驳该 Claim 的适用 Evidence，必须人工裁决。"
        elif contradicting:
            status = VerificationStatus.CONTRADICTED
            explanation = "适用的离线 Evidence 明确反驳该 Claim。"
        elif supporting and all(item.coverage == EvidenceCoverage.PARTIAL for item in supporting):
            status = VerificationStatus.PARTIALLY_VERIFIED
            explanation = "Evidence 只覆盖 Claim 的部分内容，不能视为完整核验。"
        elif supporting:
            status = VerificationStatus.VERIFIED
            explanation = "适用的离线 Evidence 明确支持该 Claim。"
        else:
            status = VerificationStatus.INSUFFICIENT_EVIDENCE
            explanation = "候选 Evidence 相关，但没有明确支持或反驳该 Claim。"

        return _result(
            claim,
            status,
            explanation,
            matches=matches,
            evidence=selected,
            supporting=supporting,
            contradicting=contradicting,
            verified_at=verified_at,
            version_match=_combined_version_match(eligible),
        )

    def verify_all(
        self,
        claims: list[Claim],
        *,
        fixture_id: str,
        fixture_notice: str,
    ) -> VerificationReport:
        results = [self.verify(claim) for claim in claims]
        evidence_by_id: dict[str, Evidence] = {}
        for claim in claims:
            for item in self.source.search(claim):
                evidence_by_id[item.evidence_id] = item
        counts = Counter(result.verification_status.value for result in results)
        status_counts = {status.value: counts.get(status.value, 0) for status in VerificationStatus}
        network_requests = int(getattr(self.source, "network_request_count", 0))
        return VerificationReport(
            metadata={
                "mode": "offline_fixture",
                "fixture_id": fixture_id,
                "fixture_notice": fixture_notice,
                "generated_at": datetime.now(UTC).isoformat(),
                "model_call_count": self.model_call_count,
                "network_request_count": network_requests,
            },
            claim_count=len(claims),
            evidence_count=len(evidence_by_id),
            status_counts=status_counts,
            claims=claims,
            evidence=sorted(evidence_by_id.values(), key=lambda item: item.evidence_id),
            verification_results=results,
            execution_notes=[
                "本次使用离线 fixture，并非真实官方核验结果。",
                "未调用模型，未发送网络请求。",
            ],
        )


def _result(
    claim: Claim,
    status: VerificationStatus,
    explanation: str,
    *,
    matches: list[EvidenceMatch] | None = None,
    evidence: list[Evidence] | None = None,
    supporting: list[Evidence] | None = None,
    contradicting: list[Evidence] | None = None,
    verified_at: datetime,
    version_match: bool | None = None,
    requires_human_review: bool | None = None,
) -> VerificationResult:
    evidence = evidence or []
    supporting = supporting or []
    contradicting = contradicting or []
    official_values = [item.official_value for item in evidence if item.official_value]
    return VerificationResult(
        claim_id=claim.claim_id,
        verification_status=status,
        reported_claim=claim.original_text,
        official_value="；".join(dict.fromkeys(official_values)) or None,
        supporting_evidence_ids=[item.evidence_id for item in supporting],
        contradicting_evidence_ids=[item.evidence_id for item in contradicting],
        evidence_strength=_strength(evidence),
        version_match=version_match,
        explanation=explanation,
        requires_human_review=(
            status not in {VerificationStatus.VERIFIED, VerificationStatus.NOT_APPLICABLE}
            if requires_human_review is None
            else requires_human_review
        ),
        verified_at=verified_at,
        match_details=matches or [],
    )


def _strength(evidence: list[Evidence]) -> EvidenceStrength:
    if not evidence:
        return EvidenceStrength.NONE
    best = max((item.source_priority, item.relevance_score) for item in evidence)
    if best[0] >= 90 and best[1] >= 0.8:
        return EvidenceStrength.STRONG
    if best[0] >= 80 and best[1] >= 0.6:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.WEAK


def _combined_version_match(matches: list[EvidenceMatch]) -> bool | None:
    values = [match.version_match for match in matches if match.version_match is not None]
    if not values:
        return None
    return all(values)
