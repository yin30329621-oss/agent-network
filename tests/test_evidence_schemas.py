from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_network.evidence.schemas import Claim, Evidence, excerpt_digest


def claim_payload() -> dict:
    return {
        "claim_id": "claim-test",
        "source_file": "fixture.md",
        "section": "Test",
        "line_start": 2,
        "line_end": 3,
        "original_text": "Cluster Agent connects to Rancher Server.",
        "normalized_claim": "Cluster Agent connects to Rancher Server",
        "claim_type": "communication_flow",
        "entities": [{"type": "component", "value": "Cluster Agent"}],
        "product": "Rancher Manager",
        "component": "Cluster Agent",
        "version_scope": {"raw": "2.10", "exact": "2.10"},
        "verification_priority": "high",
        "requires_external_evidence": True,
        "status": "pending",
    }


def evidence_payload() -> dict:
    return {
        "evidence_id": "evidence-test",
        "claim_id": "claim-test",
        "source_type": "fixture",
        "source_title": "FIXTURE: Test",
        "source_url": "https://fixture.invalid/test",
        "official_domain": "ranchermanager.docs.rancher.com",
        "retrieved_at": datetime(2026, 7, 12, tzinfo=UTC),
        "product_version": "2.10",
        "excerpt": "FIXTURE ONLY: Cluster Agent connects to Rancher Server.",
        "relevance_score": 0.9,
        "source_priority": 100,
        "supports_claim": True,
        "contradicts_claim": False,
        "notes": "fixture",
        "product": "Rancher Manager",
        "component": "Cluster Agent",
        "claim_types": ["communication_flow"],
        "keywords": ["cluster agent", "connects"],
        "fixture_only": True,
    }


def test_claim_schema_validates_required_fields_and_line_range() -> None:
    claim = Claim.model_validate(claim_payload())
    assert claim.claim_type.value == "communication_flow"
    assert claim.line_end == 3

    invalid = claim_payload()
    invalid["line_end"] = 1
    with pytest.raises(ValidationError):
        Claim.model_validate(invalid)


def test_evidence_schema_generates_stable_excerpt_hash() -> None:
    first = Evidence.model_validate(evidence_payload())
    second = Evidence.model_validate(evidence_payload())

    assert first.excerpt_hash == second.excerpt_hash
    assert first.excerpt_hash == excerpt_digest(first.excerpt)
    assert first.excerpt_hash.startswith("sha256:")


def test_evidence_rejects_incorrect_excerpt_hash() -> None:
    payload = evidence_payload()
    payload["excerpt_hash"] = "sha256:incorrect"
    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def test_evidence_requires_timezone_aware_retrieval_time() -> None:
    payload = evidence_payload()
    payload["retrieved_at"] = datetime(2026, 7, 12)
    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def test_evidence_rejects_domain_outside_official_whitelist() -> None:
    payload = evidence_payload()
    payload["official_domain"] = "blog.example.com"
    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)
