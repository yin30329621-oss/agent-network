"""Read-only evidence retrieval from synchronized official document cache entries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
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
    min_score: float = 0.0
    min_matched_terms: int = 1
    exclude_navigation_like: bool = False


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
    candidate_evidence_count: int
    returned_evidence_count: int
    filtered_evidence_count: int
    filtered_reasons_summary: dict[str, int]
    network_request_count: int
    evidences: list[RetrievedOfficialEvidence]
    cache_failures: list[CachedDocumentFailure]

    def to_dict(self) -> dict[str, object]:
        return {
            "loaded_document_count": self.loaded_document_count,
            "failed_document_count": self.failed_document_count,
            "total_chunk_count": self.total_chunk_count,
            "candidate_evidence_count": self.candidate_evidence_count,
            "returned_evidence_count": self.returned_evidence_count,
            "filtered_evidence_count": self.filtered_evidence_count,
            "filtered_reasons_summary": self.filtered_reasons_summary,
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
                loaded_document_count=len(loaded.documents),
                failed_document_count=len(failures),
                total_chunk_count=0,
                candidate_evidence_count=0,
                returned_evidence_count=0,
                filtered_evidence_count=0,
                filtered_reasons_summary={},
                network_request_count=0,
                evidences=[],
                cache_failures=failures,
            )
        results = OfficialDocumentBm25Index(chunks).search(
            Bm25SearchQuery(
                query_text=request.query_text,
                top_k=len(chunks),
                product=request.product,
                component=request.component,
                document_type=request.document_type,
                document_id=request.document_id,
            )
        )
        evidences, filtered_reasons = _filter_evidences(results, request)
        return CachedEvidenceRetrievalResult(
            loaded_document_count=len(loaded.documents),
            failed_document_count=len(failures),
            total_chunk_count=len(chunks),
            candidate_evidence_count=len(results),
            returned_evidence_count=len(evidences),
            filtered_evidence_count=sum(filtered_reasons.values()),
            filtered_reasons_summary=filtered_reasons,
            network_request_count=0,
            evidences=evidences,
            cache_failures=failures,
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
    if (
        request.max_documents <= 0
        or request.top_chunks <= 0
        or request.min_score < 0
        or request.min_matched_terms <= 0
    ):
        raise CachedDocumentLoadError(
            "invalid_request", "Document limits and quality thresholds are invalid"
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


def _filter_evidences(
    results: list, request: CachedEvidenceRetrievalRequest
) -> tuple[list[RetrievedOfficialEvidence], dict[str, int]]:
    reasons: dict[str, int] = {}
    selected: list[RetrievedOfficialEvidence] = []
    seen_chunk_ids: set[str] = set()
    for result in results:
        reason = _filtered_reason(result, request)
        if reason is not None:
            reasons[reason] = reasons.get(reason, 0) + 1
            continue
        if result.chunk.chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(result.chunk.chunk_id)
        selected.append(_evidence(result))
    selected = selected[: request.top_chunks]
    return [
        replace(evidence, rank=rank) for rank, evidence in enumerate(selected, start=1)
    ], reasons


def _filtered_reason(result, request: CachedEvidenceRetrievalRequest) -> str | None:
    if result.score < request.min_score:
        return "below_min_score"
    if len(result.matched_terms) < request.min_matched_terms:
        return "below_min_matched_terms"
    if request.exclude_navigation_like and _is_navigation_like_chunk(result.chunk):
        return "navigation_like"
    return None


def _is_navigation_like_chunk(chunk: DocumentChunk) -> bool:
    marker_text = f"{chunk.section_heading}\n{chunk.text}".lower()
    markers = ("on this page", "table of contents", "本页目录")
    lines = [line.strip() for line in chunk.text.splitlines() if line.strip()]
    list_lines = [line for line in lines if _is_list_line(line)]
    if len(list_lines) < 3 or len(list_lines) * 2 < len(lines):
        return False
    if any(marker in marker_text for marker in markers):
        return _mostly_short_names(list_lines)

    explanatory_lines = sum(_is_explanatory_line(line) for line in lines)
    if explanatory_lines > max(1, len(lines) // 3):
        return False
    if not _mostly_short_names(list_lines):
        return False
    protected_items = sum(_is_action_or_permission_item(line) for line in list_lines)
    return protected_items / len(list_lines) < 0.4


_LIST_LINE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_ACTION_PREFIX = re.compile(
    r"^(?:install|configure|create|update|run|check|verify|use|set|apply|delete|allow|deny|grant|bind|authenticate|connect|deploy)\b",
    re.I,
)


def _is_list_line(line: str) -> bool:
    return bool(_LIST_LINE.match(line))


def _list_item_text(line: str) -> str:
    return _LIST_LINE.sub("", line).strip()


def _mostly_short_names(lines: list[str]) -> bool:
    names = [_list_item_text(line) for line in lines]
    short_names = [
        name for name in names if len(name) <= 80 and not re.search(r"[.!?。！？;；]$", name)
    ]
    return len(short_names) / len(names) >= 0.75


def _is_explanatory_line(line: str) -> bool:
    text = _list_item_text(line) if _is_list_line(line) else line
    words = re.findall(r"[A-Za-z0-9]+", text)
    return (
        bool(re.search(r"[.!?。！？;；]$", text))
        or len(words) >= 10
        or bool(re.match(r"^(?:the|a|an|each|this|these)\b", text, re.I))
    )


def _is_action_or_permission_item(line: str) -> bool:
    text = _list_item_text(line)
    if _ACTION_PREFIX.match(text):
        return True
    return bool(
        re.search(
            r"\b(?:permission|permissions|role|roles|access|allow|deny|must|required|can)\b",
            text,
            re.I,
        )
    )
