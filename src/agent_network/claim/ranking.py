"""Deterministic Claim ranking metadata for the v0.5 MVP."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_network.claim.claim import Claim, ClaimType
from agent_network.claim.registry import ClaimRegistry


_BASE_SCORES = {
    "low": 10,
    "medium": 30,
    "high": 60,
    "critical": 85,
}
_CLAIM_TYPE_SCORES = {
    ClaimType.AUTHORIZATION: 20,
    ClaimType.SECURITY_CONTROL: 18,
    ClaimType.ARCHITECTURE: 16,
    ClaimType.VERSION_SUPPORT: 12,
    ClaimType.CITATION_OR_PROVENANCE: 12,
    ClaimType.CONFIGURATION: 8,
    ClaimType.BEHAVIOR: 5,
    ClaimType.QUANTITATIVE: 4,
    ClaimType.OTHER: 0,
}
_PRIORITY_BANDS = ((80, "critical"), (60, "high"), (30, "medium"), (0, "low"))
_SECURITY_TYPES = {ClaimType.AUTHORIZATION, ClaimType.SECURITY_CONTROL}
_SECURITY_TERMS = re.compile(
    r"\b(authentication|authorization|credential|credentials|rbac|secret|security|token|tls|encryption|cve|vulnerability|fips|cis)\b"
    r"|认证|授权|凭证|密钥|安全|令牌|加密|漏洞|权限",
    re.IGNORECASE,
)
_ARCHITECTURE_CORE_TERMS = re.compile(
    r"\b(api server|cluster agent|cluster controller|etcd|management plane|rancher server|reverse tunnel|serviceaccount)\b"
    r"|管理平面|控制器|集群代理|数据存储|反向隧道|通信平面",
    re.IGNORECASE,
)
_SECTION_SALIENCE_RULES = (
    ("3.3.1 cluster agent", 20, "section_cluster_agent"),
    ("3.2.3 cluster controller", 18, "section_cluster_controller"),
    ("3.2.2 rancher api server", 18, "section_api_server"),
    ("3.2.4 data store", 18, "section_data_store"),
    ("3.3.2", 18, "section_credentials"),
    ("6.1", 18, "section_vulnerability"),
    ("3.3 cluster communication", 16, "section_communication_plane"),
    ("3.2 management plane", 16, "section_management_plane"),
    ("3.1 rancher", 14, "section_architecture_overview"),
    ("token", 14, "section_token"),
    ("credential", 14, "section_credential"),
    ("authentication", 14, "section_authentication"),
    ("cve", 16, "section_cve"),
    ("漏洞", 16, "section_vulnerability"),
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

    ranking_version: str = "v0.5.1"
    algorithm: str = "deterministic_claim_metadata_v2"
    source_claim_file: str | None = None
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
            source_claim_file=source_claim_file,
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
        security_sensitive = claim.claim_type in _SECURITY_TYPES or bool(
            _SECURITY_TERMS.search(context)
        )
        architecture_core = claim.claim_type is ClaimType.ARCHITECTURE and bool(
            _ARCHITECTURE_CORE_TERMS.search(context)
        )
        section_salience, section_reason = _section_salience(claim)
        requires_external_evidence = claim.requires_external_evidence
        factors = {
            "base_priority": _BASE_SCORES[claim.priority],
            "claim_type": _CLAIM_TYPE_SCORES[claim.claim_type],
            "security_sensitive": 12 if security_sensitive else 0,
            "architecture_core": 12 if architecture_core else 0,
            "section_salience": section_salience,
            "requires_external_evidence": 5 if requires_external_evidence else 0,
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
            "priority_score": min(100, uncapped_score),
            "priority_band": _band_for(min(100, uncapped_score)),
            "original_priority": claim.priority,
            "reason_codes": reason_codes,
            "factors": {**factors, "uncapped_score": uncapped_score},
        }


def _section_salience(claim: Claim) -> tuple[int, str | None]:
    context = " / ".join(
        [*claim.heading_path, claim.section or "", claim.source_location or ""]
    ).lower()
    for pattern, score, reason in _SECTION_SALIENCE_RULES:
        if pattern in context:
            return score, reason
    return 0, None


def _band_for(score: int) -> str:
    for threshold, band in _PRIORITY_BANDS:
        if score >= threshold:
            return band
    return "low"
