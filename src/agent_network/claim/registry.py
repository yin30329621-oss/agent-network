"""Deterministic in-memory Claim registry."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from agent_network.claim.claim import Claim


class ClaimRegistry:
    """Store validated Claims with unique IDs and stable insertion order."""

    def __init__(self, claims: Iterable[Claim | dict[str, Any]] = ()) -> None:
        self._claims: dict[str, Claim] = {}
        for claim in claims:
            self.add(claim)

    def add(self, claim: Claim | dict[str, Any]) -> Claim:
        validated = claim if isinstance(claim, Claim) else Claim.model_validate(claim)
        if validated.claim_id in self._claims:
            raise ValueError(f"duplicate claim_id: {validated.claim_id}")
        self._claims[validated.claim_id] = validated
        return validated

    def get(self, claim_id: str) -> Claim:
        try:
            return self._claims[claim_id]
        except KeyError as exc:
            raise KeyError(f"unknown claim_id: {claim_id}") from exc

    def __contains__(self, claim_id: object) -> bool:
        return claim_id in self._claims

    def __len__(self) -> int:
        return len(self._claims)

    def __iter__(self) -> Iterator[Claim]:
        return iter(self._claims.values())

    def list(self) -> list[Claim]:
        return list(self._claims.values())

    def to_dict(self) -> dict[str, Any]:
        return {"claims": [claim.to_dict() for claim in self._claims.values()]}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> "ClaimRegistry":
        payload = json.loads(value)
        if not isinstance(payload, dict) or not isinstance(payload.get("claims"), list):
            raise ValueError("registry JSON must contain a claims list")
        return cls(payload["claims"])
