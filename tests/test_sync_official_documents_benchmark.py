from dataclasses import dataclass, field
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from agent_network.evidence.document_cleaner import OfficialDocumentCleaner
from agent_network.evidence.document_fetcher import (
    HttpOfficialDocumentFetcher,
    OfficialDocumentFetchRequest,
)
from agent_network.evidence.official_document_synchronizer import (
    OfficialDocumentSynchronizer,
    OfficialDocumentSyncRequest,
)
from sync_official_documents import (
    SyncBenchmarkSafetyError,
    build_plan,
    load_live_catalog,
    main,
    run_live_sync,
)


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


def response(url: str, text: str = "Cluster Agent documentation") -> FakeResponse:
    return FakeResponse(url, f"<html><main><h1>Document</h1><p>{text}</p></main></html>".encode())


def synchronizer(tmp_path: Path, responses: list[FakeResponse | Exception]) -> tuple:
    repository = load_live_catalog()
    transport = FakeTransport(responses)
    fetcher = HttpOfficialDocumentFetcher(
        allowed_domains={item.official_domain for item in repository.query()},
        transport=transport,
        timeout_seconds=1,
        maximum_response_bytes=10_000,
    )
    return (
        OfficialDocumentSynchronizer(
            repository, fetcher, OfficialDocumentCleaner(), cache_root=tmp_path / "cache"
        ),
        repository,
        transport,
    )


def request(**overrides) -> OfficialDocumentSyncRequest:
    defaults = {
        "document_id": "rancher-downstream-cluster-communication",
        "max_documents": 1,
        "allow_network": True,
        "cache_directory": "acceptance",
    }
    defaults.update(overrides)
    return OfficialDocumentSyncRequest(**defaults)


def live_plan(repository, sync_request, *, confirmed: int = 1):
    return build_plan(
        repository,
        sync_request,
        live_sync_enabled=True,
        confirmed_document_count=confirmed,
    )


def test_default_plan_is_offline_and_does_not_write_cache(capsys) -> None:
    assert main(["--plan"]) == 0

    plan = json.loads(capsys.readouterr().out)
    assert plan["selected_document_count"] == 1
    assert plan["allow_network"] is False
    assert plan["live_sync_enabled"] is False
    assert plan["cache_directory"] is None


def test_catalog_filters_and_plan_document_counts_are_strict() -> None:
    repository = load_live_catalog()
    one = build_plan(
        repository,
        OfficialDocumentSyncRequest(document_id="fleet-overview", max_documents=1),
        live_sync_enabled=False,
    )
    two = build_plan(
        repository, OfficialDocumentSyncRequest(max_documents=2), live_sync_enabled=False
    )

    assert one.selected_document_ids == ["fleet-overview"]
    assert two.selected_document_count == 2
    assert two.planned_max_network_requests == 8
    with pytest.raises(SyncBenchmarkSafetyError, match="not registered"):
        build_plan(
            repository,
            OfficialDocumentSyncRequest(document_id="not-in-catalog", max_documents=1),
            live_sync_enabled=False,
        )
    with pytest.raises(SyncBenchmarkSafetyError, match="cache-directory"):
        build_plan(
            repository,
            OfficialDocumentSyncRequest(cache_directory="../escape", max_documents=1),
            live_sync_enabled=False,
        )


@pytest.mark.parametrize(
    ("sync_request", "enabled", "confirmed", "message"),
    [
        (request(allow_network=False), True, 1, "allow-network"),
        (request(cache_directory=None), True, 1, "cache-directory"),
        (request(), False, 1, "run-live"),
        (request(), True, 2, "explicitly confirmed"),
    ],
)
def test_missing_live_confirmation_rejects_before_fetch(
    tmp_path: Path, sync_request, enabled: bool, confirmed: int, message: str
) -> None:
    subject, repository, transport = synchronizer(tmp_path, [])
    plan = build_plan(
        repository,
        sync_request,
        live_sync_enabled=enabled,
        confirmed_document_count=confirmed,
    )

    with pytest.raises(SyncBenchmarkSafetyError, match=message):
        run_live_sync(subject, sync_request, plan)

    assert transport.calls == []


def test_live_acceptance_sequence_and_cache_integrity_are_mocked(tmp_path: Path) -> None:
    subject, repository, transport = synchronizer(
        tmp_path,
        [
            response(
                "https://ranchermanager.docs.rancher.com/v2.14/reference-guides/"
                "rancher-manager-architecture/communicating-with-downstream-user-clusters"
            ),
            response(
                "https://ranchermanager.docs.rancher.com/v2.14/reference-guides/"
                "rancher-manager-architecture/communicating-with-downstream-user-clusters"
            ),
        ],
    )
    first_request = request()
    first = run_live_sync(subject, first_request, live_plan(repository, first_request))
    skipped_request = request()
    skipped = run_live_sync(subject, skipped_request, live_plan(repository, skipped_request))
    refresh_request = request(force_refresh=True)
    refreshed = run_live_sync(subject, refresh_request, live_plan(repository, refresh_request))

    assert first["fetched_count"] == 1 and first["network_request_count"] == 1
    assert skipped["skipped_count"] == 1 and skipped["network_request_count"] == 0
    assert refreshed["unchanged_count"] == 1 and refreshed["network_request_count"] == 1
    assert first["cache_checks"] == [
        {
            "document_id": "rancher-downstream-cluster-communication",
            "cache_valid": True,
            "final_url": first["records"][0]["final_url"],
        }
    ]
    assert len(transport.calls) == 2
    assert subject.model_call_count == 0


def test_failed_result_does_not_expose_html(tmp_path: Path) -> None:
    subject, repository, _transport = synchronizer(tmp_path, [TimeoutError("sensitive html")])
    sync_request = request()

    result = run_live_sync(subject, sync_request, live_plan(repository, sync_request))

    rendered = json.dumps(result)
    assert result["failed_count"] == 1
    assert "sensitive html" not in rendered
    assert "raw.html" not in rendered
