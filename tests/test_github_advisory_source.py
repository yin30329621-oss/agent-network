import json

from agent_network.evidence.cache import EvidenceCache
from agent_network.evidence.github_advisory import GitHubAdvisoryEvidenceSource
from agent_network.evidence.http import EvidenceHttpClient, HttpRequest, HttpResponse
from agent_network.evidence.pilot import public_cve_claim


class StubTransport:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return HttpResponse(
            status=200,
            final_url=request.url,
            headers={"X-RateLimit-Remaining": "59", "X-RateLimit-Reset": "12345"},
            body=json.dumps(self.payload).encode(),
        )


def github_payload() -> list[dict]:
    return [
        {
            "ghsa_id": "GHSA-aaaa-bbbb-cccc",
            "cve_id": "CVE-2022-45157",
            "url": "https://api.github.com/advisories/GHSA-aaaa-bbbb-cccc",
            "html_url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
            "summary": "Public fixture advisory summary",
            "description": "Public fixture advisory description.",
            "severity": "high",
            "published_at": "2022-11-10T10:00:00Z",
            "updated_at": "2024-01-02T12:30:00Z",
            "cvss": {
                "vector_string": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
                "score": 8.8,
            },
            "cwes": [{"cwe_id": "CWE-79", "name": "Improper Neutralization"}],
            "vulnerabilities": [
                {
                    "package": {"ecosystem": "GO", "name": "example/module"},
                    "vulnerable_version_range": "< 1.2.3",
                    "first_patched_version": {"identifier": "1.2.3"},
                }
            ],
            "references": [{"url": "https://nvd.nist.gov/vuln/detail/CVE-2022-45157"}],
        }
    ]


def test_github_advisory_maps_complete_metadata_without_token(tmp_path) -> None:
    transport = StubTransport(github_payload())
    http = EvidenceHttpClient(
        transport=transport,
        cache=EvidenceCache(tmp_path / "cache"),
    )
    source = GitHubAdvisoryEvidenceSource(http)

    evidence = source.search(public_cve_claim("CVE-2022-45157"))

    assert len(evidence) == 1
    item = evidence[0]
    assert item.evidence_id == "github-ghsa-aaaa-bbbb-cccc"
    assert item.official_domain == "github.com"
    assert item.source_metadata["ghsa_id"] == "GHSA-aaaa-bbbb-cccc"
    assert item.source_metadata["severity"] == "high"
    assert item.source_metadata["cvss"]["score"] == 8.8
    assert item.source_metadata["cwes"][0]["cwe_id"] == "CWE-79"
    assert item.source_metadata["vulnerabilities"][0] == {
        "ecosystem": "GO",
        "package": "example/module",
        "vulnerable_version_range": "< 1.2.3",
        "first_patched_version": "1.2.3",
    }
    assert "Authorization" not in transport.requests[0].headers
    assert source.last_audit.rate_limit_remaining == "59"


def test_github_token_is_sent_but_never_recorded_in_audit(tmp_path) -> None:
    token = "github-secret-token"
    transport = StubTransport(github_payload())
    http = EvidenceHttpClient(
        transport=transport,
        cache=EvidenceCache(tmp_path / "cache"),
    )
    source = GitHubAdvisoryEvidenceSource(http, token=token)

    source.search(public_cve_claim("CVE-2022-45157"))
    audit = json.dumps(source.last_audit.to_dict())

    assert transport.requests[0].headers["Authorization"] == f"Bearer {token}"
    assert token not in audit
    assert "authorization" not in audit.lower()


def test_github_no_advisory_returns_empty(tmp_path) -> None:
    transport = StubTransport([])
    source = GitHubAdvisoryEvidenceSource(
        EvidenceHttpClient(
            transport=transport,
            cache=EvidenceCache(tmp_path / "cache"),
        )
    )

    assert source.search(public_cve_claim("CVE-2022-45157")) == []


def test_github_untrusted_advisory_url_falls_back_to_github(tmp_path) -> None:
    payload = github_payload()
    payload[0]["html_url"] = "https://evil.example/advisory"
    source = GitHubAdvisoryEvidenceSource(
        EvidenceHttpClient(
            transport=StubTransport(payload),
            cache=EvidenceCache(tmp_path / "cache"),
        )
    )

    evidence = source.search(public_cve_claim("CVE-2022-45157"))

    assert evidence[0].source_url == "https://github.com/advisories/GHSA-aaaa-bbbb-cccc"


def test_github_string_first_patched_version_is_supported(tmp_path) -> None:
    payload = github_payload()
    payload[0]["vulnerabilities"][0]["first_patched_version"] = "1.2.3"
    source = GitHubAdvisoryEvidenceSource(
        EvidenceHttpClient(
            transport=StubTransport(payload),
            cache=EvidenceCache(tmp_path / "cache"),
        )
    )

    evidence = source.search(public_cve_claim("CVE-2022-45157"))

    assert evidence[0].source_metadata["vulnerabilities"][0]["first_patched_version"] == "1.2.3"


def test_github_string_reference_is_supported(tmp_path) -> None:
    payload = github_payload()
    payload[0]["references"] = ["https://nvd.nist.gov/vuln/detail/CVE-2022-45157"]
    source = GitHubAdvisoryEvidenceSource(
        EvidenceHttpClient(
            transport=StubTransport(payload),
            cache=EvidenceCache(tmp_path / "cache"),
        )
    )

    evidence = source.search(public_cve_claim("CVE-2022-45157"))

    assert evidence[0].source_metadata["references"] == [
        "https://nvd.nist.gov/vuln/detail/CVE-2022-45157"
    ]


def test_github_unexpected_mapping_shape_is_audited_without_crashing(tmp_path) -> None:
    payload = github_payload()
    payload[0]["vulnerabilities"] = [42]
    source = GitHubAdvisoryEvidenceSource(
        EvidenceHttpClient(
            transport=StubTransport(payload),
            cache=EvidenceCache(tmp_path / "cache"),
        )
    )

    evidence = source.search(public_cve_claim("CVE-2022-45157"))

    assert evidence == []
    assert source.last_audit.error_type == "response_mapping_error"
