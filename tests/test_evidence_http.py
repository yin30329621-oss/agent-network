from dataclasses import dataclass

import pytest

from agent_network.evidence.cache import EvidenceCache
from agent_network.evidence.http import EvidenceHttpClient, HttpRequest, HttpResponse


NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2022-45157"


@dataclass
class FakeTransport:
    responses: list[HttpResponse | Exception]

    def __post_init__(self) -> None:
        self.calls: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.calls.append(request)
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def response(
    status: int = 200,
    *,
    body: bytes = b'{"ok":true}',
    final_url: str = NVD_URL,
    headers: dict[str, str] | None = None,
) -> HttpResponse:
    return HttpResponse(status=status, final_url=final_url, headers=headers or {}, body=body)


def client(tmp_path, transport, ttl=3600) -> EvidenceHttpClient:
    return EvidenceHttpClient(
        transport=transport,
        cache=EvidenceCache(tmp_path / "cache"),
        cache_ttl_seconds=ttl,
    )


def fetch(http: EvidenceHttpClient, headers=None):
    return http.get(
        source_name="nvd",
        query="CVE-2022-45157",
        url=NVD_URL,
        headers=headers or {"Accept": "application/json"},
    )


def test_cache_miss_then_hit_and_response_hash(tmp_path) -> None:
    transport = FakeTransport([response(headers={"ETag": '"abc"'})])
    http = client(tmp_path, transport)

    first = fetch(http)
    assert first is not None
    assert first.audit.cache_status == "miss"
    assert first.audit.response_hash.startswith("sha256:")
    second = fetch(http)

    assert second is not None
    assert second.audit.cache_status == "hit"
    assert second.audit.response_hash == first.audit.response_hash
    assert len(transport.calls) == 1


def test_stale_cache_fetches_again(tmp_path) -> None:
    transport = FakeTransport([response(body=b"first"), response(body=b"second")])
    http = client(tmp_path, transport, ttl=-1)

    fetch(http)
    second = fetch(http)

    assert second is not None
    assert second.audit.cache_status == "stale"
    assert second.body == b"second"
    assert len(transport.calls) == 2


def test_etag_and_last_modified_revalidation(tmp_path) -> None:
    transport = FakeTransport(
        [
            response(headers={"ETag": '"abc"', "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"}),
            response(status=304, body=b""),
        ]
    )
    http = client(tmp_path, transport, ttl=-1)

    first = fetch(http)
    second = fetch(http)

    assert first is not None and second is not None
    assert second.audit.cache_status == "revalidated"
    assert second.body == first.body
    assert transport.calls[1].headers["If-None-Match"] == '"abc"'
    assert "If-Modified-Since" in transport.calls[1].headers


@pytest.mark.parametrize(
    ("transport_response", "expected_error"),
    [
        (TimeoutError("timed out"), "timeout"),
        (response(status=429, headers={"X-RateLimit-Remaining": "0"}), "rate_limit"),
        (response(status=500), "server_error"),
    ],
)
def test_http_errors_are_audited(tmp_path, transport_response, expected_error) -> None:
    http = client(tmp_path, FakeTransport([transport_response]))

    result = fetch(http)

    assert result is None
    assert http.last_audit.error_type == expected_error
    assert http.last_audit.retry_count == 0
    if expected_error == "rate_limit":
        assert http.last_audit.rate_limit_remaining == "0"


def test_non_whitelisted_domain_is_rejected_without_transport(tmp_path) -> None:
    transport = FakeTransport([response()])
    http = client(tmp_path, transport)

    result = http.get(
        source_name="nvd",
        query="CVE-2022-45157",
        url="https://example.com/not-allowed",
    )

    assert result is None
    assert http.last_audit.error_type == "domain_not_allowed"
    assert transport.calls == []


def test_non_whitelisted_redirect_target_is_rejected(tmp_path) -> None:
    transport = FakeTransport([response(final_url="https://evil.example/redirect")])
    http = client(tmp_path, transport)

    result = fetch(http)

    assert result is None
    assert http.last_audit.error_type == "domain_not_allowed"


def test_secret_header_values_are_redacted_from_errors(tmp_path) -> None:
    token = "top-secret-token"
    transport = FakeTransport([RuntimeError(f"request failed for {token}")])
    http = client(tmp_path, transport)

    result = fetch(http, headers={"Authorization": f"Bearer {token}"})

    assert result is None
    assert token not in http.last_audit.error_message


def test_nvd_api_key_is_redacted_from_errors(tmp_path) -> None:
    api_key = "nvd-secret-key"
    transport = FakeTransport([RuntimeError(f"request failed for {api_key}")])
    http = client(tmp_path, transport)

    result = fetch(http, headers={"apiKey": api_key})

    assert result is None
    assert api_key not in http.last_audit.error_message
