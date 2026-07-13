from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agent_network.evidence.catalog import DocumentCatalogRepository
from agent_network.evidence.document_cleaner import OfficialDocumentCleaner
from agent_network.evidence.document_fetcher import (
    HttpOfficialDocumentFetcher,
    OfficialDocumentFetchRequest,
)
from agent_network.evidence.official_document_synchronizer import (
    DocumentSyncError,
    OfficialDocumentCache,
    OfficialDocumentSynchronizer,
    OfficialDocumentSyncRequest,
)
from agent_network.evidence.schemas import DocumentCatalog


RANCHER_DOMAIN = "ranchermanager.docs.rancher.com"
FLEET_DOMAIN = "fleet.rancher.io"


@dataclass
class FakeResponse:
    url: str
    body: bytes
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=lambda: {"Content-Type": "text/html"})
    offset: int = 0

    def read(self, size: int) -> bytes:
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        pass


@dataclass
class FakeTransport:
    responses: list[FakeResponse | Exception]
    calls: list[OfficialDocumentFetchRequest] = field(default_factory=list)

    def open(self, request: OfficialDocumentFetchRequest) -> FakeResponse:
        self.calls.append(request)
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


def document(document_id: str, *, product: str = "Rancher Manager") -> DocumentCatalog:
    domain = FLEET_DOMAIN if product == "Fleet" else RANCHER_DOMAIN
    return DocumentCatalog(
        document_id=document_id,
        source_name="fixture",
        title=f"{document_id} title",
        canonical_url=f"https://{domain}/fixture/{document_id}",
        official_domain=domain,
        document_type="reference",
        product=product,
        components=["Fleet Agent" if product == "Fleet" else "Cluster Agent"],
    )


def response(document_id: str, text: str = "Cluster Agent content") -> FakeResponse:
    return FakeResponse(
        f"https://{RANCHER_DOMAIN}/fixture/{document_id}",
        f"<html><main><h1>{document_id}</h1><p>{text}</p></main></html>".encode(),
    )


def synchronizer(tmp_path: Path, documents: list[DocumentCatalog], responses) -> tuple:
    transport = FakeTransport(responses)
    fetcher = HttpOfficialDocumentFetcher(
        allowed_domains={RANCHER_DOMAIN, FLEET_DOMAIN},
        transport=transport,
        timeout_seconds=1,
        maximum_response_bytes=10_000,
    )
    subject = OfficialDocumentSynchronizer(
        DocumentCatalogRepository(documents, allowed_domains={RANCHER_DOMAIN, FLEET_DOMAIN}),
        fetcher,
        OfficialDocumentCleaner(),
        cache_root=tmp_path / "cache-root",
    )
    return subject, transport


def test_first_sync_writes_complete_cache_and_stable_hashes(tmp_path: Path) -> None:
    subject, _transport = synchronizer(tmp_path, [document("cluster")], [response("cluster")])

    result = subject.sync(OfficialDocumentSyncRequest(allow_network=True))

    cache = tmp_path / "cache-root" / "documents" / "cluster"
    metadata = __import__("json").loads((cache / "metadata.json").read_text(encoding="utf-8"))
    assert result.fetched_count == 1
    assert result.network_request_count == 1
    assert [record.sync_status for record in result.records] == ["fetched"]
    assert (cache / "raw.html").is_file() and (cache / "cleaned.json").is_file()
    assert len(metadata["raw_content_sha256"]) == len(metadata["cleaned_content_sha256"]) == 64
    assert metadata["etag"] is None and metadata["last_modified"] is None


def test_cached_sync_skips_without_network_and_force_refresh_detects_unchanged(
    tmp_path: Path,
) -> None:
    subject, transport = synchronizer(
        tmp_path, [document("cluster")], [response("cluster"), response("cluster")]
    )
    subject.sync(OfficialDocumentSyncRequest(allow_network=True))

    skipped = subject.sync(OfficialDocumentSyncRequest(allow_network=False))
    unchanged = subject.sync(OfficialDocumentSyncRequest(allow_network=True, force_refresh=True))

    assert skipped.skipped_count == 1 and skipped.network_request_count == 0
    assert unchanged.unchanged_count == 1 and unchanged.network_request_count == 1
    assert len(transport.calls) == 2


def test_force_refresh_changed_content_replaces_cache(tmp_path: Path) -> None:
    subject, _transport = synchronizer(
        tmp_path,
        [document("cluster")],
        [response("cluster", "old text"), response("cluster", "new text")],
    )
    subject.sync(OfficialDocumentSyncRequest(allow_network=True))
    changed = subject.sync(OfficialDocumentSyncRequest(allow_network=True, force_refresh=True))

    raw = (tmp_path / "cache-root" / "documents" / "cluster" / "raw.html").read_text(
        encoding="utf-8"
    )
    assert changed.fetched_count == 1
    assert "new text" in raw


def test_network_disabled_and_single_document_failure_are_fail_soft(tmp_path: Path) -> None:
    subject, transport = synchronizer(
        tmp_path,
        [document("first"), document("second")],
        [TimeoutError("offline"), response("second")],
    )

    disabled = subject.sync(OfficialDocumentSyncRequest(allow_network=False))
    result = subject.sync(OfficialDocumentSyncRequest(allow_network=True))

    assert disabled.failed_count == 2 and disabled.network_request_count == 0
    assert result.failed_count == 1 and result.fetched_count == 1
    assert result.records[0].error_code == "timeout"
    assert result.records[0].network_request_count == 1
    assert len(transport.calls) == 2


def test_atomic_write_failure_keeps_existing_cache(tmp_path: Path, monkeypatch) -> None:
    subject, _transport = synchronizer(
        tmp_path,
        [document("cluster")],
        [response("cluster", "old"), response("cluster", "new")],
    )
    subject.sync(OfficialDocumentSyncRequest(allow_network=True))
    raw_path = tmp_path / "cache-root" / "documents" / "cluster" / "raw.html"
    old_raw = raw_path.read_text(encoding="utf-8")

    def fail_activate(self, staged, target, backup):
        raise OSError("simulated activation failure")

    monkeypatch.setattr(OfficialDocumentCache, "_activate", fail_activate)
    failed = subject.sync(OfficialDocumentSyncRequest(allow_network=True, force_refresh=True))

    assert failed.failed_count == 1
    assert raw_path.read_text(encoding="utf-8") == old_raw


def test_cache_path_filters_and_catalog_order_are_safe_and_stable(tmp_path: Path) -> None:
    fleet = document("fleet", product="Fleet")
    rancher = document("rancher")
    subject, transport = synchronizer(
        tmp_path,
        [fleet, rancher],
        [response("rancher"), response("fleet")],
    )

    rancher_only = subject.sync(
        OfficialDocumentSyncRequest(product="Rancher Manager", allow_network=True, max_documents=1)
    )
    with pytest.raises(DocumentSyncError, match="cache root"):
        subject.sync(OfficialDocumentSyncRequest(cache_directory="../escape"))

    assert [record.document_id for record in rancher_only.records] == ["rancher"]
    assert rancher_only.network_request_count == 1
    assert len(transport.calls) == 1
