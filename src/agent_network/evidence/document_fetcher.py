"""Safe, minimal HTTP fetching for configured official document catalogs."""

from __future__ import annotations

import ipaddress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from agent_network.evidence.schemas import DocumentCatalog


@dataclass(slots=True)
class OfficialDocumentFetchRequest:
    url: str
    headers: dict[str, str]
    timeout_seconds: float


class OfficialDocumentStreamResponse(Protocol):
    status_code: int
    url: str
    headers: dict[str, str]

    def read(self, size: int) -> bytes:
        """Read up to size bytes from the response stream."""

    def close(self) -> None:
        """Release the underlying response."""


class OfficialDocumentHttpTransport(Protocol):
    def open(self, request: OfficialDocumentFetchRequest) -> OfficialDocumentStreamResponse:
        """Open one GET request without automatically following redirects."""


@dataclass(slots=True)
class FetchAudit:
    """Safe, serializable accounting for one catalog-bound fetch attempt."""

    network_request_count: int = 0
    cache_hit: bool = False
    cache_miss: bool = True
    rejected_url: bool = False
    rejected_redirect: bool = False
    response_too_large: bool = False
    invalid_content_type: bool = False
    timeout: bool = False
    elapsed_seconds: float = 0.0


@dataclass(slots=True)
class OfficialDocumentFetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    html: str
    fetched_at: datetime
    response_size_bytes: int
    redirect_count: int
    document_id: str = ""
    content_length: int | None = None
    raw_content_hash: str | None = None
    cache_status: str = "miss"
    etag: str | None = None
    last_modified: str | None = None
    body: str | None = None
    success: bool = True
    error_type: str | None = None
    error_message: str | None = None
    audit: FetchAudit = field(default_factory=FetchAudit)

    def __post_init__(self) -> None:
        if self.content_length is None:
            self.content_length = self.response_size_bytes
        if self.body is None:
            self.body = self.html
        if self.raw_content_hash is None:
            self.raw_content_hash = f"sha256:{sha256(self.body.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["fetched_at"] = self.fetched_at.isoformat()
        return data


class OfficialDocumentFetchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _UrllibDocumentResponse:
    def __init__(self, response) -> None:
        self._response = response
        self.status_code = int(response.code)
        self.url = str(response.geturl())
        self.headers = dict(response.headers.items()) if response.headers else {}

    def read(self, size: int) -> bytes:
        return self._response.read(size)

    def close(self) -> None:
        self._response.close()


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibOfficialDocumentTransport:
    """Production transport. Unit tests inject a deterministic fake transport."""

    def open(self, request: OfficialDocumentFetchRequest) -> OfficialDocumentStreamResponse:
        opener = build_opener(_NoRedirectHandler())
        urllib_request = Request(request.url, headers=request.headers, method="GET")
        try:
            return _UrllibDocumentResponse(
                opener.open(urllib_request, timeout=request.timeout_seconds)
            )
        except HTTPError as exc:
            return _UrllibDocumentResponse(exc)
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                raise TimeoutError("Official document request timed out") from exc
            raise OfficialDocumentFetchError(
                "transport_error", "Official document transport failed"
            ) from exc


class HttpOfficialDocumentFetcher:
    """Catalog-bound official document fetcher with strict network limits."""

    def __init__(
        self,
        *,
        allowed_domains: set[str],
        timeout_seconds: float = 20.0,
        maximum_response_bytes: int = 1_000_000,
        maximum_redirects: int = 3,
        user_agent: str = "agent-network-document-fetcher/0.3",
        transport: OfficialDocumentHttpTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or maximum_response_bytes <= 0 or maximum_redirects < 0:
            raise ValueError("document fetcher limits must be positive")
        self.allowed_domains = frozenset(domain.lower().rstrip(".") for domain in allowed_domains)
        self.timeout_seconds = timeout_seconds
        self.maximum_response_bytes = maximum_response_bytes
        self.maximum_redirects = maximum_redirects
        self.user_agent = user_agent
        self.transport = transport or UrllibOfficialDocumentTransport()
        self.network_request_count = 0
        self.model_call_count = 0
        self.last_fetch_audit = FetchAudit()

    def fetch(self, document: DocumentCatalog) -> OfficialDocumentFetchResult:
        started_at = monotonic()
        audit = FetchAudit()
        requested_url = document.canonical_url
        try:
            self._validate_document(document)
            self._validate_url(requested_url)
        except OfficialDocumentFetchError:
            audit.rejected_url = True
            audit.elapsed_seconds = monotonic() - started_at
            self.last_fetch_audit = audit
            raise
        current_url = requested_url
        redirect_count = 0
        try:
            while True:
                self._validate_url(current_url)
                audit.network_request_count += 1
                response = self._open(current_url)
                try:
                    try:
                        self._validate_url(response.url)
                    except OfficialDocumentFetchError:
                        audit.rejected_redirect = True
                        raise
                    if 300 <= response.status_code < 400:
                        location = _header(response.headers, "location")
                        if not location:
                            raise OfficialDocumentFetchError(
                                "http_error", "Redirect response has no location"
                            )
                        if redirect_count >= self.maximum_redirects:
                            raise OfficialDocumentFetchError(
                                "too_many_redirects", "Document redirect limit exceeded"
                            )
                        redirect_count += 1
                        current_url = urljoin(response.url, location)
                        try:
                            self._validate_url(current_url)
                        except OfficialDocumentFetchError:
                            audit.rejected_redirect = True
                            raise
                        continue
                    if response.status_code < 200 or response.status_code >= 300:
                        raise OfficialDocumentFetchError(
                            "http_error", "Document request returned an error status"
                        )
                    content_type = _header(response.headers, "content-type") or ""
                    mime_type, charset = _parse_content_type(content_type)
                    if mime_type not in {"text/html", "application/xhtml+xml"}:
                        audit.invalid_content_type = True
                        raise OfficialDocumentFetchError(
                            "unsupported_content_type", "Document response is not HTML"
                        )
                    body = _read_limited(response, self.maximum_response_bytes)
                    try:
                        html = body.decode(charset)
                    except (LookupError, UnicodeDecodeError) as exc:
                        raise OfficialDocumentFetchError(
                            "decode_error", "Document response could not be decoded"
                        ) from exc
                    audit.elapsed_seconds = monotonic() - started_at
                    self.last_fetch_audit = audit
                    return OfficialDocumentFetchResult(
                        requested_url=requested_url,
                        final_url=response.url,
                        status_code=response.status_code,
                        content_type=content_type,
                        html=html,
                        fetched_at=datetime.now(UTC),
                        response_size_bytes=len(body),
                        redirect_count=redirect_count,
                        document_id=document.document_id,
                        raw_content_hash=f"sha256:{sha256(body).hexdigest()}",
                        etag=_header(response.headers, "etag"),
                        last_modified=_header(response.headers, "last-modified"),
                        audit=audit,
                    )
                finally:
                    response.close()
        except OfficialDocumentFetchError as exc:
            audit.response_too_large = exc.code == "response_too_large"
            audit.timeout = exc.code == "timeout"
            audit.elapsed_seconds = monotonic() - started_at
            self.last_fetch_audit = audit
            raise

    def _validate_document(self, document: DocumentCatalog) -> None:
        if document.official_domain not in self.allowed_domains:
            raise OfficialDocumentFetchError(
                "disallowed_domain", "Catalog domain is not configured for this fetcher"
            )

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        hostname = parsed.hostname.lower().rstrip(".") if parsed.hostname else ""
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or hostname == "localhost"
            or _is_ip_address(hostname)
        ):
            raise OfficialDocumentFetchError("invalid_url", "Document URL is not a safe HTTPS URL")
        if hostname not in self.allowed_domains:
            raise OfficialDocumentFetchError(
                "disallowed_domain", "Document URL domain is not configured"
            )

    def _open(self, url: str) -> OfficialDocumentStreamResponse:
        self.network_request_count += 1
        try:
            return self.transport.open(
                OfficialDocumentFetchRequest(
                    url=url,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "text/html,application/xhtml+xml",
                    },
                    timeout_seconds=self.timeout_seconds,
                )
            )
        except OfficialDocumentFetchError:
            raise
        except TimeoutError as exc:
            raise OfficialDocumentFetchError("timeout", "Document request timed out") from exc
        except Exception as exc:
            raise OfficialDocumentFetchError(
                "transport_error", "Document transport failed"
            ) from exc


def _read_limited(response: OfficialDocumentStreamResponse, maximum_response_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining_with_sentinel = maximum_response_bytes - total + 1
        chunk = response.read(min(64 * 1024, remaining_with_sentinel))
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > maximum_response_bytes:
            raise OfficialDocumentFetchError(
                "response_too_large", "Document response exceeds limit"
            )
        chunks.append(chunk)


def _parse_content_type(content_type: str) -> tuple[str, str]:
    parts = [part.strip() for part in content_type.split(";")]
    mime_type = parts[0].lower()
    for part in parts[1:]:
        key, separator, value = part.partition("=")
        if separator and key.strip().lower() == "charset" and value.strip().strip('"'):
            return mime_type, value.strip().strip('"')
    return mime_type, "utf-8"


def _header(headers: dict[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _is_ip_address(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True
