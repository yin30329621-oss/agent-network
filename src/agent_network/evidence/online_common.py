"""Shared helpers for official online evidence sources."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from agent_network.evidence.schemas import Claim


def claim_cve_id(claim: Claim) -> str | None:
    values = [claim.original_text, claim.normalized_claim]
    values.extend(entity.value for entity in claim.entities if entity.type.lower() == "cve")
    for value in values:
        match = re.search(r"\bCVE-\d{4}-\d{4,}\b", value, re.IGNORECASE)
        if match:
            return match.group(0).upper()
    return None


def api_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def now_utc() -> datetime:
    return datetime.now(UTC)
