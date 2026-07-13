from dataclasses import dataclass, field

import pytest

from agent_network.evidence.document_fetcher import (
    HttpOfficialDocumentFetcher,
    OfficialDocumentFetchError,
    OfficialDocumentFetchRequest,
)
from agent_network.evidence.schemas import DocumentCatalog


RANCHER_DOMAIN = "ranchermanager.docs.rancher.com"
FLEET_DOMAIN = "fleet.rancher.io"
ALLOWED_DOMAINS = {RANCHER_DOMAIN, "rancher.com", FLEET_DOMAIN}


@dataclass
class FakeStreamResponse:
    status_code: int
    url: str
    headers: dict[str, str]
    body: bytes = b""
    offset: int = 0
    read_sizes: list[int] = field(default_factory=list)
    closed: bool = False

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeTransport:
    responses: list[FakeStreamResponse | Exception]
    calls: list[OfficialDocumentFetchRequest] = field(default_factory=list)

    def open(self, request: OfficialDocumentFetchRequest) -> FakeStreamResponse:
        self.calls.append(request)
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def document(url: str = f"https://{RANCHER_DOMAIN}/fixture/page") -> DocumentCatalog:
    return DocumentCatalog.model_construct(
        document_id="document-fetcher-test",
        source_name="rancher",
        title="Fixture document",
        canonical_url=url,
        official_domain=RANCHER_DOMAIN,
        document_type="reference",
        product="Rancher Manager",
    )


def html_response(
    *,
    status_code: int = 200,
    url: str = f"https://{RANCHER_DOMAIN}/fixture/page",
    body: bytes = b"<html>ok</html>",
    content_type: str = "text/html; charset=utf-8",
    headers: dict[str, str] | None = None,
) -> FakeStreamResponse:
    response_headers = {"Content-Type": content_type}
    response_headers.update(headers or {})
    return FakeStreamResponse(status_code, url, response_headers, body)


def fetcher(transport: FakeTransport, **overrides) -> HttpOfficialDocumentFetcher:
    options = {
        "timeout_seconds": 7,
        "maximum_response_bytes": 100,
        "maximum_redirects": 2,
        "user_agent": "agent-network-test-fetcher/1.0",
    }
    options.update(overrides)
    return HttpOfficialDocumentFetcher(
        allowed_domains=ALLOWED_DOMAINS,
        transport=transport,
        **options,
    )


def test_successful_html_fetch_returns_serializable_result() -> None:
    transport = FakeTransport([html_response()])
    subject = fetcher(transport)

    result = subject.fetch(document())

    assert result.html == "<html>ok</html>"
    assert result.response_size_bytes == len(b"<html>ok</html>")
    assert result.redirect_count == 0
    assert result.to_dict()["fetched_at"].endswith("+00:00")
    assert transport.calls[0].headers["User-Agent"] == "agent-network-test-fetcher/1.0"
    assert transport.calls[0].timeout_seconds == 7
    assert subject.network_request_count == 1
    assert subject.model_call_count == 0


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("http://ranchermanager.docs.rancher.com/page", "invalid_url"),
        ("https://localhost/page", "invalid_url"),
        ("https://127.0.0.1/page", "invalid_url"),
        ("https://user:password@ranchermanager.docs.rancher.com/page", "invalid_url"),
        ("https://evil-rancher.com/page", "disallowed_domain"),
    ],
)
def test_unsafe_urls_are_rejected_before_network(url: str, code: str) -> None:
    transport = FakeTransport([html_response()])
    subject = fetcher(transport)

    with pytest.raises(OfficialDocumentFetchError) as error:
        subject.fetch(document(url))

    assert error.value.code == code
    assert subject.network_request_count == 0
    assert transport.calls == []


def test_allowed_cross_domain_redirect_counts_each_request() -> None:
    first = html_response(
        status_code=302,
        headers={"Location": f"https://{FLEET_DOMAIN}/fixture/redirected"},
    )
    second = html_response(url=f"https://{FLEET_DOMAIN}/fixture/redirected")
    transport = FakeTransport([first, second])
    subject = fetcher(transport)

    result = subject.fetch(document())

    assert result.final_url == f"https://{FLEET_DOMAIN}/fixture/redirected"
    assert result.redirect_count == 1
    assert subject.network_request_count == 2
    assert first.closed is True and second.closed is True


def test_disallowed_redirect_is_rejected_after_first_request() -> None:
    transport = FakeTransport(
        [html_response(status_code=302, headers={"Location": "https://evil-rancher.com/page"})]
    )
    subject = fetcher(transport)

    with pytest.raises(OfficialDocumentFetchError) as error:
        subject.fetch(document())

    assert error.value.code == "disallowed_domain"
    assert subject.network_request_count == 1


def test_redirect_limit_is_enforced() -> None:
    transport = FakeTransport(
        [
            html_response(status_code=302, headers={"Location": "/one"}),
            html_response(status_code=302, headers={"Location": "/two"}),
        ]
    )
    subject = fetcher(transport, maximum_redirects=1)

    with pytest.raises(OfficialDocumentFetchError) as error:
        subject.fetch(document())

    assert error.value.code == "too_many_redirects"
    assert subject.network_request_count == 2


@pytest.mark.parametrize("status_code", [404, 500])
def test_http_error_statuses_are_rejected(status_code: int) -> None:
    subject = fetcher(FakeTransport([html_response(status_code=status_code)]))

    with pytest.raises(OfficialDocumentFetchError) as error:
        subject.fetch(document())

    assert error.value.code == "http_error"
    assert subject.network_request_count == 1


def test_timeout_and_transport_errors_are_classified() -> None:
    timeout_fetcher = fetcher(FakeTransport([TimeoutError("timed out")]))
    with pytest.raises(OfficialDocumentFetchError) as timeout_error:
        timeout_fetcher.fetch(document())
    assert timeout_error.value.code == "timeout"

    transport_fetcher = fetcher(FakeTransport([RuntimeError("connection failed")]))
    with pytest.raises(OfficialDocumentFetchError) as transport_error:
        transport_fetcher.fetch(document())
    assert transport_error.value.code == "transport_error"


def test_content_type_size_and_charset_handling() -> None:
    non_html = fetcher(FakeTransport([html_response(content_type="application/json")]))
    with pytest.raises(OfficialDocumentFetchError) as content_error:
        non_html.fetch(document())
    assert content_error.value.code == "unsupported_content_type"

    exact = fetcher(FakeTransport([html_response(body=b"12345")]), maximum_response_bytes=5)
    assert exact.fetch(document()).response_size_bytes == 5

    large_response = html_response(body=b"0123456789")
    large = fetcher(FakeTransport([large_response]), maximum_response_bytes=5)
    with pytest.raises(OfficialDocumentFetchError) as size_error:
        large.fetch(document())
    assert size_error.value.code == "response_too_large"
    assert large_response.offset == 6

    latin = fetcher(
        FakeTransport(
            [
                html_response(
                    body="caf\xe9".encode("latin-1"), content_type="text/html; charset=latin-1"
                )
            ]
        )
    )
    assert latin.fetch(document()).html == "caf\xe9"


def test_decode_error_and_no_model_calls() -> None:
    subject = fetcher(FakeTransport([html_response(body=b"\xff", content_type="text/html")]))

    with pytest.raises(OfficialDocumentFetchError) as error:
        subject.fetch(document())

    assert error.value.code == "decode_error"
    assert subject.model_call_count == 0
