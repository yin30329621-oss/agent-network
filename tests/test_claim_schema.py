import json

import pytest
from pydantic import ValidationError

from agent_network.claim import Claim, ClaimRegistry, ClaimStatus, ClaimType


def test_claim_validates_and_serializes_deterministically() -> None:
    claim = Claim(
        claim_id="claim-001",
        text="Cluster Agent connects to Rancher Server.",
        product="Rancher Manager",
        component="Cluster Agent",
        claim_type=ClaimType.ARCHITECTURE,
        source_location="section 2, paragraph 3",
    )

    assert claim.normalized_text == "cluster agent connects to rancher server."
    assert claim.status is ClaimStatus.PENDING
    payload = json.loads(claim.to_json())
    assert payload["claim_id"] == "claim-001"
    assert Claim.from_json(claim.to_json()) == claim


def test_claim_rejects_invalid_range_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Claim(claim_id="claim-001", text="statement", line_start=4, line_end=2)
    with pytest.raises(ValidationError):
        Claim(claim_id="claim-001", text="statement", unsupported=True)


def test_registry_rejects_duplicates_and_round_trips() -> None:
    first = Claim(claim_id="claim-001", text="first")
    registry = ClaimRegistry([first])

    with pytest.raises(ValueError, match="duplicate claim_id"):
        registry.add({"claim_id": "claim-001", "text": "duplicate"})

    restored = ClaimRegistry.from_json(registry.to_json())
    assert [claim.claim_id for claim in restored] == ["claim-001"]
    assert restored.get("claim-001").text == "first"


def test_registry_unknown_claim_is_explicit() -> None:
    with pytest.raises(KeyError, match="unknown claim_id"):
        ClaimRegistry().get("missing")
