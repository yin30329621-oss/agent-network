from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from agent_network.evidence.catalog import DocumentCatalogRepository
from agent_network.evidence.document_chunker import OfficialDocumentChunker
from agent_network.evidence.document_cleaner import OfficialDocumentCleaner
from agent_network.evidence.document_fetcher import (
    HttpOfficialDocumentFetcher,
    OfficialDocumentFetchRequest,
    OfficialDocumentFetchResult,
)
from agent_network.evidence.official_evidence_retriever import (
    FixtureOfficialDocumentContentProvider,
    OfficialEvidenceRetrievalError,
    OfficialEvidenceRetrievalRequest,
    OfficialEvidenceRetriever,
)
from agent_network.evidence.schemas import DocumentCatalog


FETCHED_AT = datetime(2026, 7, 13, tzinfo=UTC)
DOMAIN = "ranchermanager.docs.rancher.com"
FLEET_DOMAIN = "fleet.rancher.io"


def catalog(
    document_id: str,
    *,
    product: str = "Rancher Manager",
    component: str = "Cluster Agent",
    document_type: str = "reference",
    claim_id: str = "claim-cluster",
    domain: str = DOMAIN,
) -> DocumentCatalog:
    return DocumentCatalog(
        document_id=document_id,
        source_name="rancher",
        title=f"{document_id} title",
        canonical_url=f"https://{domain}/{document_id}",
        official_domain=domain,
        document_type=document_type,
        product=product,
        components=[component],
        supported_claim_ids=[claim_id],
    )


def fetched(document: DocumentCatalog, body: str) -> OfficialDocumentFetchResult:
    html = f"<html><body><main><h1>{document.title}</h1><h2>Details</h2><p>{body}</p></main></body></html>"
    return OfficialDocumentFetchResult(
        requested_url=document.canonical_url,
        final_url=document.canonical_url,
        status_code=200,
        content_type="text/html",
        html=html,
        fetched_at=FETCHED_AT,
        response_size_bytes=len(html.encode()),
        redirect_count=0,
    )


def retriever(
    documents: list[DocumentCatalog], content: dict[str, OfficialDocumentFetchResult]
) -> OfficialEvidenceRetriever:
    return OfficialEvidenceRetriever(
        DocumentCatalogRepository(documents),
        OfficialDocumentCleaner(),
        OfficialDocumentChunker(),
        content_provider=FixtureOfficialDocumentContentProvider(content),
    )


def test_offline_cluster_and_fleet_retrieval_are_isolated() -> None:
    cluster = catalog("cluster", claim_id="claim-cluster")
    fleet = catalog(
        "fleet",
        product="Fleet",
        component="Fleet Agent",
        claim_id="claim-fleet",
        domain=FLEET_DOMAIN,
    )
    subject = retriever(
        [fleet, cluster],
        {
            "cluster": fetched(cluster, "Cluster Agent maintains a reverse tunnel over TLS."),
            "fleet": fetched(fleet, "Fleet Bundle deploys GitOps resources."),
        },
    )

    cluster_result = subject.retrieve(
        OfficialEvidenceRetrievalRequest("reverse tunnel", claim_id="claim-cluster")
    )
    fleet_result = subject.retrieve(
        OfficialEvidenceRetrievalRequest("Fleet Bundle", claim_id="claim-fleet")
    )

    assert cluster_result.status == fleet_result.status == "success"
    assert cluster_result.evidences[0].document_id == "cluster"
    assert fleet_result.evidences[0].document_id == "fleet"
    assert cluster_result.network_request_count == fleet_result.network_request_count == 0


def test_catalog_and_bm25_filters_and_limits_are_preserved() -> None:
    cluster = catalog("cluster")
    rbac = catalog("rbac", component="ServiceAccount", document_type="security_advisory")
    subject = retriever(
        [cluster, rbac],
        {
            "cluster": fetched(cluster, "Cluster Agent reverse tunnel."),
            "rbac": fetched(rbac, "ServiceAccount RBAC RoleBinding."),
        },
    )

    result = subject.retrieve(
        OfficialEvidenceRetrievalRequest(
            "RBAC", component="ServiceAccount", document_type="security_advisory", top_chunks=1
        )
    )
    limited = subject.retrieve(OfficialEvidenceRetrievalRequest("Agent", top_documents=1))
    by_id = subject.retrieve(OfficialEvidenceRetrievalRequest("RBAC", document_id="rbac"))

    assert result.evidences[0].document_id == "rbac"
    assert len(result.evidences) == 1
    assert limited.selected_document_count == 1
    assert by_id.evidences[0].document_id == "rbac"


def test_no_catalog_match_and_no_chunk_match_are_stable() -> None:
    cluster = catalog("cluster")
    subject = retriever([cluster], {"cluster": fetched(cluster, "Cluster Agent reverse tunnel.")})

    absent = subject.retrieve(
        OfficialEvidenceRetrievalRequest("reverse", claim_id="not-in-catalog")
    )
    unmatched = subject.retrieve(OfficialEvidenceRetrievalRequest("unavailable-phrase"))

    assert absent.status == "no_catalog_match"
    assert absent.catalog_match_count == 0
    assert unmatched.status == "no_chunk_match"
    assert unmatched.processed_document_count == 1
    assert unmatched.returned_evidence_count == 0


def test_document_failures_are_fail_soft_and_safe() -> None:
    good = catalog("good")
    broken = catalog("broken")
    empty = fetched(broken, "")
    empty.html = ""
    subject = retriever(
        [broken, good],
        {"good": fetched(good, "Cluster Agent reverse tunnel."), "broken": empty},
    )

    result = subject.retrieve(OfficialEvidenceRetrievalRequest("reverse tunnel"))

    assert result.status == "partial_success"
    assert result.processed_document_count == 1
    assert result.failed_document_count == 1
    assert result.document_failures[0].document_id == "broken"
    assert result.document_failures[0].stage == "clean"
    assert result.document_failures[0].error_code == "empty_html"
    assert result.evidences[0].rank == 1


def test_all_documents_failed_and_missing_offline_content_are_reported() -> None:
    missing = catalog("missing")
    subject = retriever([missing], {})

    result = subject.retrieve(OfficialEvidenceRetrievalRequest("reverse"))

    assert result.status == "all_documents_failed"
    assert result.document_failures[0].stage == "content_provider"
    assert result.document_failures[0].error_code == "content_unavailable"


def test_retrieval_is_deterministic_and_does_not_mutate_fixture_content() -> None:
    cluster = catalog("cluster")
    content = {"cluster": fetched(cluster, "Cluster Agent maintains a reverse tunnel.")}
    subject = retriever([cluster], content)
    request = OfficialEvidenceRetrievalRequest("reverse tunnel")

    first = subject.retrieve(request)
    second = subject.retrieve(request)

    assert [evidence.to_dict() for evidence in first.evidences] == [
        evidence.to_dict() for evidence in second.evidences
    ]
    assert content["cluster"].html.startswith("<html>")
    assert len({evidence.chunk_id for evidence in first.evidences}) == len(first.evidences)


@dataclass
class FakeResponse:
    status_code: int
    url: str
    headers: dict[str, str]
    body: bytes = b""
    offset: int = 0

    def read(self, size: int) -> bytes:
        value = self.body[self.offset : self.offset + size]
        self.offset += len(value)
        return value

    def close(self) -> None:
        pass


@dataclass
class FakeTransport:
    responses: list[FakeResponse]
    calls: list[OfficialDocumentFetchRequest] = field(default_factory=list)

    def open(self, request: OfficialDocumentFetchRequest) -> FakeResponse:
        self.calls.append(request)
        return self.responses[len(self.calls) - 1]


def test_allow_network_false_never_uses_fetcher_and_mock_network_is_counted() -> None:
    document = catalog("network")
    offline = FixtureOfficialDocumentContentProvider(
        {"network": fetched(document, "Cluster Agent reverse tunnel.")}
    )
    transport = FakeTransport(
        [
            FakeResponse(
                302,
                document.canonical_url,
                {"Location": f"https://{FLEET_DOMAIN}/network"},
            ),
            FakeResponse(
                200,
                f"https://{FLEET_DOMAIN}/network",
                {"Content-Type": "text/html"},
                b"<html><body><main><p>Cluster Agent reverse tunnel.</p></main></body></html>",
            ),
        ]
    )
    fetcher = HttpOfficialDocumentFetcher(
        allowed_domains={DOMAIN, FLEET_DOMAIN}, transport=transport
    )
    subject = OfficialEvidenceRetriever(
        DocumentCatalogRepository([document]),
        OfficialDocumentCleaner(),
        OfficialDocumentChunker(),
        fetcher=fetcher,
        content_provider=offline,
    )

    offline_result = subject.retrieve(
        OfficialEvidenceRetrievalRequest("reverse", allow_network=False)
    )
    network_result = subject.retrieve(
        OfficialEvidenceRetrievalRequest("reverse", allow_network=True)
    )

    assert offline_result.network_request_count == 0
    assert transport.calls[0].url == document.canonical_url
    assert network_result.network_request_count == 2
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "retrieval_request",
    [
        OfficialEvidenceRetrievalRequest(""),
        OfficialEvidenceRetrievalRequest("query", top_documents=0),
        OfficialEvidenceRetrievalRequest("query", top_chunks=0),
    ],
)
def test_invalid_requests_are_rejected(
    retrieval_request: OfficialEvidenceRetrievalRequest,
) -> None:
    subject = retriever([], {})

    with pytest.raises(OfficialEvidenceRetrievalError) as error:
        subject.retrieve(retrieval_request)

    assert error.value.code == "invalid_request"
