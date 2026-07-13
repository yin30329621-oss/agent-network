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
)
from retrieve_from_official_cache import build_plan


FETCHED_AT = "2026-07-13T00:00:00+00:00"


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
    assert before == {path.name: path.read_bytes() for path in valid.iterdir()}


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


def test_cache_path_escape_is_rejected_and_plan_is_read_only(tmp_path: Path) -> None:
    subject = CachedEvidenceIndexBuilder(cache_root=tmp_path)
    with pytest.raises(CachedDocumentLoadError, match="stay below"):
        subject.load(request(cache_directory="../escape"))

    write_cached_document(tmp_path, "planned")
    plan = build_plan(subject, request(document_id="planned"), run=False)
    assert plan.selected_document_ids == ["planned"]
    assert plan.network_request_count == 0
    assert plan.run_enabled is False
