"""Validated, deterministic configuration for Claim ranking."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_network.claim.claim import ClaimType


class RankingScoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_priority: dict[str, int]
    claim_type_weights: dict[str, int]
    security_sensitive_weight: int = Field(ge=0)
    architecture_core_weight: int = Field(ge=0)
    external_evidence_weight: int = Field(ge=0)
    max_score: int = Field(ge=1, le=1000)
    priority_bands: dict[str, int]

    @field_validator("base_priority", "claim_type_weights", "priority_bands")
    @classmethod
    def validate_integer_mapping(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not isinstance(key, str) or not key.strip() for key in value):
            raise ValueError("ranking mapping keys must be non-empty strings")
        if any(not isinstance(item, int) or item < 0 for item in value.values()):
            raise ValueError("ranking mapping values must be non-negative integers")
        return value

    @model_validator(mode="after")
    def validate_score_vocabularies(self) -> "RankingScoreConfig":
        required_priorities = {"low", "medium", "high", "critical"}
        if set(self.base_priority) != required_priorities:
            raise ValueError("base_priority must define low, medium, high, and critical")
        unknown_types = set(self.claim_type_weights) - {item.value for item in ClaimType}
        if unknown_types:
            raise ValueError(f"unknown Claim types in ranking config: {sorted(unknown_types)}")
        if not {"low", "medium", "high", "critical"}.issubset(self.priority_bands):
            raise ValueError("priority_bands must define low, medium, high, and critical")
        return self


class RankingSignalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_types: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)

    @field_validator("claim_types")
    @classmethod
    def validate_claim_types(cls, value: list[str]) -> list[str]:
        unknown = set(value) - {item.value for item in ClaimType}
        if unknown:
            raise ValueError(f"unknown Claim types in ranking signal: {sorted(unknown)}")
        return list(dict.fromkeys(value))

    @field_validator("terms")
    @classmethod
    def validate_terms(cls, value: list[str]) -> list[str]:
        terms = [str(item).strip() for item in value if str(item).strip()]
        if any("\n" in item or "\r" in item for item in terms):
            raise ValueError("ranking signal terms must be single-line strings")
        return list(dict.fromkeys(terms))


class SectionSalienceRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(min_length=1)
    patterns: list[str] = Field(min_length=1)
    weight: int = Field(ge=0)
    reason_code: str = Field(min_length=1)

    @field_validator("patterns")
    @classmethod
    def validate_patterns(cls, value: list[str]) -> list[str]:
        patterns = [str(item).strip().lower() for item in value if str(item).strip()]
        if not patterns:
            raise ValueError("section salience patterns must not be empty")
        return list(dict.fromkeys(patterns))


class RankingConfig(BaseModel):
    """Profile-level ranking policy; separate from the Claim schema."""

    model_config = ConfigDict(extra="forbid")

    config_id: str = Field(min_length=1)
    config_version: str = Field(min_length=1)
    ranking_version: str = Field(min_length=1)
    algorithm: str = Field(min_length=1)
    score: RankingScoreConfig
    security_signal: RankingSignalConfig
    architecture_signal: RankingSignalConfig
    section_salience: list[SectionSalienceRule] = Field(default_factory=list)
    tie_break: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profile(self) -> "RankingConfig":
        rule_ids = [rule.rule_id for rule in self.section_salience]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("section salience rule_id values must be unique")
        if self.tie_break != ["priority_score_desc", "claim_id_asc"] and self.tie_break != [
            "priority_score_desc",
            "section_salience_desc",
            "claim_id_asc",
        ]:
            raise ValueError("unsupported ranking tie_break policy")
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    def sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_json().encode('utf-8')).hexdigest()}"


def load_ranking_config(path: str | Path) -> RankingConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError("ranking config must contain a YAML mapping")
    return RankingConfig.model_validate(payload)


def default_ranking_config() -> RankingConfig:
    return load_ranking_config(Path("configs/ranking/default.yaml"))


def source_sha256(path: str | Path) -> str:
    return f"sha256:{hashlib.sha256(Path(path).read_bytes()).hexdigest()}"


def matches_term(context: str, term: str) -> bool:
    """Match ASCII vocabulary by word boundary and non-ASCII vocabulary literally."""

    normalized_context = context.lower()
    normalized_term = term.lower()
    if normalized_term.isascii() and re.fullmatch(r"[\w -]+", normalized_term):
        return bool(re.search(rf"\b{re.escape(normalized_term)}\b", normalized_context))
    return normalized_term in normalized_context
