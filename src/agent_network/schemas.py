"""Shared review schemas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class Severity(StrEnum):
    """Finding severity levels."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingStatus(StrEnum):
    """Finding lifecycle/status markers."""

    VALID = "valid"
    DISPUTED = "disputed"
    UNIQUE = "unique"
    DEGRADED = "degraded"
    PARSE_FAILED = "parse_failed"


class EvidenceRelation(StrEnum):
    """How supplied official evidence relates to a Fact Agent claim."""

    DIRECT_SUPPORT = "direct_support"
    DIRECT_CONTRADICTION = "direct_contradiction"
    ABSENCE_OF_SUPPORT = "absence_of_support"
    INDIRECT_EVIDENCE = "indirect_evidence"
    UNAVAILABLE = "unavailable"


SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class FindingModel(BaseModel):
    """Validated model response finding."""

    id: str = Field(default_factory=lambda: f"finding-{uuid4().hex[:12]}")
    agent: str = ""
    provider: str | None = None
    model: str | None = None
    severity: Severity = Severity.INFO
    location: str = ""
    issue: str
    reason: str
    evidence_needed: str = ""
    reference: str | None = None
    suggestion: str = ""
    confidence: float = 0.5
    status: FindingStatus = FindingStatus.VALID

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: Any) -> Severity:
        return _coerce_severity(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.5
        return max(0.0, min(1.0, confidence))

    @field_validator("location", "evidence_needed", "suggestion", mode="before")
    @classmethod
    def normalize_nullable_display_text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("reference", mode="before")
    @classmethod
    def normalize_nullable_reference(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("issue", "reason", mode="before")
    @classmethod
    def require_core_text(cls, value: Any) -> str:
        if value is None or not str(value).strip():
            raise ValueError("core finding text must not be null or empty")
        return str(value).strip()


@dataclass(slots=True)
class ReviewFinding:
    """A single actionable review finding."""

    id: str = field(default_factory=lambda: f"finding-{uuid4().hex[:12]}")
    agent: str = ""
    provider: str | None = None
    model: str | None = None
    severity: Severity = Severity.INFO
    location: str = "Unspecified"
    issue: str = "Unspecified issue"
    reason: str = ""
    evidence_needed: str = "Not specified"
    reference: str | None = None
    suggestion: str = "No suggestion provided"
    confidence: float = 0.5
    status: FindingStatus = FindingStatus.VALID

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(
        cls,
        agent: str,
        data: dict[str, Any],
        provider: str | None = None,
        model: str | None = None,
    ) -> "ReviewFinding":
        payload = dict(data)
        payload["agent"] = agent
        payload["provider"] = payload.get("provider") or provider
        payload["model"] = payload.get("model") or model
        finding = FindingModel.model_validate(payload)
        return cls(
            id=finding.id,
            agent=agent,
            provider=finding.provider,
            model=finding.model,
            severity=finding.severity,
            location=finding.location,
            issue=finding.issue,
            reason=finding.reason,
            evidence_needed=finding.evidence_needed,
            reference=finding.reference,
            suggestion=finding.suggestion,
            confidence=finding.confidence,
            status=finding.status,
        )


@dataclass(slots=True)
class AgentReview:
    """Review result produced by one agent."""

    agent: str
    summary: str
    findings: list[ReviewFinding] = field(default_factory=list)
    status: str = "completed"
    model: str | None = None
    provider: str | None = None
    elapsed_seconds: float | None = None
    error_type: str | None = None
    error_message: str | None = None
    skip_reason: str | None = None
    debug_response: str | None = None
    parse_attempts: int = 0
    repair_attempted: bool = False
    repair_status: str | None = None
    parse_error_type: str | None = None
    failure_stage: str | None = None
    raw_finding_count: int = 0
    valid_finding_count: int = 0
    rejected_finding_count: int = 0
    rejected_findings: list[dict[str, Any]] = field(default_factory=list)
    provider_response_audit: dict[str, Any] = field(default_factory=dict)
    model_call_count: int = 0
    request_attempt_count: int = 0
    retry_count: int = 0
    timeout_count: int = 0
    request_started_at: str | None = None
    request_completed_at: str | None = None
    last_error_type: str | None = None
    last_error_message: str | None = None
    configured_timeout_seconds: float | None = None
    configured_max_tokens: int | None = None
    effective_elapsed_seconds: float | None = None
    evidence_status: str | None = None
    evidence_relation: EvidenceRelation | None = None
    evidence_used: bool = False
    evidence_chunk_ids: list[str] = field(default_factory=list)
    evidence_document_ids: list[str] = field(default_factory=list)
    evidence_urls: list[str] = field(default_factory=list)
    evidence_limitations: list[str] = field(default_factory=list)
    retrieval_status: str | None = None
    evidence_warnings: list[str] = field(default_factory=list)
    evidence_network_request_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = {
            "agent": self.agent,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
            "status": self.status,
            "model": self.model,
            "provider": self.provider,
            "elapsed_seconds": self.elapsed_seconds,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "skip_reason": self.skip_reason,
            "debug_response": self.debug_response,
            "parse_attempts": self.parse_attempts,
            "repair_attempted": self.repair_attempted,
            "repair_status": self.repair_status,
            "parse_error_type": self.parse_error_type,
            "failure_stage": self.failure_stage,
            "raw_finding_count": self.raw_finding_count,
            "valid_finding_count": self.valid_finding_count,
            "rejected_finding_count": self.rejected_finding_count,
            "rejected_findings": self.rejected_findings,
            "provider_response_audit": self.provider_response_audit,
            "model_call_count": self.model_call_count,
            "request_attempt_count": self.request_attempt_count,
            "retry_count": self.retry_count,
            "timeout_count": self.timeout_count,
            "request_started_at": self.request_started_at,
            "request_completed_at": self.request_completed_at,
            "last_error_type": self.last_error_type,
            "last_error_message": self.last_error_message,
            "configured_timeout_seconds": self.configured_timeout_seconds,
            "configured_max_tokens": self.configured_max_tokens,
            "effective_elapsed_seconds": self.effective_elapsed_seconds,
        }
        if self.agent == "fact" and self.retrieval_status is not None:
            data["evidence_status"] = self.evidence_status
            data["evidence_relation"] = (
                self.evidence_relation.value if self.evidence_relation is not None else None
            )
            data["evidence_used"] = self.evidence_used
            data["evidence_chunk_ids"] = self.evidence_chunk_ids
            data["evidence_document_ids"] = self.evidence_document_ids
            data["evidence_urls"] = self.evidence_urls
            data["evidence_limitations"] = self.evidence_limitations
            data["retrieval_status"] = self.retrieval_status
            data["evidence_warnings"] = self.evidence_warnings
            data["evidence_network_request_count"] = self.evidence_network_request_count
        return data

    def apply_request_audit(self, audit: dict[str, Any] | None = None) -> None:
        data = audit or self.provider_response_audit
        self.provider_response_audit = dict(data or {})
        self.model_call_count = int(data.get("model_call_count") or 0)
        self.request_attempt_count = int(data.get("request_attempt_count") or 0)
        self.retry_count = int(data.get("retry_count") or 0)
        self.timeout_count = int(data.get("timeout_count") or 0)
        self.request_started_at = data.get("request_started_at")
        self.request_completed_at = data.get("request_completed_at")
        self.last_error_type = data.get("last_error_type")
        self.last_error_message = data.get("last_error_message")
        self.configured_timeout_seconds = data.get("configured_timeout_seconds")
        self.configured_max_tokens = data.get("configured_max_tokens")
        self.effective_elapsed_seconds = data.get("effective_elapsed_seconds")

    @classmethod
    def from_dict(
        cls,
        agent: str,
        data: dict[str, Any],
        provider: str | None = None,
        model: str | None = None,
    ) -> "AgentReview":
        findings = [
            ReviewFinding.from_dict(agent=agent, data=item, provider=provider, model=model)
            for item in data.get("findings", [])
            if isinstance(item, dict)
        ]
        return cls(
            agent=agent,
            summary=str(data.get("summary") or ""),
            findings=findings,
            provider=provider,
            model=model,
        )


@dataclass(slots=True)
class MergedFinding:
    """A deduplicated/judged finding for final output."""

    id: str
    title: str
    location: str
    supporting_agents: list[str]
    dissenting_agents: list[str]
    source_finding_ids: list[str]
    original_severities: list[dict[str, str]]
    merged_severity: Severity
    decision_reason: str
    reason: str
    combined_evidence_needed: str
    combined_references: list[str]
    final_suggestion: str
    confidence: float
    needs_human_review: bool = False
    status: FindingStatus = FindingStatus.VALID
    potential_duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["merged_severity"] = self.merged_severity.value
        data["status"] = self.status.value
        return data


@dataclass(slots=True)
class ReviewResult:
    """Final merged review result."""

    summary: str
    agent_reviews: list[AgentReview] = field(default_factory=list)
    findings: list[ReviewFinding] = field(default_factory=list)
    merged_findings: list[MergedFinding] = field(default_factory=list)
    disagreements: list[dict[str, Any]] = field(default_factory=list)
    potential_duplicates: list[dict[str, Any]] = field(default_factory=list)
    execution_notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    summary_stats: dict[str, Any] = field(default_factory=dict)
    overall_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        summary = self.summary_stats or build_summary_stats(
            self.merged_findings, self.agent_reviews
        )
        overall_status = self.overall_status or determine_overall_status(self)
        if str(self.metadata.get("language") or "").lower().startswith("zh"):
            summary = dict(summary)
            summary["overall_assessment"] = _overall_assessment_zh(
                overall_status, len(self.merged_findings)
            )
        return {
            "metadata": self.metadata,
            "overall_status": overall_status,
            "execution": [review.to_dict() for review in self.agent_reviews],
            "summary": summary,
            "merged_findings": [finding.to_dict() for finding in self.merged_findings],
            "agent_reviews": [review.to_dict() for review in self.agent_reviews],
            "disagreements": self.disagreements,
            "potential_duplicates": self.potential_duplicates,
            "execution_notes": self.execution_notes,
            "findings": [finding.to_dict() for finding in self.findings],
        }


def determine_overall_status(result: ReviewResult) -> str:
    """Return the run-level status from structured execution and finding data."""

    merge_review = next(
        (review for review in result.agent_reviews if review.agent == "merge"), None
    )
    usable_findings = [
        finding
        for finding in result.merged_findings
        if finding.status not in {FindingStatus.DEGRADED, FindingStatus.PARSE_FAILED}
    ]
    if merge_review is None or merge_review.status == "failed" or not usable_findings:
        return "failed"
    professional_reviews = [
        review for review in result.agent_reviews if review.agent in {"fact", "security", "logic"}
    ]
    if merge_review.status in {"degraded", "truncated"} or any(
        review.status != "completed" for review in professional_reviews
    ):
        return "degraded"
    return "success"


@dataclass(slots=True)
class ReviewRequest:
    """Input to a review workflow."""

    markdown: str
    source_name: str = "input.md"
    language: str = "en"
    fact_evidence_query: dict[str, Any] | None = None
    fact_evidence_context: dict[str, Any] | None = None


def build_summary_stats(
    merged_findings: list[MergedFinding], agent_reviews: list[AgentReview]
) -> dict[str, Any]:
    counts = {severity.value: 0 for severity in Severity}
    for finding in merged_findings:
        counts[finding.merged_severity.value] += 1
    degraded_agents = [
        review.agent for review in agent_reviews if review.status not in {"completed", "valid"}
    ]
    return {
        "overall_assessment": _overall_assessment(counts),
        "critical": counts["critical"],
        "high": counts["high"],
        "medium": counts["medium"],
        "low": counts["low"],
        "info": counts["info"],
        "needs_human_review": bool(
            counts["critical"]
            or counts["high"]
            or degraded_agents
            or any(item.needs_human_review for item in merged_findings)
        ),
    }


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _coerce_severity(value: Any) -> Severity:
    try:
        return Severity(str(value).lower())
    except ValueError:
        return Severity.INFO


def _overall_assessment(counts: dict[str, int]) -> str:
    if counts.get("critical"):
        return "Critical issues require immediate review before publication."
    if counts.get("high"):
        return "High-risk issues should be addressed before publication."
    if counts.get("medium"):
        return "Moderate issues need evidence, clarification, or safer recommendations."
    if counts.get("low"):
        return "Low-risk improvements were identified."
    return "No material issues were identified."


def _overall_assessment_zh(overall_status: str, finding_count: int) -> str:
    if overall_status == "success" and finding_count > 0:
        return f"本次审查已完成，共发现 {finding_count} 项需要关注的问题。"
    if overall_status == "success":
        return "本次审查已成功完成，未发现符合当前审查规则的实质性问题。"
    if overall_status == "degraded":
        return (
            "本次审查为降级结果，部分 Agent 未产生可用结果，当前结论不完整，"
            "不建议直接作为最终安全判断。"
        )
    return "本次审查失败，专业 Agent 未产生足够的可用结果，无法评估报告中的安全风险。"
