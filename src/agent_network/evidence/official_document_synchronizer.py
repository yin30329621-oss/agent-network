"""Catalog-bound, auditable synchronization of official document cache entries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any
from uuid import uuid4

from agent_network.evidence.catalog import DocumentCatalogQuery, DocumentCatalogRepository
from agent_network.evidence.document_cleaner import OfficialDocumentCleaner
from agent_network.evidence.document_fetcher import HttpOfficialDocumentFetcher
from agent_network.evidence.schemas import DocumentCatalog


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIRECTORY = PROJECT_ROOT / "data" / "official-evidence-cache"
_SAFE_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SYNC_SCHEMA_VERSION = "1"


class DocumentSyncError(RuntimeError):
    """Safe, categorical synchronization or cache error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class OfficialDocumentSyncRequest:
    product: str | None = None
    component: str | None = None
    document_id: str | None = None
    official_domain: str | None = None
    max_documents: int = 20
    force_refresh: bool = False
    allow_network: bool = False
    cache_directory: str | None = None


@dataclass(slots=True)
class DocumentSyncRecord:
    document_id: str
    canonical_url: str
    sync_status: str
    network_request_count: int
    error_stage: str | None = None
    error_code: str | None = None
    safe_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class OfficialDocumentSyncResult:
    catalog_match_count: int
    selected_document_count: int
    fetched_count: int
    unchanged_count: int
    skipped_count: int
    failed_count: int
    network_request_count: int
    records: list[DocumentSyncRecord]
    started_at: datetime
    completed_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "records": [record.to_dict() for record in self.records],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
        }


class OfficialDocumentCache:
    """File cache with staged, document-directory replacement."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.documents_root = self.root / "documents"

    def metadata(self, document_id: str) -> dict[str, Any] | None:
        path = self._document_directory(document_id) / "metadata.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DocumentSyncError(
                "cache_read_error", "Cached document metadata is invalid"
            ) from exc
        return data if isinstance(data, dict) else None

    def write(
        self, document_id: str, *, raw_html: str, cleaned: dict[str, Any], metadata: dict[str, Any]
    ) -> None:
        target = self._document_directory(document_id)
        self.documents_root.mkdir(parents=True, exist_ok=True)
        staged = self.documents_root / f".{document_id}.staging-{uuid4().hex}"
        backup = self.documents_root / f".{document_id}.backup-{uuid4().hex}"
        try:
            staged.mkdir()
            _atomic_write(staged / "raw.html", raw_html.encode("utf-8"))
            _atomic_write(staged / "cleaned.json", _stable_json_bytes(cleaned))
            _atomic_write(staged / "metadata.json", _stable_json_bytes(metadata))
            self._activate(staged, target, backup)
        except Exception:
            shutil.rmtree(staged, ignore_errors=True)
            if backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        else:
            shutil.rmtree(backup, ignore_errors=True)

    def _activate(self, staged: Path, target: Path, backup: Path) -> None:
        if target.exists():
            os.replace(target, backup)
        try:
            os.replace(staged, target)
        except Exception:
            if backup.exists() and not target.exists():
                os.replace(backup, target)
            raise

    def _document_directory(self, document_id: str) -> Path:
        if not _SAFE_DOCUMENT_ID.fullmatch(document_id):
            raise DocumentSyncError(
                "invalid_document_id", "Catalog document ID is not safe for cache storage"
            )
        target = (self.documents_root / document_id).resolve()
        try:
            target.relative_to(self.documents_root.resolve())
        except ValueError as exc:
            raise DocumentSyncError(
                "invalid_cache_path", "Cache path escapes the documents directory"
            ) from exc
        return target


class OfficialDocumentSynchronizer:
    """Synchronize only validated catalog URLs; network access is opt-in."""

    def __init__(
        self,
        repository: DocumentCatalogRepository,
        fetcher: HttpOfficialDocumentFetcher,
        cleaner: OfficialDocumentCleaner,
        *,
        cache_root: Path = DEFAULT_CACHE_DIRECTORY,
    ) -> None:
        self.repository = repository
        self.fetcher = fetcher
        self.cleaner = cleaner
        self.cache_root = cache_root.resolve()
        self.network_request_count = 0
        self.model_call_count = 0

    def sync(self, request: OfficialDocumentSyncRequest) -> OfficialDocumentSyncResult:
        if request.max_documents <= 0:
            raise DocumentSyncError("invalid_request", "max_documents must be positive")
        cache = OfficialDocumentCache(self._cache_directory(request.cache_directory))
        started_at = datetime.now(UTC)
        candidates = self.repository.query(
            DocumentCatalogQuery(
                product=request.product,
                component=request.component,
                official_domain=request.official_domain,
            )
        )
        if request.document_id is not None:
            candidates = [item for item in candidates if item.document_id == request.document_id]
        selected = candidates[: request.max_documents]
        records: list[DocumentSyncRecord] = []
        before = self.fetcher.network_request_count
        for document in selected:
            record = self._sync_document(document, request, cache)
            records.append(record)
        network_count = self.fetcher.network_request_count - before
        self.network_request_count += network_count
        return OfficialDocumentSyncResult(
            catalog_match_count=len(candidates),
            selected_document_count=len(selected),
            fetched_count=sum(record.sync_status == "fetched" for record in records),
            unchanged_count=sum(record.sync_status == "unchanged" for record in records),
            skipped_count=sum(record.sync_status == "skipped" for record in records),
            failed_count=sum(record.sync_status == "failed" for record in records),
            network_request_count=network_count,
            records=records,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )

    def _sync_document(
        self,
        document: DocumentCatalog,
        request: OfficialDocumentSyncRequest,
        cache: OfficialDocumentCache,
    ) -> DocumentSyncRecord:
        before = self.fetcher.network_request_count
        try:
            previous = cache.metadata(document.document_id)
            if previous is not None and not request.force_refresh:
                return DocumentSyncRecord(
                    document.document_id, document.canonical_url, "skipped", 0
                )
            if not request.allow_network:
                raise DocumentSyncError(
                    "network_disabled", "Network access is disabled for uncached documents"
                )
            fetched = self.fetcher.fetch(document)
            network_count = self.fetcher.network_request_count - before
            cleaned = self.cleaner.clean(fetched, document).to_dict()
            raw_hash = _sha256(fetched.html.encode("utf-8"))
            cleaned_hash = _sha256(_stable_json_bytes(_cleaned_content(cleaned)))
            if (
                previous is not None
                and previous.get("raw_content_sha256") == raw_hash
                and previous.get("cleaned_content_sha256") == cleaned_hash
            ):
                status = "unchanged"
            else:
                status = "fetched"
            metadata = _metadata(document, fetched, raw_hash, cleaned_hash, status)
            cache.write(
                document.document_id, raw_html=fetched.html, cleaned=cleaned, metadata=metadata
            )
            return DocumentSyncRecord(
                document.document_id, document.canonical_url, status, network_count
            )
        except Exception as exc:
            return DocumentSyncRecord(
                document.document_id,
                document.canonical_url,
                "failed",
                self.fetcher.network_request_count - before,
                error_stage=_error_stage(exc),
                error_code=getattr(exc, "code", type(exc).__name__),
                safe_message=_safe_message(exc),
            )

    def _cache_directory(self, requested: str | None) -> Path:
        if requested is None:
            return self.cache_root
        path = Path(requested)
        if path.is_absolute() or ".." in path.parts:
            raise DocumentSyncError(
                "invalid_cache_path", "Cache directory must stay below the configured cache root"
            )
        resolved = (self.cache_root / path).resolve()
        try:
            resolved.relative_to(self.cache_root)
        except ValueError as exc:
            raise DocumentSyncError(
                "invalid_cache_path", "Cache directory escapes the configured cache root"
            ) from exc
        return resolved


def _metadata(
    document: DocumentCatalog,
    fetched,
    raw_hash: str,
    cleaned_hash: str,
    sync_status: str,
) -> dict[str, Any]:
    return {
        "document_id": document.document_id,
        "canonical_url": document.canonical_url,
        "final_url": fetched.final_url,
        "product": document.product,
        "component": document.components[0] if document.components else "",
        "document_type": document.document_type.value,
        "fetched_at": fetched.fetched_at.isoformat(),
        "synced_at": datetime.now(UTC).isoformat(),
        "status_code": fetched.status_code,
        "content_type": fetched.content_type,
        "response_size_bytes": fetched.response_size_bytes,
        "raw_content_sha256": raw_hash,
        "cleaned_content_sha256": cleaned_hash,
        "etag": None,
        "last_modified": None,
        "cleaner_version": _SYNC_SCHEMA_VERSION,
        "sync_status": sync_status,
    }


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid4().hex}")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _stable_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return sha256(value).hexdigest()


def _cleaned_content(cleaned: dict[str, Any]) -> dict[str, Any]:
    """Exclude fetch-time audit data from the deterministic cleaned-content digest."""
    return {key: value for key, value in cleaned.items() if key != "source_fetched_at"}


def _error_stage(error: Exception) -> str:
    code = getattr(error, "code", "")
    if code in {
        "network_disabled",
        "timeout",
        "http_error",
        "transport_error",
        "invalid_url",
        "disallowed_domain",
    }:
        return "fetch"
    if code in {
        "empty_html",
        "input_too_large",
        "no_extractable_content",
        "invalid_html",
        "cleaning_error",
    }:
        return "clean"
    if (
        code.startswith("cache_")
        or code.startswith("invalid_cache")
        or code == "invalid_document_id"
    ):
        return "cache"
    return "sync"


def _safe_message(error: Exception) -> str:
    if isinstance(error, DocumentSyncError):
        return str(error)
    return "Official document synchronization failed"
