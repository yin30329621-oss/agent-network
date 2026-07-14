from pathlib import Path

from agent_network.evidence.catalog import DocumentCatalogQuery, DocumentCatalogRepository
from agent_network.evidence.schemas import Claim, Evidence
from agent_network.evidence.sources import (
    DocumentCatalogFixture,
    FixtureOfficialDocumentEvidenceSource,
    load_official_document_domain_config,
)
from agent_network.evidence.vocabulary import components_match


DOMAIN_CONFIG = Path("configs/evidence_domains/rancher.yaml")
FIXTURE_PATH = Path("benchmarks/fixtures/official-document-evidence-v1")


def test_rancher_domain_config_keeps_products_and_components_distinct() -> None:
    config = load_official_document_domain_config(DOMAIN_CONFIG)

    assert config.domain_id == "rancher"
    assert set(config.products) == {"rancher_manager", "fleet", "rke", "rke2"}
    assert config.official_domains["rancher_manager"] == ["ranchermanager.docs.rancher.com"]
    assert config.official_domains["fleet"] == ["fleet.rancher.io"]
    assert "Fleet Agent" not in config.components["rancher_manager"]
    assert "Cluster Agent" not in config.components["fleet"]


def test_component_alias_and_fixture_catalog_are_offline_and_validated() -> None:
    fixture = DocumentCatalogFixture.load(FIXTURE_PATH)

    assert fixture.fixture_notice.startswith("FIXTURE ONLY")
    assert len(fixture.documents) == 10
    assert components_match("cattle-cluster-agent", "Cluster Agent")
    cluster_agent = next(
        item for item in fixture.documents if item.document_id == "fixture-cluster-agent"
    )
    assert cluster_agent.product_version == "v2.10"
    assert cluster_agent.component == "Cluster Agent"
    assert cluster_agent.fetched_at is not None
    assert cluster_agent.content_hash == "sha256:fixture-cluster-agent"
    assert all(item.fixture_only for item in fixture.documents)
    assert all(item.canonical_url.startswith("https://") for item in fixture.documents)
    assert all(".invalid/" in item.canonical_url for item in fixture.documents)


def test_fixture_catalog_preserves_product_isolation_and_zero_calls() -> None:
    fixture = DocumentCatalogFixture.load(FIXTURE_PATH)
    repository = DocumentCatalogRepository(fixture.documents)
    source = FixtureOfficialDocumentEvidenceSource(
        "rancher",
        {"ranchermanager.docs.rancher.com", "fleet.rancher.io", "rancher.com"},
        fixture.documents,
    )
    claim = Claim(
        claim_id="fixture-fleet",
        source_file="fixture.md",
        section="Fixture",
        line_start=1,
        line_end=1,
        original_text="Fleet Agent applies Bundle resources.",
        normalized_claim="fleet agent applies bundle resources",
        claim_type="rancher_feature",
        product="Fleet",
        component="Fleet Agent",
    )

    assert [
        item.document_id for item in repository.query(DocumentCatalogQuery(product="Fleet"))
    ] == [
        "fixture-bundle",
        "fixture-fleet-agent",
    ]
    assert (
        repository.query(DocumentCatalogQuery(product="Rancher Manager", component="Fleet Agent"))
        == []
    )
    assert source.search(claim) == []
    assert repository.network_request_count == 0
    assert repository.model_call_count == 0
    assert source.network_request_count == 0


def test_fixture_catalog_remains_compatible_with_evidence_schema() -> None:
    evidence = Evidence(
        evidence_id="fixture-evidence",
        claim_id="fixture-claim",
        source_type="official_document_catalog_fixture",
        source_title="FIXTURE ONLY: Cluster Agent",
        source_url="https://rancher-fixtures.invalid/cluster-agent",
        official_domain="ranchermanager.docs.rancher.com",
        retrieved_at="2026-01-03T00:00:00Z",
        product_version="v2.10",
        excerpt="FIXTURE ONLY: Cluster Agent metadata.",
        relevance_score=1.0,
        source_priority=100,
        product="Rancher Manager",
        component="Cluster Agent",
        claim_types=["communication_flow"],
        fixture_only=True,
    )

    assert evidence.fixture_only is True
    assert evidence.product_version == "v2.10"
