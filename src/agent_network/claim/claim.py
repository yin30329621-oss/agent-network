"""Stable Claim contract for v0.4 verification."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClaimType(StrEnum):
    """Finite categories used to route and audit claims."""

    ARCHITECTURE = "architecture"
    CONFIGURATION = "configuration"
    AUTHORIZATION = "authorization"
    SECURITY_CONTROL = "security_control"
    VERSION_SUPPORT = "version_support"
    BEHAVIOR = "behavior"
    QUANTITATIVE = "quantitative"
    CITATION_OR_PROVENANCE = "citation_or_provenance"
    OTHER = "other"


class ClaimStatus(StrEnum):
    """Lifecycle state of a Claim before verification."""

    PENDING = "pending"
    READY = "ready"
    VERIFIED = "verified"
    EXTRACTION_FAILED = "extraction_failed"


class Claim(BaseModel):
    """A report statement that can be verified independently."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    normalized_text: str | None = None
    source_excerpt: str | None = None
    source_file: str | None = None
    source_location: str | None = None
    section: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    product: str | None = None
    component: str | None = None
    claim_type: ClaimType = ClaimType.OTHER
    priority: str = "medium"
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    extraction_method: str = "deterministic"
    requires_external_evidence: bool = True
    status: ClaimStatus = ClaimStatus.PENDING

    @field_validator("claim_id", "text", mode="before")
    @classmethod
    def require_text(cls, value: Any) -> str:
        if value is None:
            raise ValueError("value must not be null")
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator(
        "normalized_text",
        "source_excerpt",
        "source_file",
        "source_location",
        "section",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("heading_path", mode="before")
    @classmethod
    def normalize_heading_path(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value: Any) -> str:
        normalized = str(value or "medium").strip().lower()
        if normalized not in {"low", "medium", "high", "critical"}:
            raise ValueError("priority must be low, medium, high, or critical")
        return normalized

    @model_validator(mode="after")
    def validate_source_range(self) -> "Claim":
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        if self.normalized_text is None:
            self.normalized_text = " ".join(self.text.lower().split())
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)

    @classmethod
    def from_json(cls, value: str) -> "Claim":
        return cls.model_validate_json(value)
