"""Schemas for offline claim and evidence verification."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from agent_network.evidence.vocabulary import normalize_official_domain


class ClaimType(StrEnum):
    ARCHITECTURE_BEHAVIOR = "architecture_behavior"
    COMMUNICATION_FLOW = "communication_flow"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    CREDENTIAL_STORAGE = "credential_storage"
    TOKEN_LIFECYCLE = "token_lifecycle"
    KUBERNETES_BEHAVIOR = "kubernetes_behavior"
    RANCHER_FEATURE = "rancher_feature"
    VERSION_CLAIM = "version_claim"
    CVE_EXISTENCE = "cve_existence"
    CVE_AFFECTED_VERSION = "cve_affected_version"
    CVE_FIXED_VERSION = "cve_fixed_version"
    CVSS = "cvss"
    SECURITY_RECOMMENDATION = "security_recommendation"
    TERMINOLOGY = "terminology"


class VerificationPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ClaimStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    VERIFIED = "verified"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    PARTIALLY_VERIFIED = "partially_verified"
    NOT_VERIFIED = "not_verified"
    CONFLICTING_SOURCES = "conflicting_sources"
    VERSION_MISMATCH = "version_mismatch"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"


class EvidenceStrength(StrEnum):
    NONE = "none"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class EvidenceCoverage(StrEnum):
    FULL = "full"
    PARTIAL = "partial"


class DocumentType(StrEnum):
    ARCHITECTURE = "architecture"
    FEATURE_OVERVIEW = "feature_overview"
    REFERENCE = "reference"
    RELEASE_NOTES = "release_notes"
    SECURITY_ADVISORY = "security_advisory"


class DocumentCatalog(BaseModel):
    """Metadata for an official document before fetching or chunking it."""

    document_id: str
    source_name: str
    title: str
    canonical_url: str
    official_domain: str
    document_type: DocumentType = DocumentType.REFERENCE
    product: str
    component: str | None = None
    components: list[str] = Field(default_factory=list)
    product_version: str | None = None
    documentation_version: str | None = None
    language: str = "en"
    published_at: datetime | None = None
    updated_at: datetime | None = None
    fetched_at: datetime | None = None
    content_hash: str | None = None
    tags: list[str] = Field(default_factory=list)
    supported_claim_ids: list[str] = Field(default_factory=list)
    fixture_excerpt: str | None = None
    source_priority: int = Field(default=100, ge=0, le=100)
    fixture_only: bool = False

    @field_validator("official_domain", mode="before")
    @classmethod
    def validate_document_domain(cls, value: Any) -> str:
        return normalize_official_domain(str(value))

    @field_validator("published_at", "updated_at", "fetched_at", mode="after")
    @classmethod
    def require_document_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("document timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_canonical_url(self) -> "DocumentCatalog":
        from urllib.parse import urlparse

        parsed = urlparse(self.canonical_url)
        fixture_url = parsed.hostname == f"{self.source_name}-fixtures.invalid"
        fixture_url = self.fixture_only and fixture_url
        if parsed.scheme != "https" or (
            parsed.hostname != self.official_domain and not fixture_url
        ):
            raise ValueError("canonical_url must use the configured official domain over HTTPS")
        if self.fixture_only and not self.fixture_excerpt:
            raise ValueError("fixture catalogs require fixture_excerpt")
        if self.component is None and self.components:
            self.component = self.components[0]
        return self


class Entity(BaseModel):
    type: str
    value: str


class VersionScope(BaseModel):
    raw: str = "unknown"
    exact: str | None = None
    minimum: str | None = None
    maximum: str | None = None
    include_minimum: bool = True
    include_maximum: bool = False


class Claim(BaseModel):
    claim_id: str
    source_file: str
    section: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    original_text: str = Field(min_length=1)
    normalized_claim: str = Field(min_length=1)
    claim_type: ClaimType
    entities: list[Entity] = Field(default_factory=list)
    product: str
    component: str
    version_scope: VersionScope = Field(default_factory=VersionScope)
    verification_priority: VerificationPriority = VerificationPriority.MEDIUM
    requires_external_evidence: bool = True
    status: ClaimStatus = ClaimStatus.PENDING

    @model_validator(mode="after")
    def validate_line_range(self) -> "Claim":
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


def excerpt_digest(excerpt: str) -> str:
    """Return the stable digest used by evidence snapshots."""

    normalized = "\n".join(line.rstrip() for line in excerpt.strip().splitlines())
    return f"sha256:{sha256(normalized.encode('utf-8')).hexdigest()}"


class Evidence(BaseModel):
    evidence_id: str
    claim_id: str
    source_type: str
    source_title: str
    source_url: str
    official_domain: str
    retrieved_at: datetime
    published_at: datetime | None = None
    updated_at: datetime | None = None
    product_version: str | None = None
    excerpt: str = Field(min_length=1)
    excerpt_hash: str = ""
    relevance_score: float = Field(ge=0.0, le=1.0)
    source_priority: int = Field(ge=0, le=100)
    supports_claim: bool = False
    contradicts_claim: bool = False
    notes: str = ""
    product: str
    component: str
    claim_types: list[ClaimType] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    coverage: EvidenceCoverage = EvidenceCoverage.FULL
    official_value: str | None = None
    fixture_only: bool = False
    response_hash: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("official_domain", mode="before")
    @classmethod
    def validate_official_domain(cls, value: Any) -> str:
        return normalize_official_domain(str(value))

    @field_validator("retrieved_at", "published_at", "updated_at", mode="after")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("evidence timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_excerpt_hash(self) -> "Evidence":
        expected = excerpt_digest(self.excerpt)
        if self.excerpt_hash and self.excerpt_hash != expected:
            raise ValueError("excerpt_hash does not match excerpt")
        self.excerpt_hash = expected
        return self


class EvidenceMatch(BaseModel):
    evidence_id: str
    eligible: bool
    product_match: bool
    component_match: bool
    claim_type_match: bool
    version_match: bool | None
    keyword_overlap: float = Field(ge=0.0, le=1.0)
    effective_relevance: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    claim_id: str
    verification_status: VerificationStatus
    reported_claim: str
    official_value: str | None = None
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength = EvidenceStrength.NONE
    version_match: bool | None = None
    explanation: str
    requires_human_review: bool
    verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    match_details: list[EvidenceMatch] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
