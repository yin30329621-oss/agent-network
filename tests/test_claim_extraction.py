import pytest
from pydantic import ValidationError

from agent_network.claim import (
    ClaimExtractionRequest,
    ClaimType,
    DeterministicClaimExtractor,
)


def request(text: str, **kwargs) -> ClaimExtractionRequest:
    return ClaimExtractionRequest(document_text=text, source_name="report.md", **kwargs)


def test_extracts_markdown_claims_with_locations_and_types() -> None:
    result = DeterministicClaimExtractor().extract(
        request(
            """# Architecture\n\nCluster Agent connects to Rancher Server through a tunnel.\n\n- ServiceAccount requires RBAC permissions.\n\n| Item | Statement |\n| --- | --- |\n| TLS | HTTPS protects communication. |\n"""
        )
    )

    assert len(result.claims) == 3
    assert result.claims[0].claim_type is ClaimType.ARCHITECTURE
    assert result.claims[1].claim_type is ClaimType.AUTHORIZATION
    assert result.claims[2].claim_type is ClaimType.SECURITY_CONTROL
    assert result.claims[0].source_location == "report.md#architecture:paragraph-1:L3-L3"
    assert all(claim.extraction_method == "deterministic" for claim in result.claims)


def test_excludes_code_commands_urls_navigation_and_quotes() -> None:
    result = DeterministicClaimExtractor().extract(
        request(
            """# Contents\n\n如下所示\n\n`kubectl get pods`\n\nhttps://example.test/docs\n\n> Cluster Agent connects to the server.\n\n```yaml\napiVersion: v1\n```\n\nThe server manages downstream clusters.\n"""
        )
    )

    assert [claim.text for claim in result.claims] == ["The server manages downstream clusters."]


def test_headings_can_be_enabled_but_plain_titles_are_excluded() -> None:
    result = DeterministicClaimExtractor().extract(
        request(
            """# Cluster Agent\n# Cluster Agent connects to Rancher Server\n""",
            include_headings=True,
        )
    )

    assert [claim.text for claim in result.claims] == ["Cluster Agent connects to Rancher Server"]


def test_duplicate_claims_are_removed_and_ids_are_stable() -> None:
    text = """# Architecture\n\nCluster Agent connects to Rancher Server.\n\nCluster Agent connects to Rancher Server.\n"""
    extractor = DeterministicClaimExtractor()
    first = extractor.extract(request(text))
    second = extractor.extract(request(text))

    assert len(first.claims) == 1
    assert first.duplicate_count == 1
    assert first.claims[0].claim_id == second.claims[0].claim_id


def test_input_and_configuration_validation_is_explicit() -> None:
    with pytest.raises(ValidationError, match="document_text"):
        request("   ")
    with pytest.raises(ValidationError, match="maximum_input_characters"):
        request("statement", maximum_input_characters=5)
    with pytest.raises(ValidationError, match="source_type"):
        request("valid statement.", source_type="html")
