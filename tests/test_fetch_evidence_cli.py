import json
import socket

from typer.testing import CliRunner

from agent_network.cli import app
from agent_network.evidence.cache import EvidenceCache
from agent_network.evidence.http import EvidenceHttpClient, HttpRequest, HttpResponse


class GitHubPilotTransport:
    def send(self, request: HttpRequest) -> HttpResponse:
        payload = [
            {
                "ghsa_id": "GHSA-aaaa-bbbb-cccc",
                "cve_id": "CVE-2022-45157",
                "html_url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc",
                "description": "Mock advisory used by an offline CLI test.",
                "severity": "high",
                "published_at": "2022-11-10T10:00:00Z",
                "updated_at": "2024-01-02T12:30:00Z",
                "cvss": {"score": 8.8, "vector_string": "CVSS:3.1/test"},
                "cwes": [],
                "vulnerabilities": [],
                "references": [],
            }
        ]
        return HttpResponse(
            status=200,
            final_url=request.url,
            headers={"X-RateLimit-Remaining": "59"},
            body=json.dumps(payload).encode(),
        )


def test_fetch_evidence_cli_uses_injected_transport_and_no_model(tmp_path, monkeypatch) -> None:
    def blocked_socket(*args, **kwargs):
        raise AssertionError("test attempted a real network request")

    fake_client = EvidenceHttpClient(
        transport=GitHubPilotTransport(),
        cache=EvidenceCache(tmp_path / "cache"),
    )
    monkeypatch.setattr(socket, "socket", blocked_socket)
    monkeypatch.setattr("agent_network.cli.EvidenceHttpClient", lambda **kwargs: fake_client)
    output = tmp_path / "pilot"

    result = CliRunner().invoke(
        app,
        [
            "fetch-evidence",
            "CVE-2022-45157",
            "--source",
            "github",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Network requests: 1; Model calls: 0" in result.output
    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert run["network_request_count"] == 1
    assert run["model_call_count"] == 0
    assert len(json.loads((output / "evidence.json").read_text(encoding="utf-8"))) == 1


def test_fetch_evidence_rejects_invalid_source_before_network(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "fetch-evidence",
            "CVE-2022-45157",
            "--source",
            "unofficial",
            "--output",
            str(tmp_path),
        ],
    )

    assert result.exit_code != 0
    assert "--source must be one of" in result.output
