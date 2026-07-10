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
    location: str = "Unspecified"
    issue: str = "Unspecified issue"
    reason: str = ""
    evidence_needed: str = "Not specified"
    reference: str | None = None
    suggestion: str = "No suggestion provided"
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
    debug_response: str | None = None
    parse_attempts: int = 0
    repair_attempted: bool = False
    repair_status: str | None = None
    parse_error_type: str | None = None
    provider_response_audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "summary": self.summary,
            "findings": [finding.to_dict() for finding in self.findings],
            "status": self.status,
            "model": self.model,
            "provider": self.provider,
            "elapsed_seconds": self.elapsed_seconds,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "debug_response": self.debug_response,
            "parse_attempts": self.parse_attempts,
            "repair_attempted": self.repair_attempted,
            "repair_status": self.repair_status,
            "parse_error_type": self.parse_error_type,
            "provider_response_audit": self.provider_response_audit,
        }

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
    original_severities: dict[str, str]
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
    execution_notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    summary_stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        summary = self.summary_stats or build_summary_stats(
            self.merged_findings, self.agent_reviews
        )
        return {
            "metadata": self.metadata,
            "execution": [review.to_dict() for review in self.agent_reviews],
            "summary": summary,
            "merged_findings": [finding.to_dict() for finding in self.merged_findings],
            "agent_reviews": [review.to_dict() for review in self.agent_reviews],
            "disagreements": self.disagreements,
            "execution_notes": self.execution_notes,
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(slots=True)
class ReviewRequest:
    """Input to a review workflow."""

    markdown: str
    source_name: str = "input.md"


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
