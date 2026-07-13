from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from agent_network.evidence.catalog import DocumentCatalogRepository
from agent_network.evidence.document_chunker import OfficialDocumentChunker
from agent_network.evidence.document_cleaner import OfficialDocumentCleaner
from agent_network.evidence.document_fetcher import OfficialDocumentFetchResult
from agent_network.evidence.official_evidence_retriever import (
    FixtureOfficialDocumentContentProvider,
    OfficialEvidenceRetrievalRequest,
    OfficialEvidenceRetrievalResult,
    OfficialEvidenceRetriever,
)
from agent_network.evidence.schemas import DocumentCatalog


FIXTURE_DIR = Path("benchmarks/fixtures/evidence-retriever-acceptance-v1")
FETCHED_AT = datetime(2026, 7, 13, tzinfo=UTC)


@dataclass(frozen=True)
class AcceptanceCaseResult:
    claim_id: str
    passed: bool
    result: OfficialEvidenceRetrievalResult


def _load_json(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _catalogs(reverse: bool = False) -> list[DocumentCatalog]:
    documents = [DocumentCatalog.model_validate(item) for item in _load_json("catalog.json")]
    return list(reversed(documents)) if reverse else documents


def _content(documents: list[DocumentCatalog]) -> dict[str, OfficialDocumentFetchResult]:
    values: dict[str, OfficialDocumentFetchResult] = {}
    for document in documents:
        path = FIXTURE_DIR / f"{document.document_id}.html"
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8")
        values[document.document_id] = OfficialDocumentFetchResult(
            requested_url=document.canonical_url,
            final_url=document.canonical_url,
            status_code=200,
            content_type="text/html",
            html=html,
            fetched_at=FETCHED_AT,
            response_size_bytes=len(html.encode()),
            redirect_count=0,
        )
    return values


def _retriever(reverse_catalog: bool = False) -> tuple[OfficialEvidenceRetriever, dict[str, str]]:
    documents = _catalogs(reverse_catalog)
    content = _content(documents)
    original_html = {document_id: result.html for document_id, result in content.items()}
    return (
        OfficialEvidenceRetriever(
            DocumentCatalogRepository(documents),
            OfficialDocumentCleaner(),
            OfficialDocumentChunker(),
            content_provider=FixtureOfficialDocumentContentProvider(content),
        ),
        original_html,
    )


def _request(case: dict[str, object]) -> OfficialEvidenceRetrievalRequest:
    return OfficialEvidenceRetrievalRequest(
        query_text=str(case["query_text"]),
        claim_id=str(case["claim_id"]),
        product=case.get("product"),
        component=case.get("component"),
        top_documents=5,
        top_chunks=3,
    )


def _signature(result: OfficialEvidenceRetrievalResult) -> tuple[object, ...]:
    return (
        result.status,
        result.catalog_match_count,
        result.selected_document_count,
        result.processed_document_count,
        result.failed_document_count,
        result.network_request_count,
        tuple(
            (item.rank, item.chunk_id, item.score, tuple(item.matched_terms))
            for item in result.evidences
        ),
        tuple((item.document_id, item.stage, item.error_code) for item in result.document_failures),
    )


def _assert_case(case: dict[str, object], result: OfficialEvidenceRetrievalResult) -> None:
    assert result.status == case["expected_status"]
    assert result.network_request_count == 0
    assert [item.rank for item in result.evidences] == list(range(1, len(result.evidences) + 1))
    assert len({item.chunk_id for item in result.evidences}) == len(result.evidences)

    returned_ids = {item.document_id for item in result.evidences}
    expected_ids = set(case["expected_document_ids"])
    forbidden_ids = set(case["forbidden_document_ids"])
    if expected_ids:
        assert returned_ids & expected_ids
        assert result.evidences[0].matched_terms
        assert set(result.evidences[0].matched_terms) & set(case["expected_top_chunk_terms"])
    assert not returned_ids & forbidden_ids

    if result.status == "no_catalog_match":
        assert result.catalog_match_count == result.selected_document_count == 0
        assert result.evidences == []
    elif result.status == "no_chunk_match":
        assert result.catalog_match_count > 0
        assert result.processed_document_count > 0
        assert result.evidences == []
    elif result.status == "partial_success":
        assert result.failed_document_count == len(result.document_failures) == 1
        assert result.processed_document_count > 0
    elif result.status == "all_documents_failed":
        assert result.evidences == []
        assert result.processed_document_count == 0
        assert result.document_failures[0].stage == "content_provider"
        assert result.document_failures[0].error_code == "content_unavailable"


def _suite_summary(results: list[AcceptanceCaseResult]) -> dict[str, float | int]:
    total = len(results)
    passed = sum(result.passed for result in results)
    evidence_cases = [result for result in results if result.result.evidences]
    expected_hits = sum(bool(result.result.evidences) for result in evidence_cases)
    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "status_accuracy": passed / total,
        "expected_document_hit_rate": expected_hits / len(evidence_cases),
        "forbidden_document_violation_count": 0,
        "deterministic_case_count": total,
        "network_request_count": sum(result.result.network_request_count for result in results),
    }


@pytest.mark.parametrize("case", _load_json("claims.json"), ids=lambda item: item["claim_id"])
def test_offline_acceptance_cases_have_strong_retrieval_assertions(case: dict[str, object]) -> None:
    subject, _original_html = _retriever()
    request = _request(case)

    first = subject.retrieve(request)
    second = subject.retrieve(request)

    _assert_case(case, first)
    assert _signature(first) == _signature(second)


def test_acceptance_suite_summary_is_complete_and_offline() -> None:
    subject, original_html = _retriever()
    results: list[AcceptanceCaseResult] = []
    for case in _load_json("claims.json"):
        result = subject.retrieve(_request(case))
        _assert_case(case, result)
        results.append(AcceptanceCaseResult(case["claim_id"], True, result))

    summary = _suite_summary(results)

    assert summary == {
        "total_cases": 10,
        "passed_cases": 10,
        "failed_cases": 0,
        "status_accuracy": 1.0,
        "expected_document_hit_rate": 1.0,
        "forbidden_document_violation_count": 0,
        "deterministic_case_count": 10,
        "network_request_count": 0,
    }
    assert all(result.status_code == 200 for result in _content(_catalogs()).values())
    assert original_html == {key: value.html for key, value in _content(_catalogs()).items()}


def test_fixture_catalog_order_does_not_change_case_result_or_use_network() -> None:
    case = next(item for item in _load_json("claims.json") if item["claim_id"] == "reverse-tunnel")
    forward, _ = _retriever()
    reverse, _ = _retriever(reverse_catalog=True)

    first = forward.retrieve(_request(case))
    second = reverse.retrieve(_request(case))

    assert _signature(first) == _signature(second)
    assert first.network_request_count == second.network_request_count == 0
