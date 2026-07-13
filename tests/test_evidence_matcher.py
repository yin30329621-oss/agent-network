from agent_network.evidence.matcher import DeterministicEvidenceMatcher
from agent_network.evidence.schemas import Claim, Evidence
from agent_network.evidence.vocabulary import (
    normalize_component,
    normalize_official_domain,
    normalize_product,
    products_match,
    source_priority_for_domain,
)


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
        "entities": [],
        "product": "Rancher Manager",
        "component": "Cluster Agent",
        "version_scope": {"raw": "2.10", "exact": "2.10"},
    }


def evidence_payload() -> dict:
    return {
        "evidence_id": "evidence-test",
        "claim_id": "claim-test",
        "source_type": "fixture",
        "source_title": "FIXTURE: Test",
        "source_url": "https://fixture.invalid/test",
        "official_domain": "ranchermanager.docs.rancher.com",
        "retrieved_at": "2026-07-12T00:00:00Z",
        "product_version": "2.10",
        "excerpt": "FIXTURE ONLY: Cluster Agent connects to Rancher Server.",
        "relevance_score": 0.9,
        "source_priority": 100,
        "supports_claim": True,
        "product": "Rancher Manager",
        "component": "Cluster Agent",
        "claim_types": ["communication_flow"],
        "keywords": ["cluster agent", "connects"],
        "fixture_only": True,
    }


def test_product_and_component_aliases_normalize_without_collapsing_products() -> None:
    assert normalize_product("Rancher") == "rancher_manager"
    assert normalize_component("cluster-agent") == "cluster_agent"
    assert normalize_component("cattle-cluster-agent") == "cluster_agent"
    assert products_match("Rancher Manager", "Rancher")
    assert not products_match("Rancher", "Fleet")
    assert not products_match("RKE", "RKE2")
    assert normalize_official_domain("KUBERNETES.IO") == "kubernetes.io"
    assert source_priority_for_domain("ranchermanager.docs.rancher.com") == 100


def test_matcher_accepts_aliases_and_records_reasons() -> None:
    claim = Claim.model_validate(claim_payload())
    payload = evidence_payload()
    payload["component"] = "cattle-cluster-agent"
    evidence = Evidence.model_validate(payload)

    match = DeterministicEvidenceMatcher().match(claim, evidence)

    assert match.eligible is True
    assert match.product_match is True
    assert match.component_match is True
    assert match.version_match is True
    assert "product_match=true" in match.reasons


def test_wrong_product_or_component_cannot_be_eligible() -> None:
    claim = Claim.model_validate(claim_payload())
    payload = evidence_payload()
    payload["product"] = "Fleet"
    payload["component"] = "Fleet Agent"
    evidence = Evidence.model_validate(payload)

    match = DeterministicEvidenceMatcher().match(claim, evidence)

    assert match.eligible is False
    assert "rejected:wrong_product" in match.reasons
    assert "rejected:wrong_component" in match.reasons


def test_version_mismatch_is_explicit() -> None:
    claim = Claim.model_validate(claim_payload())
    payload = evidence_payload()
    payload["product_version"] = "2.11"
    evidence = Evidence.model_validate(payload)

    match = DeterministicEvidenceMatcher().match(claim, evidence)

    assert match.version_match is False
    assert match.eligible is False
    assert "rejected:version_mismatch" in match.reasons
