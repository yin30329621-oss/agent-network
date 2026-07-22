from agent_network.claim import Claim, ClaimRegistry, ClaimType
from agent_network.claim.ranking import ClaimRanker
from agent_network.claim.ranking_config import load_ranking_config


def make_claim(claim_id: str, **overrides) -> Claim:
    values = {
        "claim_id": claim_id,
        "text": "The component provides a documented behavior.",
        "claim_type": ClaimType.OTHER,
        "priority": "medium",
        "requires_external_evidence": False,
    }
    values.update(overrides)
    return Claim(**values)


def test_ranking_is_deterministic_and_preserves_claim_contract() -> None:
    claims = [
        make_claim("claim-b", priority="high"),
        make_claim("claim-a", priority="high"),
        make_claim(
            "claim-security",
            text="Authentication requires RBAC and secure token handling.",
            claim_type=ClaimType.AUTHORIZATION,
            priority="high",
            requires_external_evidence=True,
        ),
    ]

    result = ClaimRanker().rank(claims)

    assert [item.claim_id for item in result.ranked_claims] == [
        "claim-security",
        "claim-a",
        "claim-b",
    ]
    assert result.ranked_claims[0].priority_score == 97
    assert "security_sensitive" in result.ranked_claims[0].reason_codes
    assert "claim_type_authorization" in result.ranked_claims[0].reason_codes
    assert result.ranked_claims[0].factors["requires_external_evidence"] == 5
    assert result.ranked_claims[1].priority_score == result.ranked_claims[2].priority_score
    assert result.ranked_claims[1].claim_id < result.ranked_claims[2].claim_id
    assert claims[0].priority == "high"
    assert "priority_score" not in claims[0].to_dict()


def test_ranking_scores_architecture_core_and_selects_top_k() -> None:
    claims = [
        make_claim("claim-plain", priority="critical"),
        make_claim(
            "claim-architecture",
            text="Rancher API Server manages the management plane.",
            claim_type=ClaimType.ARCHITECTURE,
            component="Rancher API Server",
            priority="critical",
            requires_external_evidence=True,
        ),
        make_claim("claim-low", priority="low"),
    ]

    result = ClaimRanker().rank(claims, top_k=2)

    architecture = result.ranked_claims[0]
    assert architecture.claim_id == "claim-architecture"
    assert architecture.priority_score == 100
    assert "architecture_core" in architecture.reason_codes
    assert result.selected_claim_ids == ["claim-architecture", "claim-plain"]


def test_ranking_applies_section_salience_without_changing_claims() -> None:
    claim = make_claim(
        "claim-agent",
        text="Cluster Agent communicates through a reverse tunnel.",
        claim_type=ClaimType.ARCHITECTURE,
        section="3.3.1 Cluster Agent",
        heading_path=["Rancher", "3.3.1 Cluster Agent"],
        source_location="report.md#rancher.3-3-1-cluster-agent:paragraph-1:L1-L1",
        requires_external_evidence=True,
    )

    legacy = load_ranking_config(
        "configs/ranking/rancher-security-review-v1-legacy-v0.5.1.yaml"
    )
    item = ClaimRanker(legacy).rank([claim]).ranked_claims[0]

    assert item.factors["section_salience"] == 20
    assert "section_cluster_agent" in item.reason_codes
    assert item.priority_score == 83


def test_selection_returns_existing_claims_without_mutating_registry() -> None:
    registry = ClaimRegistry(
        [make_claim("claim-z", priority="low"), make_claim("claim-a", priority="high")]
    )

    ranking = ClaimRanker().rank(registry, top_k=1)
    selected = ranking.select_claims(registry)

    assert [claim.claim_id for claim in selected] == ["claim-a"]
    assert selected[0] is registry.get("claim-a")
    assert [claim.claim_id for claim in registry] == ["claim-z", "claim-a"]


def test_empty_and_invalid_top_k_are_explicit() -> None:
    empty = ClaimRanker().rank([])
    assert empty.total_claim_count == 0
    assert empty.ranked_claims == []
    assert empty.selected_claim_ids == []

    try:
        ClaimRanker().rank([], top_k=0)
    except ValueError as exc:
        assert str(exc) == "top_k must be positive when provided"
    else:
        raise AssertionError("expected invalid top_k to fail")


def test_ranking_metadata_is_versioned_and_traceable() -> None:
    result = ClaimRanker().rank(
        [make_claim("claim-1")],
        source_claim_file="cases/example/output/claims.json",
        input_identifier="example-candidate-1",
    )

    payload = result.to_dict()
    assert payload["ranking_version"] == "v0.5.2"
    assert payload["algorithm"] == "deterministic_claim_metadata_v3"
    assert payload["artifact_schema_version"] == "2"
    assert payload["config_id"] == "default"
    assert payload["config_version"] == "1"
    assert payload["config_sha256"].startswith("sha256:")
    assert payload["source_claim_file"] == "cases/example/output/claims.json"
    assert payload["input_identifier"] == "example-candidate-1"
