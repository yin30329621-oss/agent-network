"""Read-only evidence retrieval from synchronized official document cache entries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from agent_network.evidence.document_bm25 import Bm25SearchQuery, OfficialDocumentBm25Index
from agent_network.evidence.document_chunker import DocumentChunk, OfficialDocumentChunker
from agent_network.evidence.document_cleaner import CleanedOfficialDocument, DocumentSection
from agent_network.evidence.official_document_synchronizer import DEFAULT_CACHE_DIRECTORY
from agent_network.evidence.official_evidence_retriever import RetrievedOfficialEvidence


class CachedDocumentLoadError(RuntimeError):
    """Safe failure while reading a local official-document cache entry."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CachedEvidenceRetrievalRequest:
    cache_directory: str | None = None
    document_id: str | None = None
    product: str | None = None
    component: str | None = None
    document_type: str | None = None
    max_documents: int = 1
    query_text: str = ""
    top_chunks: int = 5


@dataclass(slots=True)
class CachedDocumentFailure:
    document_id: str
    error_code: str
    safe_message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(slots=True)
class CachedDocumentLoadResult:
    documents: list[CleanedOfficialDocument]
    failures: list[CachedDocumentFailure]
    discovered_document_ids: list[str]
    selected_document_ids: list[str]


@dataclass(slots=True)
class CachedEvidenceRetrievalResult:
    loaded_document_count: int
    failed_document_count: int
    total_chunk_count: int
    returned_evidence_count: int
    network_request_count: int
    evidences: list[RetrievedOfficialEvidence]
    cache_failures: list[CachedDocumentFailure]

    def to_dict(self) -> dict[str, object]:
        return {
            "loaded_document_count": self.loaded_document_count,
            "failed_document_count": self.failed_document_count,
            "total_chunk_count": self.total_chunk_count,
            "returned_evidence_count": self.returned_evidence_count,
            "network_request_count": self.network_request_count,
            "evidences": [item.to_dict() for item in self.evidences],
            "cache_failures": [item.to_dict() for item in self.cache_failures],
        }


class CachedEvidenceIndexBuilder:
    """Build deterministic Chunk/BM25 results from a controlled local cache only."""

    def __init__(
        self,
        *,
        cache_root: Path = DEFAULT_CACHE_DIRECTORY,
        chunker: OfficialDocumentChunker | None = None,
    ) -> None:
        self.cache_root = cache_root.resolve()
        self.chunker = chunker or OfficialDocumentChunker()
        self.network_request_count = 0
        self.model_call_count = 0

    def load(self, request: CachedEvidenceRetrievalRequest) -> CachedDocumentLoadResult:
        _validate_request(request)
        root = _cache_directory(self.cache_root, request.cache_directory)
        documents_root = root / "documents"
        if not documents_root.exists():
            return CachedDocumentLoadResult([], [], [], [])
        if not documents_root.is_dir():
            raise CachedDocumentLoadError("cache_read_error", "Cache documents path is invalid")
        discovered = sorted(path.name for path in documents_root.iterdir() if path.is_dir())
        selected = discovered if request.document_id is None else [request.document_id]
        documents: list[CleanedOfficialDocument] = []
        failures: list[CachedDocumentFailure] = []
        selected_ids: list[str] = []
        for document_id in selected:
            if len(selected_ids) >= request.max_documents:
                break
            try:
                loaded = _load_document(documents_root, document_id)
                if not _matches(loaded, request):
                    continue
                documents.append(loaded)
                selected_ids.append(document_id)
            except CachedDocumentLoadError as exc:
                failures.append(CachedDocumentFailure(document_id, exc.code, str(exc)))
                selected_ids.append(document_id)
        return CachedDocumentLoadResult(documents, failures, discovered, selected_ids)

    def retrieve(self, request: CachedEvidenceRetrievalRequest) -> CachedEvidenceRetrievalResult:
        if not request.query_text.strip():
            raise CachedDocumentLoadError("invalid_request", "query_text must not be empty")
        loaded = self.load(request)
        chunks: list[DocumentChunk] = []
        failures = list(loaded.failures)
        for document in loaded.documents:
            try:
                chunks.extend(self.chunker.chunk(document))
            except Exception as exc:
                failures.append(
                    CachedDocumentFailure(
                        document.document_id,
                        getattr(exc, "code", "chunk_error"),
                        "Cached document could not be chunked",
                    )
                )
        if not chunks:
            return CachedEvidenceRetrievalResult(
                len(loaded.documents), len(failures), 0, 0, 0, [], failures
            )
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
        evidences = [_evidence(result) for result in results]
        return CachedEvidenceRetrievalResult(
            len(loaded.documents),
            len(failures),
            len(chunks),
            len(evidences),
            0,
            evidences,
            failures,
        )


def _load_document(documents_root: Path, document_id: str) -> CleanedOfficialDocument:
    document_root = documents_root / document_id
    if not document_root.is_dir():
        raise CachedDocumentLoadError("cache_not_found", "Cached document directory was not found")
    metadata = _read_json(document_root / "metadata.json", "metadata_missing")
    cleaned = _read_json(document_root / "cleaned.json", "cleaned_document_missing")
    _validate_metadata(document_id, metadata, cleaned, document_root)
    try:
        sections = [DocumentSection(**section) for section in cleaned["sections"]]
        fetched_at = datetime.fromisoformat(str(cleaned["source_fetched_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CachedDocumentLoadError(
            "unsupported_schema", "Cached cleaned document schema is invalid"
        ) from exc
    if fetched_at.tzinfo is None:
        raise CachedDocumentLoadError("unsupported_schema", "Cached timestamp lacks timezone")
    try:
        return CleanedOfficialDocument(
            document_id=str(cleaned["document_id"]),
            canonical_url=str(cleaned["canonical_url"]),
            final_url=str(cleaned["final_url"]),
            product=str(cleaned["product"]),
            component=str(cleaned["component"]),
            document_type=str(cleaned["document_type"]),
            title=str(cleaned["title"]),
            plain_text=str(cleaned["plain_text"]),
            headings=[str(value) for value in cleaned["headings"]],
            sections=sections,
            source_fetched_at=fetched_at,
            source_response_size_bytes=int(cleaned["source_response_size_bytes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CachedDocumentLoadError(
            "unsupported_schema", "Cached cleaned document is incomplete"
        ) from exc


def _read_json(path: Path, missing_code: str) -> dict[str, Any]:
    if not path.is_file():
        raise CachedDocumentLoadError(missing_code, "Cached document artifact is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CachedDocumentLoadError("invalid_json", "Cached document JSON is invalid") from exc
    if not isinstance(data, dict):
        raise CachedDocumentLoadError(
            "unsupported_schema", "Cached document JSON must be an object"
        )
    return data


def _validate_metadata(
    document_id: str, metadata: dict[str, Any], cleaned: dict[str, Any], document_root: Path
) -> None:
    required = {
        "document_id",
        "canonical_url",
        "final_url",
        "product",
        "component",
        "document_type",
        "cleaned_content_sha256",
        "raw_content_sha256",
        "cleaner_version",
    }
    if not required.issubset(metadata):
        raise CachedDocumentLoadError("unsupported_schema", "Cached metadata is incomplete")
    fields = ("document_id", "canonical_url", "final_url", "product", "component", "document_type")
    if metadata["document_id"] != document_id or any(
        metadata[field] != cleaned.get(field) for field in fields
    ):
        raise CachedDocumentLoadError(
            "metadata_mismatch", "Cached metadata does not match cleaned document"
        )
    cleaned_hash = _sha256(_stable_json_bytes(_cleaned_content(cleaned)))
    if metadata["cleaned_content_sha256"] != cleaned_hash:
        raise CachedDocumentLoadError(
            "checksum_mismatch", "Cached cleaned document checksum does not match"
        )
    raw_path = document_root / "raw.html"
    if raw_path.is_file() and metadata.get("raw_content_sha256") != _sha256(raw_path.read_bytes()):
        raise CachedDocumentLoadError(
            "checksum_mismatch", "Cached raw document checksum does not match"
        )


def _matches(document: CleanedOfficialDocument, request: CachedEvidenceRetrievalRequest) -> bool:
    return (
        (request.product is None or document.product == request.product)
        and (request.component is None or document.component == request.component)
        and (request.document_type is None or document.document_type == request.document_type)
    )


def _cache_directory(cache_root: Path, value: str | None) -> Path:
    if value is None:
        return cache_root
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise CachedDocumentLoadError(
            "cache_read_error", "Cache directory must stay below the configured cache root"
        )
    result = (cache_root / path).resolve()
    try:
        result.relative_to(cache_root)
    except ValueError as exc:
        raise CachedDocumentLoadError(
            "cache_read_error", "Cache directory escapes the configured cache root"
        ) from exc
    return result


def _validate_request(request: CachedEvidenceRetrievalRequest) -> None:
    if request.max_documents <= 0 or request.top_chunks <= 0:
        raise CachedDocumentLoadError(
            "invalid_request", "Document and chunk limits must be positive"
        )


def _stable_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _cleaned_content(cleaned: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in cleaned.items() if key != "source_fetched_at"}


def _sha256(value: bytes) -> str:
    return sha256(value).hexdigest()


def _evidence(result) -> RetrievedOfficialEvidence:
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
        source_fetched_at=chunk.source_fetched_at.astimezone(UTC),
    )
