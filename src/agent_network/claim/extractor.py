"""Deterministic Claim extraction from Markdown or plain text."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_network.claim.claim import Claim, ClaimType
from agent_network.claim.normalization import (
    claim_id_for,
    clean_claim_text,
    normalize_claim_text,
    slugify_heading,
)
from agent_network.claim.registry import ClaimRegistry
from agent_network.claim.segmentation import DocumentSegment, segment_markdown


class ClaimExtractionConfig(BaseModel):
    minimum_claim_characters: int = Field(default=20, ge=1)
    maximum_claim_characters: int = Field(default=1000, ge=1)
    include_headings: bool = False
    include_list_items: bool = True
    include_table_rows: bool = True
    include_blockquotes: bool = False
    maximum_input_characters: int = Field(default=1_000_000, ge=1)

    @model_validator(mode="after")
    def validate_lengths(self) -> "ClaimExtractionConfig":
        if self.maximum_claim_characters < self.minimum_claim_characters:
            raise ValueError("maximum_claim_characters must be >= minimum_claim_characters")
        return self


class ClaimExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_text: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_type: str = "markdown"
    product: str | None = None
    default_component: str | None = None
    minimum_claim_characters: int = Field(default=20, ge=1)
    maximum_claim_characters: int = Field(default=1000, ge=1)
    include_headings: bool = False
    include_list_items: bool = True
    include_table_rows: bool = True
    include_blockquotes: bool = False
    maximum_input_characters: int = Field(default=1_000_000, ge=1)

    @field_validator("source_name", mode="before")
    @classmethod
    def normalize_source_name(cls, value: Any) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("source_name must not be empty")
        return normalized

    @field_validator("source_type", mode="before")
    @classmethod
    def validate_source_type(cls, value: Any) -> str:
        normalized = str(value or "markdown").strip().lower()
        if normalized not in {"markdown", "plain_text", "text"}:
            raise ValueError("source_type must be markdown, plain_text, or text")
        return normalized

    @model_validator(mode="after")
    def validate_document(self) -> "ClaimExtractionRequest":
        if not self.document_text.strip():
            raise ValueError("document_text must not be empty")
        if len(self.document_text) > self.maximum_input_characters:
            raise ValueError("document_text exceeds maximum_input_characters")
        ClaimExtractionConfig(
            minimum_claim_characters=self.minimum_claim_characters,
            maximum_claim_characters=self.maximum_claim_characters,
        )
        return self

    def config(self) -> ClaimExtractionConfig:
        return ClaimExtractionConfig(
            **self.model_dump(
                exclude={
                    "document_text",
                    "source_name",
                    "source_type",
                    "product",
                    "default_component",
                }
            )
        )


class ClaimExtractionFailure(BaseModel):
    code: str
    message: str
    source_location: str | None = None


class ClaimExtractionResult(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    failures: list[ClaimExtractionFailure] = Field(default_factory=list)
    candidate_count: int = 0
    duplicate_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class DeterministicClaimExtractor:
    """Extract claims using only local Markdown structure and transparent rules."""

    def extract(self, request: ClaimExtractionRequest) -> ClaimExtractionResult:
        config = request.config()
        segments = segment_markdown(request.document_text)
        registry = ClaimRegistry()
        failures: list[ClaimExtractionFailure] = []
        candidates = 0
        duplicates = 0

        for segment in segments:
            if not self._enabled(segment, config):
                continue
            candidates += 1
            text = _clean_candidate(segment.text)
            if not _is_candidate(text, segment, config):
                continue
            if not config.minimum_claim_characters <= len(text) <= config.maximum_claim_characters:
                failures.append(
                    ClaimExtractionFailure(
                        code="claim_length_out_of_range",
                        message="candidate length is outside configured bounds",
                        source_location=_source_location(request.source_name, segment),
                    )
                )
                continue
            normalized = normalize_claim_text(text)
            claim_id = claim_id_for(request.source_name, list(segment.heading_path), normalized)
            if any(existing.normalized_text == normalized for existing in registry):
                duplicates += 1
                continue
            try:
                registry.add(
                    Claim(
                        claim_id=claim_id,
                        text=text,
                        normalized_text=normalized,
                        source_excerpt=text,
                        source_file=request.source_name,
                        source_location=_source_location(request.source_name, segment),
                        section=segment.heading_path[-1] if segment.heading_path else None,
                        heading_path=list(segment.heading_path),
                        line_start=segment.start_line,
                        line_end=segment.end_line,
                        product=request.product,
                        component=request.default_component,
                        claim_type=_classify(normalized),
                        extraction_method="deterministic",
                        extraction_confidence=0.9,
                    )
                )
            except ValueError as exc:
                failures.append(
                    ClaimExtractionFailure(
                        code="claim_validation_error",
                        message=str(exc),
                        source_location=_source_location(request.source_name, segment),
                    )
                )

        return ClaimExtractionResult(
            claims=registry.list(),
            failures=failures,
            candidate_count=candidates,
            duplicate_count=duplicates,
        )

    def _enabled(self, segment: DocumentSegment, config: ClaimExtractionConfig) -> bool:
        return {
            "heading": config.include_headings,
            "list_item": config.include_list_items,
            "table_row": config.include_table_rows,
            "quote": config.include_blockquotes,
            "paragraph": True,
        }.get(segment.kind, False)


def _clean_candidate(value: str) -> str:
    return clean_claim_text(value).strip()


def _is_candidate(text: str, segment: DocumentSegment, config: ClaimExtractionConfig) -> bool:
    comparable = normalize_claim_text(text)
    if (
        not comparable
        or comparable.startswith("!")
        or _is_url(comparable)
        or _is_command(comparable)
    ):
        return False
    if segment.kind == "heading" and not _has_statement_signal(comparable):
        return False
    if segment.kind == "quote":
        return False
    if re.fullmatch(r"[a-zA-Z_][\w.-]*\s*[:=].*", text) and " " not in text.split(":", 1)[0]:
        return False
    if comparable in {"如下所示", "主要功能如下", "更多信息请参见"}:
        return False
    if len(text) < config.minimum_claim_characters or len(text) > config.maximum_claim_characters:
        return False
    return _has_statement_signal(comparable) or bool(re.search(r"[。！？.!?]$", comparable))


def _has_statement_signal(text: str) -> bool:
    return bool(
        re.search(
            r"\b(is|are|was|were|has|have|uses|use|supports|connects?|communicates?|contains|requires|provides|prevents|allows|runs|stores|manages|configures?)\b",
            text,
        )
        or re.search(
            r"(是|为|使用|通过|连接|通信|包含|需要|支持|允许|运行|存储|管理|配置|保护|部署)", text
        )
    )


def _is_url(text: str) -> bool:
    return bool(re.fullmatch(r"(?:https?://|www\.)\S+", text, re.IGNORECASE))


def _is_command(text: str) -> bool:
    return bool(re.match(r"^(?:kubectl|curl|helm|docker|git)\s+", text, re.IGNORECASE))


def _classify(text: str) -> ClaimType:
    if re.search(
        r"\b(rbac|rolebinding|clusterrole|serviceaccount|authorization|permission)\b", text
    ):
        return ClaimType.AUTHORIZATION
    if re.search(r"\b(tls|https|encryption|authentication|token|secret|credential)\b", text):
        return ClaimType.SECURITY_CONTROL
    if re.search(r"\b(cve[- ]?\d{4}-\d+|v?\d+(?:\.\d+)+|version|patch|release)\b", text):
        return ClaimType.VERSION_SUPPORT
    if re.search(r"\b(connect|communicat|tunnel|network|server|agent|downstream)\w*\b", text):
        return ClaimType.ARCHITECTURE
    if re.search(r"\b(configur|setting|default|enable|disable|option)\w*\b", text):
        return ClaimType.CONFIGURATION
    if re.search(r"\b(metric|percent|seconds?|milliseconds?|maximum|minimum|limit|count)\b", text):
        return ClaimType.QUANTITATIVE
    if re.search(r"\b(cite|source|reference|according)\w*\b", text):
        return ClaimType.CITATION_OR_PROVENANCE
    return ClaimType.BEHAVIOR if _has_statement_signal(text) else ClaimType.OTHER


def _source_location(source_name: str, segment: DocumentSegment) -> str:
    heading = ".".join(slugify_heading(item) for item in segment.heading_path) or "root"
    return f"{source_name}#{heading}:{segment.kind}-{segment.order}:L{segment.start_line}-L{segment.end_line}"
