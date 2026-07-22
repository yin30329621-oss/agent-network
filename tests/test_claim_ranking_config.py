import json
from pathlib import Path

import pytest

from agent_network.claim import Claim
from agent_network.claim.ranking import ClaimRanker
from agent_network.claim.ranking_config import RankingConfig, load_ranking_config


def test_ranking_profiles_load_and_are_versioned() -> None:
    default = load_ranking_config("configs/ranking/default.yaml")
    legacy = load_ranking_config(
        "configs/ranking/rancher-security-review-v1-legacy-v0.5.1.yaml"
    )

    assert (default.config_id, default.ranking_version, default.algorithm) == (
        "default",
        "v0.5.2",
        "deterministic_claim_metadata_v3",
    )
    assert (legacy.config_id, legacy.ranking_version, legacy.algorithm) == (
        "rancher-security-review-v1-legacy-v0.5.1",
        "v0.5.1",
        "deterministic_claim_metadata_v2",
    )
    assert len(legacy.section_salience) == 14
    assert default.sha256().startswith("sha256:")


def test_ranking_profile_rejects_unknown_claim_type() -> None:
    payload = load_ranking_config("configs/ranking/default.yaml").model_dump()
    payload["score"]["claim_type_weights"]["not_a_claim_type"] = 1

    with pytest.raises(ValueError, match="unknown Claim types"):
        RankingConfig.model_validate(payload)


def test_ranking_profile_rejects_duplicate_section_rule_ids() -> None:
    payload = load_ranking_config(
        "configs/ranking/rancher-security-review-v1-legacy-v0.5.1.yaml"
    ).model_dump()
    payload["section_salience"].append(payload["section_salience"][0])

    with pytest.raises(ValueError, match="rule_id values must be unique"):
        RankingConfig.model_validate(payload)


def test_legacy_profile_reproduces_candidate_ranking_artifact() -> None:
    claims_path = Path("cases/rancher-security-review-v1/output/claims.json")
    ranking_path = Path("cases/rancher-security-review-v1/output/claim-ranking.json")
    claims = [Claim.model_validate(item) for item in json.loads(claims_path.read_text())["claims"]]
    expected = json.loads(ranking_path.read_text())
    config = load_ranking_config(
        "configs/ranking/rancher-security-review-v1-legacy-v0.5.1.yaml"
    )

    result = ClaimRanker(config).rank(claims, top_k=expected["selection_limit"])

    assert [item.model_dump(mode="json") for item in result.ranked_claims] == expected[
        "ranked_claims"
    ]
    assert result.selected_claim_ids == expected["selected_claim_ids"]
