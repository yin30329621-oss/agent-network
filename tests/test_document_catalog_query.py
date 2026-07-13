from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_network.config import load_config
from agent_network.evidence.catalog import DocumentCatalogQuery, DocumentCatalogRepository
from agent_network.evidence.sources import DocumentCatalogFixture


FIXTURE_PATH = Path("benchmarks/fixtures/document-catalog-v1")


@pytest.fixture
def repository() -> DocumentCatalogRepository:
    fixture = DocumentCatalogFixture.load(FIXTURE_PATH)
    config = load_config("configs/default.yaml")
    return DocumentCatalogRepository(
        fixture.documents,
        allowed_domains=config.document_source_domains("rancher"),
    )


def test_single_condition_queries(repository: DocumentCatalogRepository) -> None:
    assert [
        item.document_id
        for item in repository.query(DocumentCatalogQuery(claim_id="catalog-claim-cluster-agent"))
    ] == ["rancher-cluster-agent-2-10"]
    assert [
        item.document_id for item in repository.query(DocumentCatalogQuery(product="Fleet"))
    ] == ["fleet-bundle-0-10"]
    assert [
        item.document_id
        for item in repository.query(DocumentCatalogQuery(component="Rancher Server"))
    ] == [
        "rancher-cluster-agent-2-10",
        "rancher-server-reference",
    ]
    assert [
        item.document_id
        for item in repository.query(DocumentCatalogQuery(official_domain="fleet.rancher.io"))
    ] == ["fleet-bundle-0-10"]
    assert [
        item.document_id
        for item in repository.query(DocumentCatalogQuery(document_type="reference"))
    ] == ["rancher-server-reference"]


def test_combined_query_and_strict_product_component_isolation(
    repository: DocumentCatalogRepository,
) -> None:
    result = repository.query(
        DocumentCatalogQuery(
            product="Rancher Manager",
            component="Cluster Agent",
            official_domain="ranchermanager.docs.rancher.com",
            document_type="architecture",
        )
    )

    assert [item.document_id for item in result] == ["rancher-cluster-agent-2-10"]
    assert (
        repository.query(DocumentCatalogQuery(product="Rancher Manager", component="Fleet Agent"))
        == []
    )


def test_deduplication_and_sorting_are_reproducible(repository: DocumentCatalogRepository) -> None:
    first = repository.query(DocumentCatalogQuery(product="Rancher"))
    second = repository.query(DocumentCatalogQuery(product="Rancher"))

    assert [item.canonical_url for item in first] == [
        "https://ranchermanager.docs.rancher.com/fixture/cluster-agent",
        "https://ranchermanager.docs.rancher.com/fixture/rancher-server-reference",
    ]
    assert [item.document_id for item in first] == [item.document_id for item in second]
    assert len({item.canonical_url for item in first}) == len(first)


def test_empty_result_and_zero_network_or_model_calls(
    repository: DocumentCatalogRepository,
) -> None:
    assert repository.query(DocumentCatalogQuery(claim_id="missing-claim")) == []
    assert repository.network_request_count == 0
    assert repository.model_call_count == 0


def test_repository_revalidates_catalog_records() -> None:
    invalid = {
        "document_id": "bad",
        "source_name": "rancher",
        "title": "Bad record",
        "canonical_url": "https://example.invalid/bad",
        "official_domain": "ranchermanager.docs.rancher.com",
        "document_type": "reference",
        "product": "Rancher Manager",
        "fixture_only": True,
        "fixture_excerpt": "fixture",
    }
    with pytest.raises(ValidationError):
        DocumentCatalogRepository([invalid])
