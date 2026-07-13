from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from agent_network.evidence.cached_official_evidence import (
    CachedDocumentLoadError,
    CachedEvidenceIndexBuilder,
    CachedEvidenceRetrievalRequest,
    _is_navigation_like_chunk,
)
from agent_network.evidence.document_chunker import DocumentChunk
from retrieve_from_official_cache import _parser, build_plan


FETCHED_AT = "2026-07-13T00:00:00+00:00"
MULTIDOC_FIXTURE = Path("benchmarks/fixtures/cached-multidoc-retrieval-v1/documents.json")


def _stable_hash(value: dict) -> str:
    stable = {key: item for key, item in value.items() if key != "source_fetched_at"}
    raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256(raw).hexdigest()


def write_cached_document(
    root: Path,
    document_id: str,
    *,
    product: str = "Rancher Manager",
    component: str = "Cluster Agent",
    document_type: str = "architecture",
    text: str = "Cluster Agent communicates with Rancher Server through a downstream connection. "
    * 5,
) -> Path:
    document_dir = root / "case" / "documents" / document_id
    document_dir.mkdir(parents=True)
    canonical_url = f"https://ranchermanager.docs.rancher.com/fixture/{document_id}"
    cleaned = {
        "document_id": document_id,
        "canonical_url": canonical_url,
        "final_url": canonical_url,
        "product": product,
        "component": component,
        "document_type": document_type,
        "title": f"{document_id} title",
        "plain_text": text,
        "headings": ["Connection"],
        "sections": [{"heading": "Connection", "heading_level": 2, "text": text, "order": 0}],
        "source_fetched_at": FETCHED_AT,
        "source_response_size_bytes": len(text.encode()),
    }
    raw = f"<html><main>{text}</main></html>".encode()
    metadata = {
        "document_id": document_id,
        "canonical_url": canonical_url,
        "final_url": canonical_url,
        "product": product,
        "component": component,
        "document_type": document_type,
        "fetched_at": FETCHED_AT,
        "synced_at": FETCHED_AT,
        "status_code": 200,
        "content_type": "text/html",
        "response_size_bytes": len(raw),
        "raw_content_sha256": sha256(raw).hexdigest(),
        "cleaned_content_sha256": _stable_hash(cleaned),
        "etag": None,
        "last_modified": None,
        "cleaner_version": "1",
        "sync_status": "fetched",
    }
    (document_dir / "raw.html").write_bytes(raw)
    (document_dir / "cleaned.json").write_text(json.dumps(cleaned), encoding="utf-8")
    (document_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return document_dir


def request(**overrides) -> CachedEvidenceRetrievalRequest:
    values = {
        "cache_directory": "case",
        "query_text": "Cluster Agent Rancher Server downstream connection",
        "max_documents": 2,
        "top_chunks": 5,
    }
    values.update(overrides)
    return CachedEvidenceRetrievalRequest(**values)


def write_multidoc_fixture(root: Path) -> list[str]:
    documents = json.loads(MULTIDOC_FIXTURE.read_text(encoding="utf-8"))
    for document in documents:
        write_cached_document(root, **document)
    return [document["document_id"] for document in documents]


def test_valid_cache_loads_chunks_and_retrieves_expected_evidence(tmp_path: Path) -> None:
    write_cached_document(tmp_path, "rancher-downstream-cluster-communication")
    subject = CachedEvidenceIndexBuilder(cache_root=tmp_path)

    result = subject.retrieve(request(document_id="rancher-downstream-cluster-communication"))

    assert result.loaded_document_count == 1
    assert result.failed_document_count == 0
    assert result.total_chunk_count == 1
    assert result.returned_evidence_count == 1
    assert result.evidences[0].document_id == "rancher-downstream-cluster-communication"
    assert set(result.evidences[0].matched_terms) >= {"cluster", "agent", "rancher", "server"}
    assert (
        result.network_request_count
        == subject.network_request_count
        == subject.model_call_count
        == 0
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("checksum", "checksum_mismatch"),
        ("json", "invalid_json"),
        ("metadata", "metadata_mismatch"),
    ],
)
def test_invalid_cache_is_reported_without_network(
    tmp_path: Path, mutation: str, code: str
) -> None:
    document_dir = write_cached_document(tmp_path, "broken")
    if mutation == "checksum":
        metadata = json.loads((document_dir / "metadata.json").read_text())
        metadata["cleaned_content_sha256"] = "0" * 64
        (document_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    elif mutation == "json":
        (document_dir / "cleaned.json").write_text("{", encoding="utf-8")
    else:
        metadata = json.loads((document_dir / "metadata.json").read_text())
        metadata["product"] = "Fleet"
        (document_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    result = CachedEvidenceIndexBuilder(cache_root=tmp_path).retrieve(request(document_id="broken"))

    assert result.loaded_document_count == 0
    assert result.failed_document_count == 1
    assert result.cache_failures[0].error_code == code
    assert result.network_request_count == 0


def test_one_broken_cache_does_not_hide_other_valid_document(tmp_path: Path) -> None:
    valid = write_cached_document(tmp_path, "valid")
    write_cached_document(tmp_path, "broken")
    metadata = json.loads(
        (tmp_path / "case" / "documents" / "broken" / "metadata.json").read_text()
    )
    metadata["raw_content_sha256"] = "x" * 64
    (tmp_path / "case" / "documents" / "broken" / "metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    before = {path.name: path.read_bytes() for path in valid.iterdir()}

    result = CachedEvidenceIndexBuilder(cache_root=tmp_path).retrieve(request())

    assert result.loaded_document_count == 1
    assert result.failed_document_count == 1
    assert result.evidences[0].document_id == "valid"
    failures = {item.document_id: item.failure_code for item in result.per_document_summary}
    assert failures["broken"] == "checksum_mismatch"
    assert before == {path.name: path.read_bytes() for path in valid.iterdir()}


def test_multidocument_fixture_uses_one_shared_index_and_stable_selection(tmp_path: Path) -> None:
    document_ids = write_multidoc_fixture(tmp_path)
    subject = CachedEvidenceIndexBuilder(cache_root=tmp_path)
    query = "Cluster Agent ServiceAccount RBAC manages downstream clusters"

    forward = subject.retrieve(
        request(document_ids=tuple(document_ids), max_documents=4, query_text=query, top_chunks=4)
    )
    reverse = subject.retrieve(
        request(
            document_ids=tuple(reversed(document_ids)),
            max_documents=4,
            query_text=query,
            top_chunks=4,
        )
    )

    assert forward.loaded_document_count == forward.selected_document_count == 4
    assert forward.total_chunk_count == 4
    assert [summary.document_id for summary in forward.per_document_summary] == document_ids
    assert {item.document_id for item in forward.evidences} >= {
        "cluster-agent-tunnel",
        "serviceaccount-rbac",
    }
    assert [item.chunk_id for item in forward.evidences] == [
        item.chunk_id for item in reverse.evidences
    ]
    assert forward.network_request_count == 0


def test_document_selection_filters_and_max_documents_are_strict(tmp_path: Path) -> None:
    write_multidoc_fixture(tmp_path)
    subject = CachedEvidenceIndexBuilder(cache_root=tmp_path)

    result = subject.retrieve(
        request(
            document_ids=("fleet-bundle", "cluster-agent-tunnel", "serviceaccount-rbac"),
            max_documents=2,
            product="Rancher Manager",
            query_text="Cluster Agent ServiceAccount",
        )
    )

    assert result.selected_document_count == 2
    assert {item.document_id for item in result.evidences} == {
        "cluster-agent-tunnel",
        "serviceaccount-rbac",
    }
    assert all(item.document_id != "fleet-bundle" for item in result.evidences)

    fleet = subject.retrieve(
        request(
            document_ids=("cluster-agent-tunnel", "fleet-bundle"),
            product="Fleet",
            component="Fleet Agent",
            document_type="reference",
            query_text="Fleet Bundle GitOps",
        )
    )
    assert [item.document_id for item in fleet.evidences] == ["fleet-bundle"]


def test_multidocument_diversity_and_per_document_cap_are_deterministic(tmp_path: Path) -> None:
    cluster_text = (
        "Cluster Agent connects Rancher Server to downstream clusters through a tunnel. " * 35
    )
    rbac_text = "Cluster Agent uses a ServiceAccount with RBAC for downstream cluster access. " * 12
    write_cached_document(tmp_path, "cluster", text=cluster_text)
    write_cached_document(tmp_path, "rbac", component="ServiceAccount", text=rbac_text)
    subject = CachedEvidenceIndexBuilder(cache_root=tmp_path)
    baseline = subject.retrieve(
        request(
            document_ids=("cluster", "rbac"),
            query_text="Cluster Agent ServiceAccount RBAC downstream",
            top_chunks=1,
        )
    )

    result = subject.retrieve(
        request(
            document_ids=("cluster", "rbac"),
            query_text="Cluster Agent ServiceAccount RBAC downstream",
            top_chunks=2,
            max_chunks_per_document=1,
            min_documents_in_results=2,
        )
    )

    assert result.evidences[0].chunk_id == baseline.evidences[0].chunk_id
    assert {item.document_id for item in result.evidences} == {"cluster", "rbac"}
    assert result.returned_document_count == 2
    assert [item.rank for item in result.evidences] == [1, 2]
    assert all(summary.returned_evidence_count <= 1 for summary in result.per_document_summary)


def test_filters_ranks_and_no_match_are_deterministic(tmp_path: Path) -> None:
    write_cached_document(tmp_path, "rancher", component="Cluster Agent")
    write_cached_document(tmp_path, "fleet", product="Fleet", component="Fleet Agent")
    subject = CachedEvidenceIndexBuilder(cache_root=tmp_path)

    filtered = subject.retrieve(request(product="Rancher Manager", component="Cluster Agent"))
    no_match = subject.retrieve(
        request(query_text="unrelated vocabulary", product="Rancher Manager")
    )

    assert [item.document_id for item in filtered.evidences] == ["rancher"]
    assert [item.rank for item in filtered.evidences] == [1]
    assert no_match.returned_evidence_count == 0


def test_quality_thresholds_filter_candidates_and_rerank_stably(tmp_path: Path) -> None:
    write_cached_document(tmp_path, "first")
    write_cached_document(tmp_path, "second")
    subject = CachedEvidenceIndexBuilder(cache_root=tmp_path)

    strict = subject.retrieve(request(min_score=1_000.0))
    selected = subject.retrieve(request(min_matched_terms=2, top_chunks=2))

    assert strict.candidate_evidence_count == 2
    assert strict.returned_evidence_count == 0
    assert strict.filtered_reasons_summary == {"below_min_score": 2}
    assert [item.rank for item in selected.evidences] == [1, 2]
    assert len({item.chunk_id for item in selected.evidences}) == 2


def test_navigation_like_cached_chunks_are_optionally_excluded(tmp_path: Path) -> None:
    text = "On this page\n\n- Cluster Agent\n\n- Rancher Server\n\n- Downstream Connection\n" * 4
    write_cached_document(tmp_path, "toc", text=text)
    subject = CachedEvidenceIndexBuilder(cache_root=tmp_path)

    result = subject.retrieve(
        request(
            document_id="toc",
            query_text="Cluster Agent Rancher Server",
            exclude_navigation_like=True,
            min_matched_terms=2,
        )
    )

    assert result.returned_evidence_count == 0
    assert result.filtered_reasons_summary == {"navigation_like": 1}


def _quality_chunk(text: str, heading: str = "Section") -> DocumentChunk:
    from datetime import UTC, datetime

    return DocumentChunk(
        chunk_id="quality-check",
        document_id="quality-check",
        canonical_url="https://ranchermanager.docs.rancher.com/fixture",
        final_url="https://ranchermanager.docs.rancher.com/fixture",
        product="Rancher Manager",
        component="Cluster Agent",
        document_type="reference",
        document_title="Quality fixture",
        section_heading=heading,
        section_heading_level=2,
        section_order=0,
        chunk_order=0,
        text=text,
        character_count=len(text),
        source_fetched_at=datetime(2026, 7, 13, tzinfo=UTC),
    )


def test_navigation_detector_handles_name_directory_but_preserves_technical_lists() -> None:
    directory = _quality_chunk(
        "A source index.\n\n- GitHub repository\n- Rancher charts\n- System components\n- Resource pages"
    )
    steps = _quality_chunk("- Install the agent\n- Configure the endpoint\n- Verify the connection")
    permissions = _quality_chunk(
        "- ClusterRole grants read access\n- RoleBinding connects the ServiceAccount\n"
        "- Permissions must be reviewed"
    )
    explanation = _quality_chunk(
        "The component list explains how requests are handled.\n"
        "- Cluster Agent maintains a connection to the server.\n"
        "- The server validates the request before forwarding it."
    )

    assert _is_navigation_like_chunk(directory) is True
    assert _is_navigation_like_chunk(steps) is False
    assert _is_navigation_like_chunk(permissions) is False
    assert _is_navigation_like_chunk(explanation) is False


def test_cache_path_escape_is_rejected_and_plan_is_read_only(tmp_path: Path) -> None:
    subject = CachedEvidenceIndexBuilder(cache_root=tmp_path)
    with pytest.raises(CachedDocumentLoadError, match="stay below"):
        subject.load(request(cache_directory="../escape"))

    write_cached_document(tmp_path, "planned")
    plan = build_plan(subject, request(document_id="planned"), run=False)
    assert plan.selected_document_ids == ["planned"]
    assert plan.network_request_count == 0
    assert plan.run_enabled is False


def test_benchmark_uses_explicit_quality_defaults_without_changing_library_defaults() -> None:
    defaults = CachedEvidenceRetrievalRequest()
    args = _parser().parse_args([])

    assert (defaults.min_score, defaults.min_matched_terms, defaults.exclude_navigation_like) == (
        0.0,
        1,
        False,
    )
    assert (args.min_score, args.min_matched_terms, args.exclude_navigation_like) == (1.0, 2, True)
    assert args.include_filtered_summary is False


def test_benchmark_accepts_repeated_document_ids_and_multidocument_options() -> None:
    args = _parser().parse_args(
        [
            "--document-id",
            "cluster",
            "--document-id",
            "rbac",
            "--max-chunks-per-document",
            "2",
            "--min-documents-in-results",
            "2",
        ]
    )

    assert args.document_id == ["cluster", "rbac"]
    assert args.max_chunks_per_document == args.min_documents_in_results == 2
