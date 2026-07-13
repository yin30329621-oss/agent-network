"""Small orchestration layer for retrieving official document evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from agent_network.evidence.catalog import DocumentCatalogQuery, DocumentCatalogRepository
from agent_network.evidence.document_bm25 import (
    Bm25Error,
    Bm25SearchQuery,
    OfficialDocumentBm25Index,
)
from agent_network.evidence.document_chunker import (
    DocumentChunk,
    DocumentChunkingError,
    OfficialDocumentChunker,
)
from agent_network.evidence.document_cleaner import DocumentCleaningError, OfficialDocumentCleaner
from agent_network.evidence.document_fetcher import (
    HttpOfficialDocumentFetcher,
    OfficialDocumentFetchError,
    OfficialDocumentFetchResult,
)
from agent_network.evidence.schemas import DocumentCatalog


class OfficialEvidenceRetrievalError(RuntimeError):
    """A safe, categorical failure for invalid retrieval requests or index failures."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OfficialDocumentContentProviderError(RuntimeError):
    """A safe failure returned by an offline document content provider."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class OfficialDocumentContentProvider(Protocol):
    network_request_count: int

    def get(self, document: DocumentCatalog) -> OfficialDocumentFetchResult:
        """Return pre-fetched content for one validated catalog document."""


class FixtureOfficialDocumentContentProvider:
    """Deterministic, in-memory provider used by offline retrieval tests."""

    def __init__(self, documents: dict[str, OfficialDocumentFetchResult]) -> None:
        self._documents = dict(documents)
        self.network_request_count = 0
        self.model_call_count = 0

    def get(self, document: DocumentCatalog) -> OfficialDocumentFetchResult:
        try:
            return self._documents[document.document_id]
        except KeyError as exc:
            raise OfficialDocumentContentProviderError(
                "content_unavailable", "No offline content is available for this catalog document"
            ) from exc


@dataclass(frozen=True, slots=True)
class OfficialEvidenceRetrievalRequest:
    query_text: str
    claim_id: str | None = None
    product: str | None = None
    component: str | None = None
    official_domain: str | None = None
    document_type: str | None = None
    document_id: str | None = None
    top_documents: int = 5
    top_chunks: int = 5
    allow_network: bool = False


@dataclass(slots=True)
class RetrievedOfficialEvidence:
    rank: int
    score: float
    matched_terms: list[str]
    chunk_id: str
    document_id: str
    canonical_url: str
    final_url: str
    product: str
    component: str
    document_type: str
    document_title: str
    section_heading: str
    section_order: int
    chunk_order: int
    text: str
    source_fetched_at: datetime

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["source_fetched_at"] = self.source_fetched_at.isoformat()
        return data


@dataclass(slots=True)
class OfficialEvidenceDocumentFailure:
    document_id: str
    canonical_url: str
    stage: str
    error_code: str
    safe_message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class OfficialEvidenceRetrievalResult:
    query_text: str
    status: str
    catalog_match_count: int
    selected_document_count: int
    processed_document_count: int
    failed_document_count: int
    total_chunk_count: int
    returned_evidence_count: int
    network_request_count: int
    evidences: list[RetrievedOfficialEvidence]
    document_failures: list[OfficialEvidenceDocumentFailure]
    retrieval_started_at: datetime
    retrieval_completed_at: datetime

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["retrieval_started_at"] = self.retrieval_started_at.isoformat()
        data["retrieval_completed_at"] = self.retrieval_completed_at.isoformat()
        return data


class OfficialEvidenceRetriever:
    """Catalog-bound pipeline: fetch/provider, clean, chunk, then BM25 search."""

    def __init__(
        self,
        repository: DocumentCatalogRepository,
        cleaner: OfficialDocumentCleaner,
        chunker: OfficialDocumentChunker,
        *,
        fetcher: HttpOfficialDocumentFetcher | None = None,
        content_provider: OfficialDocumentContentProvider | None = None,
    ) -> None:
        self.repository = repository
        self.cleaner = cleaner
        self.chunker = chunker
        self.fetcher = fetcher
        self.content_provider = content_provider
        self.network_request_count = 0
        self.model_call_count = 0

    def retrieve(
        self, request: OfficialEvidenceRetrievalRequest
    ) -> OfficialEvidenceRetrievalResult:
        _validate_request(request)
        started_at = datetime.now(UTC)
        candidates = self._catalog_candidates(request)
        selected = candidates[: request.top_documents]
        if not candidates:
            return _result(request, "no_catalog_match", 0, 0, started_at)

        provider_before = _counter(self.content_provider)
        fetcher_before = _counter(self.fetcher)
        chunks: list[DocumentChunk] = []
        failures: list[OfficialEvidenceDocumentFailure] = []
        processed = 0
        for document in selected:
            try:
                fetched = self._content_for(document, request.allow_network)
                cleaned = self.cleaner.clean(fetched, document)
                chunks.extend(self.chunker.chunk(cleaned))
                processed += 1
            except Exception as exc:
                failures.append(_document_failure(document, exc))

        network_count = _counter(self.content_provider) - provider_before
        network_count += _counter(self.fetcher) - fetcher_before
        self.network_request_count += network_count
        if not processed:
            return _result(
                request,
                "all_documents_failed",
                len(candidates),
                len(selected),
                started_at,
                failures=failures,
                network_count=network_count,
            )

        try:
            results = OfficialDocumentBm25Index(chunks).search(
                Bm25SearchQuery(
                    query_text=request.query_text,
                    top_k=request.top_chunks,
                    product=request.product,
                    component=request.component,
                    document_type=request.document_type,
                    document_id=request.document_id,
                )
            )
        except Bm25Error as exc:
            raise OfficialEvidenceRetrievalError(
                "indexing_error", "Official evidence index failed"
            ) from exc

        evidences = [_evidence_from_result(result) for result in results]
        status = _status(evidences, failures)
        return OfficialEvidenceRetrievalResult(
            query_text=request.query_text,
            status=status,
            catalog_match_count=len(candidates),
            selected_document_count=len(selected),
            processed_document_count=processed,
            failed_document_count=len(failures),
            total_chunk_count=len(chunks),
            returned_evidence_count=len(evidences),
            network_request_count=network_count,
            evidences=evidences,
            document_failures=failures,
            retrieval_started_at=started_at,
            retrieval_completed_at=datetime.now(UTC),
        )

    def _catalog_candidates(
        self, request: OfficialEvidenceRetrievalRequest
    ) -> list[DocumentCatalog]:
        try:
            query = DocumentCatalogQuery(
                claim_id=request.claim_id,
                product=request.product,
                component=request.component,
                official_domain=request.official_domain,
                document_type=request.document_type,
            )
            matches = self.repository.query(query)
        except Exception as exc:
            raise OfficialEvidenceRetrievalError(
                "catalog_error", "Official catalog query failed"
            ) from exc
        if request.document_id is not None:
            matches = [
                document for document in matches if document.document_id == request.document_id
            ]
        return matches

    def _content_for(
        self, document: DocumentCatalog, allow_network: bool
    ) -> OfficialDocumentFetchResult:
        if allow_network:
            if self.fetcher is None:
                raise OfficialDocumentContentProviderError(
                    "content_unavailable", "No official document fetcher is configured"
                )
            return self.fetcher.fetch(document)
        if self.content_provider is None:
            raise OfficialDocumentContentProviderError(
                "content_unavailable", "Offline content is not available for this catalog document"
            )
        return self.content_provider.get(document)


def _validate_request(request: OfficialEvidenceRetrievalRequest) -> None:
    if not request.query_text.strip() or request.top_documents <= 0 or request.top_chunks <= 0:
        raise OfficialEvidenceRetrievalError(
            "invalid_request", "Official evidence request is invalid"
        )


def _document_failure(
    document: DocumentCatalog, error: Exception
) -> OfficialEvidenceDocumentFailure:
    if isinstance(error, OfficialDocumentContentProviderError):
        stage = "content_provider"
    elif isinstance(error, OfficialDocumentFetchError):
        stage = "fetch"
    elif isinstance(error, DocumentCleaningError):
        stage = "clean"
    elif isinstance(error, DocumentChunkingError):
        stage = "chunk"
    else:
        stage = "processing_error"
    return OfficialEvidenceDocumentFailure(
        document_id=document.document_id,
        canonical_url=document.canonical_url,
        stage=stage,
        error_code=getattr(error, "code", "processing_error"),
        safe_message=str(error) if stage != "processing_error" else "Document processing failed",
    )


def _evidence_from_result(result) -> RetrievedOfficialEvidence:
    chunk = result.chunk
    return RetrievedOfficialEvidence(
        rank=result.rank,
        score=result.score,
        matched_terms=result.matched_terms,
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        canonical_url=chunk.canonical_url,
        final_url=chunk.final_url,
        product=chunk.product,
        component=chunk.component,
        document_type=chunk.document_type,
        document_title=chunk.document_title,
        section_heading=chunk.section_heading,
        section_order=chunk.section_order,
        chunk_order=chunk.chunk_order,
        text=chunk.text,
        source_fetched_at=chunk.source_fetched_at,
    )


def _status(
    evidences: list[RetrievedOfficialEvidence], failures: list[OfficialEvidenceDocumentFailure]
) -> str:
    if evidences:
        return "partial_success" if failures else "success"
    return "no_chunk_match"


def _counter(value: object | None) -> int:
    return int(getattr(value, "network_request_count", 0)) if value is not None else 0


def _result(
    request: OfficialEvidenceRetrievalRequest,
    status: str,
    catalog_match_count: int,
    selected_document_count: int,
    started_at: datetime,
    *,
    failures: list[OfficialEvidenceDocumentFailure] | None = None,
    network_count: int = 0,
) -> OfficialEvidenceRetrievalResult:
    return OfficialEvidenceRetrievalResult(
        query_text=request.query_text,
        status=status,
        catalog_match_count=catalog_match_count,
        selected_document_count=selected_document_count,
        processed_document_count=0,
        failed_document_count=len(failures or []),
        total_chunk_count=0,
        returned_evidence_count=0,
        network_request_count=network_count,
        evidences=[],
        document_failures=failures or [],
        retrieval_started_at=started_at,
        retrieval_completed_at=datetime.now(UTC),
    )
