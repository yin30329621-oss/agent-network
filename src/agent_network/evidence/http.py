"""Whitelisted HTTP access with cache, conditional requests, and sanitized audit."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from time import monotonic, sleep
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from agent_network.evidence.cache import EvidenceCache
from agent_network.evidence.vocabulary import is_allowed_network_domain


@dataclass(slots=True)
class HttpRequest:
    url: str
    headers: dict[str, str]
    timeout_seconds: float


@dataclass(slots=True)
class HttpResponse:
    status: int
    final_url: str
    headers: dict[str, str]
    body: bytes


class HttpTransport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse:
        """Send one HTTP request."""


@dataclass(slots=True)
class SourceRequestAudit:
    source_name: str
    request_url: str
    request_started_at: str
    request_completed_at: str | None = None
    http_status: int | None = None
    cache_status: str = "miss"
    etag: str | None = None
    last_modified: str | None = None
    response_hash: str | None = None
    retry_count: int = 0
    error_type: str | None = None
    error_message: str | None = None
    rate_limit_remaining: str | None = None
    rate_limit_reset: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class HttpFetchResult:
    body: bytes
    audit: SourceRequestAudit


class DomainNotAllowedError(RuntimeError):
    pass


class UrllibTransport:
    """Production transport. Tests inject a fake implementation."""

    def send(self, request: HttpRequest) -> HttpResponse:
        opener = build_opener(_WhitelistedRedirectHandler())
        urllib_request = Request(request.url, headers=request.headers, method="GET")
        try:
            with opener.open(urllib_request, timeout=request.timeout_seconds) as response:
                return HttpResponse(
                    status=int(response.status),
                    final_url=str(response.geturl()),
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as exc:
            return HttpResponse(
                status=int(exc.code),
                final_url=str(exc.geturl()),
                headers=dict(exc.headers.items()) if exc.headers else {},
                body=exc.read() if exc.fp else b"",
            )
        except URLError as exc:
            reason = exc.reason
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                raise TimeoutError("Official evidence request timed out") from exc
            raise RuntimeError("Official evidence request failed") from exc


class _WhitelistedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class EvidenceHttpClient:
    def __init__(
        self,
        *,
        transport: HttpTransport | None = None,
        cache: EvidenceCache | None = None,
        timeout_seconds: float = 20.0,
        cache_ttl_seconds: int = 3600,
        minimum_interval_seconds: float = 0.0,
    ) -> None:
        self.transport = transport or UrllibTransport()
        self.cache = cache or EvidenceCache()
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.minimum_interval_seconds = minimum_interval_seconds
        self.last_audit: SourceRequestAudit | None = None
        self.network_request_count = 0
        self._last_request_time: float | None = None

    def get(
        self,
        *,
        source_name: str,
        query: str,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> HttpFetchResult | None:
        started_at = datetime.now(UTC).isoformat()
        audit = SourceRequestAudit(
            source_name=source_name,
            request_url=url,
            request_started_at=started_at,
        )
        self.last_audit = audit
        request_headers = dict(headers or {})
        secret_values = _secret_header_values(request_headers)
        try:
            _validate_url(url)
            key = self.cache.key_for(source_name, query, url, request_headers)
            cached = self.cache.read(source_name, key)
            if cached and cached.is_fresh:
                audit.cache_status = "hit"
                audit.http_status = cached.http_status
                audit.etag = cached.etag
                audit.last_modified = cached.last_modified
                audit.response_hash = cached.response_hash
                return HttpFetchResult(cached.body, audit)

            audit.cache_status = "stale" if cached else "miss"
            if cached:
                if cached.etag:
                    request_headers["If-None-Match"] = cached.etag
                if cached.last_modified:
                    request_headers["If-Modified-Since"] = cached.last_modified
            self._apply_rate_limit()
            self.network_request_count += 1
            response = self.transport.send(
                HttpRequest(url=url, headers=request_headers, timeout_seconds=self.timeout_seconds)
            )
            _validate_url(response.final_url)
            audit.http_status = response.status
            audit.rate_limit_remaining = _header(response.headers, "x-ratelimit-remaining")
            audit.rate_limit_reset = _header(response.headers, "x-ratelimit-reset")
            if response.status == 304 and cached:
                refreshed = self.cache.revalidate(cached, self.cache_ttl_seconds)
                audit.cache_status = "revalidated"
                _apply_cache_audit(audit, refreshed)
                return HttpFetchResult(refreshed.body, audit)
            if response.status == 429:
                raise RuntimeError("rate_limit")
            if response.status >= 500:
                raise RuntimeError("server_error")
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"http_error_{response.status}")
            record = self.cache.write(
                source=source_name,
                key=key,
                query=query,
                request_url=url,
                body=response.body,
                http_status=response.status,
                etag=_header(response.headers, "etag"),
                last_modified=_header(response.headers, "last-modified"),
                ttl_seconds=self.cache_ttl_seconds,
            )
            _apply_cache_audit(audit, record)
            return HttpFetchResult(record.body, audit)
        except Exception as exc:
            audit.error_type = _error_type(exc, audit.http_status)
            audit.error_message = _sanitize_error(exc, secret_values)
            return None
        finally:
            audit.request_completed_at = datetime.now(UTC).isoformat()

    def _apply_rate_limit(self) -> None:
        now = monotonic()
        if self._last_request_time is not None and self.minimum_interval_seconds > 0:
            remaining = self.minimum_interval_seconds - (now - self._last_request_time)
            if remaining > 0:
                sleep(remaining)
        self._last_request_time = monotonic()


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not is_allowed_network_domain(parsed.hostname)
    ):
        raise DomainNotAllowedError("Evidence request domain is not allowed")


def _header(headers: dict[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _apply_cache_audit(audit: SourceRequestAudit, record) -> None:
    audit.etag = record.etag
    audit.last_modified = record.last_modified
    audit.response_hash = record.response_hash


def _secret_header_values(headers: dict[str, str]) -> list[str]:
    values: list[str] = []
    for key, value in headers.items():
        if key.lower() not in {"authorization", "apikey", "api-key", "x-api-key"} or not value:
            continue
        values.append(value)
        if key.lower() == "authorization" and " " in value:
            values.append(value.split(" ", 1)[1])
    return values


def _sanitize_error(exc: Exception, secret_values: list[str]) -> str:
    message = str(exc)
    for value in secret_values:
        message = message.replace(value, "[REDACTED]")
    return message[:500]


def _error_type(exc: Exception, status: int | None) -> str:
    if isinstance(exc, DomainNotAllowedError):
        return "domain_not_allowed"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if status == 429 or str(exc) == "rate_limit":
        return "rate_limit"
    if status is not None and status >= 500:
        return "server_error"
    return "http_error"
