"""Deterministic Claim ranking metadata for the v0.5 MVP."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_network.claim.claim import Claim
from agent_network.claim.registry import ClaimRegistry
from agent_network.claim.ranking_config import (
    RankingConfig,
    RankingScoreConfig,
    default_ranking_config,
    matches_term,
    source_sha256,
)


class ClaimRankingItem(BaseModel):
    """One auditable, sidecar-only ranking record for a Claim."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    claim_id: str = Field(min_length=1)
    priority_score: int = Field(ge=0, le=100)
    priority_band: str
    original_priority: str
    reason_codes: list[str] = Field(default_factory=list)
    factors: dict[str, int] = Field(default_factory=dict)

    @field_validator("priority_band", "original_priority", mode="before")
    @classmethod
    def require_label(cls, value: Any) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("ranking labels must not be empty")
        return normalized


class ClaimRankingResult(BaseModel):
    """Complete ranking sidecar; it does not alter the Claim contract."""

    model_config = ConfigDict(extra="forbid")

    artifact_schema_version: str = "2"
    ranking_version: str
    algorithm: str
    config_id: str
    config_version: str
    config_sha256: str
    source_claim_file: str | None = None
    source_claim_sha256: str | None = None
    input_identifier: str | None = None
    total_claim_count: int = Field(ge=0)
    selection_limit: int | None = Field(default=None, ge=1)
    ranked_claims: list[ClaimRankingItem] = Field(default_factory=list)
    selected_claim_ids: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def select_claims(self, registry: ClaimRegistry) -> list[Claim]:
        """Return ranked Claim objects without mutating the supplied registry."""

        claims = {claim.claim_id: claim for claim in registry}
        return [claims[claim_id] for claim_id in self.selected_claim_ids if claim_id in claims]


class ClaimRanker:
    """Rank Claims using only existing deterministic Claim metadata."""

    def __init__(self, config: RankingConfig | None = None) -> None:
        self.config = config or default_ranking_config()

    def rank(
        self,
        claims: Iterable[Claim] | ClaimRegistry,
        *,
        top_k: int | None = None,
        source_claim_file: str | None = None,
        input_identifier: str | None = None,
    ) -> ClaimRankingResult:
        claim_list = list(claims)
        if top_k is not None and top_k <= 0:
            raise ValueError("top_k must be positive when provided")

        scored = [self._score(claim) for claim in claim_list]
        scored.sort(key=lambda item: (-item["priority_score"], item["claim_id"]))
        ranked = [
            ClaimRankingItem(rank=index, **item)
            for index, item in enumerate(scored, start=1)
        ]
        selected = ranked if top_k is None else ranked[:top_k]
        return ClaimRankingResult(
            ranking_version=self.config.ranking_version,
            algorithm=self.config.algorithm,
            config_id=self.config.config_id,
            config_version=self.config.config_version,
            config_sha256=self.config.sha256(),
            source_claim_file=source_claim_file,
            source_claim_sha256=(
                source_sha256(source_claim_file) if source_claim_file and Path(source_claim_file).exists() else None
            ),
            input_identifier=input_identifier,
            total_claim_count=len(claim_list),
            selection_limit=top_k,
            ranked_claims=ranked,
            selected_claim_ids=[item.claim_id for item in selected],
        )

    def _score(self, claim: Claim) -> dict[str, Any]:
        normalized = claim.normalized_text or claim.text
        context = " ".join(
            [normalized, claim.component or "", " / ".join(claim.heading_path)]
        )
        security_signal = self.config.security_signal
        architecture_signal = self.config.architecture_signal
        security_sensitive = (
            claim.claim_type.value in security_signal.claim_types
            or any(matches_term(context, term) for term in security_signal.terms)
        )
        architecture_core = (
            claim.claim_type.value in architecture_signal.claim_types
            and any(matches_term(context, term) for term in architecture_signal.terms)
        )
        section_salience, section_reason = _section_salience(claim, self.config)
        requires_external_evidence = claim.requires_external_evidence
        score_config = self.config.score
        factors = {
            "base_priority": score_config.base_priority[claim.priority],
            "claim_type": score_config.claim_type_weights.get(claim.claim_type.value, 0),
            "security_sensitive": score_config.security_sensitive_weight if security_sensitive else 0,
            "architecture_core": score_config.architecture_core_weight if architecture_core else 0,
            "section_salience": section_salience,
            "requires_external_evidence": score_config.external_evidence_weight
            if requires_external_evidence
            else 0,
        }
        uncapped_score = sum(factors.values())
        reason_codes = [f"base_priority_{claim.priority}"]
        if factors["claim_type"]:
            reason_codes.append(f"claim_type_{claim.claim_type.value}")
        if security_sensitive:
            reason_codes.append("security_sensitive")
        if architecture_core:
            reason_codes.append("architecture_core")
        if section_reason:
            reason_codes.append(section_reason)
        if requires_external_evidence:
            reason_codes.append("requires_external_evidence")
        return {
            "claim_id": claim.claim_id,
            "priority_score": min(score_config.max_score, uncapped_score),
            "priority_band": _band_for(min(score_config.max_score, uncapped_score), score_config),
            "original_priority": claim.priority,
            "reason_codes": reason_codes,
            "factors": {**factors, "uncapped_score": uncapped_score},
        }


def _section_salience(claim: Claim, config: RankingConfig) -> tuple[int, str | None]:
    context = " / ".join(
        [*claim.heading_path, claim.section or "", claim.source_location or ""]
    ).lower()
    for rule in config.section_salience:
        if any(pattern in context for pattern in rule.patterns):
            return rule.weight, rule.reason_code
    return 0, None


def _band_for(score: int, config: RankingScoreConfig) -> str:
    bands = sorted(config.priority_bands.items(), key=lambda item: item[1], reverse=True)
    for band, threshold in bands:
        if score >= threshold:
            return band
    return "low"
