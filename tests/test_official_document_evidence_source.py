from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_network.config import load_config
from agent_network.evidence.schemas import Claim, DocumentCatalog
from agent_network.evidence.sources import (
    DocumentCatalogFixture,
    FixtureOfficialDocumentEvidenceSource,
)


def catalog_claim(claim_id: str, product: str, component: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        source_file="fixture.md",
        section="Catalog",
        line_start=1,
        line_end=1,
        original_text="Synthetic catalog claim.",
        normalized_claim="Synthetic catalog claim",
        claim_type="communication_flow",
        product=product,
        component=component,
    )


def test_document_catalog_validates_official_url_and_timezone() -> None:
    catalog = DocumentCatalog(
        document_id="test-doc",
        source_name="rancher",
        title="Test document",
        canonical_url="https://ranchermanager.docs.rancher.com/test",
        official_domain="ranchermanager.docs.rancher.com",
        product="Rancher Manager",
        updated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
    assert catalog.official_domain == "ranchermanager.docs.rancher.com"

    invalid = catalog.model_dump()
    invalid["canonical_url"] = "https://example.invalid/not-official"
    with pytest.raises(ValidationError):
        DocumentCatalog(**invalid)


def test_rancher_domain_config_loads() -> None:
    config = load_config("configs/default.yaml")

    assert config.document_source_config("rancher")["mode"] == "catalog_only"
    assert config.document_source_domains("rancher") == {
        "ranchermanager.docs.rancher.com",
        "rancher.com",
        "fleet.rancher.io",
    }


def test_catalog_fixture_source_returns_only_direct_catalog_evidence() -> None:
    fixture = DocumentCatalogFixture.load("benchmarks/fixtures/document-catalog-v1")
    source = FixtureOfficialDocumentEvidenceSource(
        "rancher",
        {"ranchermanager.docs.rancher.com", "rancher.com", "fleet.rancher.io"},
        fixture.documents,
    )

    evidence = source.search(
        catalog_claim("catalog-claim-cluster-agent", "Rancher", "Cluster Agent")
    )

    assert len(evidence) == 1
    assert evidence[0].source_metadata["catalog_only"] is True
    assert evidence[0].fixture_only is True
    assert source.network_request_count == 0


def test_catalog_fixture_does_not_mix_rancher_and_fleet() -> None:
    fixture = DocumentCatalogFixture.load("benchmarks/fixtures/document-catalog-v1")
    source = FixtureOfficialDocumentEvidenceSource(
        "rancher",
        {"ranchermanager.docs.rancher.com", "rancher.com", "fleet.rancher.io"},
        fixture.documents,
    )

    evidence = source.search(
        catalog_claim("catalog-claim-fleet-bundle", "Rancher Manager", "Fleet Agent")
    )

    assert evidence == []
