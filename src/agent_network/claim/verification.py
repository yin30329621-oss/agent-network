"""Evidence links and verification result contract models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EvidenceRelation(StrEnum):
    """Relationship between a supplied evidence chunk and a Claim."""

    DIRECT_SUPPORT = "direct_support"
    DIRECT_CONTRADICTION = "direct_contradiction"
    ABSENCE_OF_SUPPORT = "absence_of_support"
    INDIRECT_EVIDENCE = "indirect_evidence"
    UNAVAILABLE = "unavailable"


class VerificationStatus(StrEnum):
    """Finite outcome states for Claim verification."""

    VERIFIED_SUPPORTED = "verified_supported"
    VERIFIED_CONTRADICTED = "verified_contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_MENTIONED = "not_mentioned"
    UNAVAILABLE = "unavailable"
    NEEDS_EXTERNAL_VERIFICATION = "needs_external_verification"
    EXTRACTION_FAILED = "extraction_failed"


class EvidenceLink(BaseModel):
    """Auditable link from one Claim to one retrieved evidence chunk."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    evidence_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    rank: int | None = Field(default=None, ge=1)
    relation: EvidenceRelation
    matched_terms: list[str] = Field(default_factory=list)
    score: float | None = Field(default=None, ge=0.0)
    limitation: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @field_validator(
        "evidence_id", "claim_id", "chunk_id", "document_id", "canonical_url", mode="before"
    )
    @classmethod
    def require_identifier(cls, value: Any) -> str:
        if value is None or not str(value).strip():
            raise ValueError("evidence link identifiers must not be empty")
        return str(value).strip()

    @field_validator("matched_terms", mode="before")
    @classmethod
    def normalize_terms(cls, value: Any) -> list[str]:
        if value is None:
            return []
        terms: list[str] = []
        for term in value:
            normalized = str(term).strip()
            if normalized and normalized not in terms:
                terms.append(normalized)
        return terms

    @field_validator("limitation", mode="before")
    @classmethod
    def normalize_limitation(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("limitations", mode="before")
    @classmethod
    def normalize_limitations(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class VerificationResult(BaseModel):
    """Validated, serializable verification outcome for a Claim."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    claim_id: str = Field(min_length=1)
    verification_status: VerificationStatus
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    evidence_limitations: list[str] = Field(default_factory=list)
    claim_text: str | None = None
    evidence_relation: EvidenceRelation = EvidenceRelation.UNAVAILABLE
    query_text: str | None = None
    applied_filters: dict[str, str | list[str] | None] = Field(default_factory=dict)
    candidate_evidence_count: int = Field(default=0, ge=0)
    returned_document_count: int = Field(default=0, ge=0)
    loaded_document_count: int = Field(default=0, ge=0)
    failed_document_count: int = Field(default=0, ge=0)
    cache_failures: list[dict[str, str]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    verification_mode: str = "candidate_only"
    model_call_count: int = Field(default=0, ge=0)
    network_request_count: int = Field(default=0, ge=0)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    explanation: str = Field(min_length=1)
    requires_human_review: bool = True
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("claim_id", "explanation", mode="before")
    @classmethod
    def require_text(cls, value: Any) -> str:
        if value is None or not str(value).strip():
            raise ValueError("verification text must not be empty")
        return str(value).strip()

    @field_validator("evidence_limitations", mode="before")
    @classmethod
    def normalize_limitations(cls, value: Any) -> list[str]:
        if value is None:
            return []
        limitations: list[str] = []
        for item in value:
            normalized = str(item).strip()
            if normalized and normalized not in limitations:
                limitations.append(normalized)
        return limitations

    @field_validator("limitations", mode="before")
    @classmethod
    def normalize_result_limitations(cls, value: Any) -> list[str]:
        if value is None:
            return []
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    @model_validator(mode="after")
    def validate_evidence_links(self) -> "VerificationResult":
        if any(link.claim_id != self.claim_id for link in self.evidence_links):
            raise ValueError("all evidence links must reference the result claim_id")
        relations = {link.relation for link in self.evidence_links}
        direct_relations = {
            EvidenceRelation.DIRECT_SUPPORT,
            EvidenceRelation.DIRECT_CONTRADICTION,
        }
        if self.verification_status == VerificationStatus.VERIFIED_SUPPORTED and not (
            relations & {EvidenceRelation.DIRECT_SUPPORT}
        ):
            raise ValueError("supported verification requires direct support evidence")
        if self.verification_status == VerificationStatus.VERIFIED_CONTRADICTED and not (
            relations & {EvidenceRelation.DIRECT_CONTRADICTION}
        ):
            raise ValueError("contradicted verification requires direct contradiction evidence")
        if not self.evidence_links and relations & direct_relations:
            raise ValueError("direct evidence relations require an evidence link")
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)

    @classmethod
    def from_json(cls, value: str) -> "VerificationResult":
        return cls.model_validate_json(value)
