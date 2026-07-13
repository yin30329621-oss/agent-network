import json

from agent_network.evidence.cache import EvidenceCache
from agent_network.evidence.http import EvidenceHttpClient, HttpRequest, HttpResponse
from agent_network.evidence.nvd import NvdEvidenceSource
from agent_network.evidence.pilot import public_cve_claim
from agent_network.evidence.schemas import VerificationStatus
from agent_network.evidence.verifier import OfflineEvidenceVerifier


class StubTransport:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = 0

    def send(self, request: HttpRequest) -> HttpResponse:
        self.calls += 1
        return HttpResponse(
            status=200,
            final_url=request.url,
            headers={"ETag": '"nvd-etag"'},
            body=json.dumps(self.payload).encode(),
        )


def nvd_payload() -> dict:
    return {
        "totalResults": 1,
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2022-45157",
                    "sourceIdentifier": "security@example.invalid",
                    "published": "2022-11-10T10:00:00.000",
                    "lastModified": "2024-01-02T12:30:00.000",
                    "descriptions": [
                        {"lang": "en", "value": "Public fixture description from NVD."}
                    ],
                    "metrics": {
                        "cvssMetricV31": [
                            {
                                "source": "nvd@nist.gov",
                                "type": "Primary",
                                "cvssData": {
                                    "version": "3.1",
                                    "baseScore": 8.8,
                                    "baseSeverity": "HIGH",
                                    "vectorString": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
                                },
                            }
                        ]
                    },
                    "references": [{"url": "https://github.com/advisories/GHSA-test"}],
                    "configurations": [
                        {
                            "nodes": [
                                {
                                    "cpeMatch": [
                                        {
                                            "vulnerable": True,
                                            "criteria": "cpe:2.3:a:example:product:*:*:*:*:*:*:*:*",
                                        }
                                    ]
                                }
                            ]
                        }
                    ],
                }
            }
        ],
    }


def source(tmp_path, payload):
    transport = StubTransport(payload)
    http = EvidenceHttpClient(
        transport=transport,
        cache=EvidenceCache(tmp_path / "cache"),
    )
    return NvdEvidenceSource(http), transport


def test_nvd_response_maps_to_evidence_schema(tmp_path) -> None:
    nvd, transport = source(tmp_path, nvd_payload())

    evidence = nvd.search(public_cve_claim("CVE-2022-45157"))

    assert transport.calls == 1
    assert len(evidence) == 1
    item = evidence[0]
    assert item.evidence_id == "nvd-cve-2022-45157"
    assert item.official_domain == "nvd.nist.gov"
    assert item.excerpt == "Public fixture description from NVD."
    assert item.response_hash.startswith("sha256:")
    assert item.source_metadata["cvss"] == {
        "version": "3.1",
        "base_score": 8.8,
        "vector_string": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
        "base_severity": "HIGH",
        "source": "nvd@nist.gov",
        "type": "Primary",
    }
    assert item.source_metadata["configurations"]
    assert item.source_metadata["references"] == ["https://github.com/advisories/GHSA-test"]


def test_nvd_no_result_returns_empty_and_not_verified(tmp_path) -> None:
    nvd, _ = source(tmp_path, {"totalResults": 0, "vulnerabilities": []})
    claim = public_cve_claim("CVE-2022-45157")

    assert nvd.search(claim) == []
    result = OfflineEvidenceVerifier(nvd).verify(claim)

    assert result.verification_status == VerificationStatus.NOT_VERIFIED
    assert result.contradicting_evidence_ids == []
