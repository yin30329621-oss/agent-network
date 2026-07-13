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
from agent_network.evidence.official_document_synchronizer import OfficialDocumentSynchronizer
from sync_and_retrieve_official_documents import (
    SyncRetrieveSafetyError,
    build_plan,
    load_sync_retrieve_catalog,
    main,
    run_live_sync_and_retrieve,
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


DOCUMENT_TEXT = {
    "rancher-downstream-cluster-communication": (
        "Cluster Agent maintains a connection to Rancher Server for downstream cluster management. "
        "The downstream cluster is managed through the agent connection."
    ),
    "rancher-rbac-reference": (
        "ServiceAccount and RBAC roles grant permissions for downstream cluster access. "
        "Cluster Agent uses the authorized access required to manage Kubernetes resources."
    ),
    "fleet-overview": (
        "Fleet Bundle distributes GitOps resources to target clusters. "
        "Fleet Agent applies Bundle resources and reports deployment state."
    ),
    "rancher-tls-settings": (
        "HTTPS and TLS protect Rancher Server communication. "
        "Operators configure the TLS endpoint for Rancher Manager."
    ),
}


def response(repository, document_id: str) -> FakeResponse:
    document = next(item for item in repository.query() if item.document_id == document_id)
    text = DOCUMENT_TEXT[document_id]
    html = f"<html><main><h1>{document.title}</h1><p>{text}</p></main></html>"
    return FakeResponse(document.canonical_url, html.encode())


def synchronizer(tmp_path: Path, responses: list[FakeResponse | Exception]):
    repository = load_sync_retrieve_catalog()
    transport = FakeTransport(responses)
    fetcher = HttpOfficialDocumentFetcher(
        allowed_domains={document.official_domain for document in repository.query()},
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


def plan(repository, document_ids: tuple[str, ...], *, force_refresh: bool = False, product=None):
    return build_plan(
        repository,
        document_ids=document_ids,
        product=product,
        component=None,
        max_documents=len(document_ids),
        cache_directory="p8",
        force_refresh=force_refresh,
        allow_network=True,
        query_text="How does Rancher use Cluster Agent and ServiceAccount RBAC downstream clusters?",
        top_chunks=6,
        max_chunks_per_document=2,
        min_documents_in_results=2,
        live_sync_enabled=True,
    )


def run(subject, sync_plan, *, confirmed=None):
    return run_live_sync_and_retrieve(
        subject,
        sync_plan,
        confirmed_document_count=confirmed or sync_plan.selected_document_count,
        min_score=0.0,
        min_matched_terms=1,
        exclude_navigation_like=True,
    )


def test_default_plan_is_offline_and_does_not_write_cache(capsys) -> None:
    assert main(["--plan"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["allow_network"] is False
    assert payload["live_sync_enabled"] is False
    assert payload["selected_document_count"] == 1


def test_plan_selects_three_or_four_controlled_documents_and_rejects_unsafe_input() -> None:
    repository = load_sync_retrieve_catalog()
    ids = tuple(document.document_id for document in repository.query())
    three = plan(repository, ids[:3])
    four = plan(repository, ids)

    assert three.selected_document_count == 3
    assert four.selected_document_count == 4
    assert four.planned_max_network_requests == 16
    assert four.products.count("Fleet") == 1
    with pytest.raises(SyncRetrieveSafetyError, match="cache-directory"):
        build_plan(
            repository,
            document_ids=ids[:3],
            product=None,
            component=None,
            max_documents=3,
            cache_directory="../escape",
            force_refresh=False,
            allow_network=False,
            query_text="query",
            top_chunks=1,
            max_chunks_per_document=0,
            min_documents_in_results=1,
            live_sync_enabled=False,
        )


def test_missing_confirmation_rejects_before_network(tmp_path: Path) -> None:
    subject, repository, transport = synchronizer(tmp_path, [])
    sync_plan = plan(repository, ("rancher-downstream-cluster-communication",))

    with pytest.raises(SyncRetrieveSafetyError, match="explicitly confirmed"):
        run(subject, sync_plan, confirmed=2)

    assert transport.calls == []


def test_multi_document_sync_then_shared_retrieval_is_mocked_and_fail_soft(tmp_path: Path) -> None:
    ids = (
        "rancher-downstream-cluster-communication",
        "rancher-rbac-reference",
        "fleet-overview",
    )
    catalog = load_sync_retrieve_catalog()
    subject, repository, transport = synchronizer(
        tmp_path, [response(catalog, document_id) for document_id in ids]
    )
    sync_plan = plan(repository, ids)

    result = run(subject, sync_plan)

    assert result["sync_summary"]["fetched_count"] == 3
    assert result["sync_summary"]["network_request_count"] == 3
    assert result["retrieval_summary"]["loaded_document_count"] == 3
    assert result["retrieval_summary"]["returned_document_count"] >= 2
    assert {item["document_id"] for item in result["retrieval_summary"]["evidences"]} >= {
        "rancher-downstream-cluster-communication",
        "rancher-rbac-reference",
    }
    assert result["overall"] == {
        "total_network_request_count": 3,
        "model_call_count": 0,
        "completed": True,
        "safe_errors": [],
    }
    assert len(transport.calls) == 3


def test_second_run_skips_and_force_refresh_is_unchanged(tmp_path: Path) -> None:
    ids = ("rancher-downstream-cluster-communication", "rancher-rbac-reference")
    catalog = load_sync_retrieve_catalog()
    subject, repository, transport = synchronizer(
        tmp_path,
        [response(catalog, item) for item in ids] + [response(catalog, item) for item in ids],
    )
    first_plan = plan(repository, ids)
    run(subject, first_plan)
    skipped = run(subject, plan(repository, ids))
    refreshed = run(subject, plan(repository, ids, force_refresh=True))

    assert skipped["sync_summary"]["skipped_count"] == 2
    assert skipped["overall"]["total_network_request_count"] == 0
    assert refreshed["sync_summary"]["unchanged_count"] == 2
    assert refreshed["overall"]["total_network_request_count"] == 2
    assert len(transport.calls) == 4


def test_fleet_query_isolated_and_single_sync_failure_is_safe(tmp_path: Path) -> None:
    ids = ("rancher-downstream-cluster-communication", "fleet-overview")
    catalog = load_sync_retrieve_catalog()
    subject, repository, _transport = synchronizer(
        tmp_path, [TimeoutError("private response"), response(catalog, "fleet-overview")]
    )
    sync_plan = plan(repository, ids)

    result = run(subject, sync_plan)
    fleet_plan = plan(repository, ("fleet-overview",), product="Fleet")
    fleet_result = run(subject, fleet_plan)

    assert result["sync_summary"]["failed_count"] == 1
    assert result["retrieval_summary"]["loaded_document_count"] == 1
    assert "private response" not in json.dumps(result)
    assert fleet_result["retrieval_summary"]["evidences"][0]["document_id"] == "fleet-overview"
    assert fleet_result["overall"]["model_call_count"] == 0
