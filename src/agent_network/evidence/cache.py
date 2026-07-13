"""Content-addressed local cache for official evidence API responses."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

SENSITIVE_HEADER_NAMES = {"authorization", "apikey", "api-key", "x-api-key"}


@dataclass(slots=True)
class CacheRecord:
    key: str
    source: str
    query: str
    request_url: str
    fetched_at: datetime
    expires_at: datetime
    etag: str | None
    last_modified: str | None
    response_hash: str
    http_status: int
    raw_response_path: Path
    body: bytes

    @property
    def is_fresh(self) -> bool:
        return datetime.now(UTC) < self.expires_at


class EvidenceCache:
    def __init__(self, root: str | Path = ".cache/agent-network/evidence") -> None:
        self.root = Path(root)

    def key_for(self, source: str, query: str, request_url: str, headers: dict[str, str]) -> str:
        relevant_headers = {
            key.lower(): value
            for key, value in headers.items()
            if key.lower() not in SENSITIVE_HEADER_NAMES
        }
        payload = json.dumps(
            {
                "source": source,
                "query": query,
                "request_url": request_url,
                "headers": relevant_headers,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def read(self, source: str, key: str) -> CacheRecord | None:
        metadata_path = self.root / source / f"{key}.json"
        if not metadata_path.exists():
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        raw_path = self.root / source / metadata["raw_response_path"]
        if not raw_path.exists():
            return None
        body = raw_path.read_bytes()
        response_hash = _response_hash(body)
        if response_hash != metadata["response_hash"]:
            return None
        return CacheRecord(
            key=key,
            source=source,
            query=str(metadata["query"]),
            request_url=str(metadata["request_url"]),
            fetched_at=datetime.fromisoformat(metadata["fetched_at"]),
            expires_at=datetime.fromisoformat(metadata["expires_at"]),
            etag=metadata.get("etag"),
            last_modified=metadata.get("last_modified"),
            response_hash=response_hash,
            http_status=int(metadata["http_status"]),
            raw_response_path=raw_path,
            body=body,
        )

    def write(
        self,
        *,
        source: str,
        key: str,
        query: str,
        request_url: str,
        body: bytes,
        http_status: int,
        etag: str | None,
        last_modified: str | None,
        ttl_seconds: int,
    ) -> CacheRecord:
        source_dir = self.root / source
        source_dir.mkdir(parents=True, exist_ok=True)
        raw_name = f"{key}.body"
        raw_path = source_dir / raw_name
        raw_path.write_bytes(body)
        fetched_at = datetime.now(UTC)
        expires_at = fetched_at + timedelta(seconds=ttl_seconds)
        response_hash = _response_hash(body)
        metadata = {
            "source": source,
            "query": query,
            "request_url": request_url,
            "fetched_at": fetched_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "etag": etag,
            "last_modified": last_modified,
            "response_hash": response_hash,
            "http_status": http_status,
            "raw_response_path": raw_name,
        }
        (source_dir / f"{key}.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return CacheRecord(
            key=key,
            source=source,
            query=query,
            request_url=request_url,
            fetched_at=fetched_at,
            expires_at=expires_at,
            etag=etag,
            last_modified=last_modified,
            response_hash=response_hash,
            http_status=http_status,
            raw_response_path=raw_path,
            body=body,
        )

    def revalidate(self, record: CacheRecord, ttl_seconds: int) -> CacheRecord:
        return self.write(
            source=record.source,
            key=record.key,
            query=record.query,
            request_url=record.request_url,
            body=record.body,
            http_status=record.http_status,
            etag=record.etag,
            last_modified=record.last_modified,
            ttl_seconds=ttl_seconds,
        )


def _response_hash(body: bytes) -> str:
    return f"sha256:{sha256(body).hexdigest()}"
