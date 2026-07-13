import json
import socket

from typer.testing import CliRunner

from agent_network.cli import app


def test_evidence_cli_runs_with_network_hard_disabled(tmp_path, monkeypatch) -> None:
    def blocked_socket(*args, **kwargs):
        raise AssertionError("offline evidence CLI attempted a network request")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    output = tmp_path / "evidence-output"
    result = CliRunner().invoke(
        app,
        [
            "verify-evidence",
            "benchmarks/fixtures/evidence-v1",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Model calls: 0; Network requests: 0" in result.output
    assert (output / "verification.json").exists()
    assert (output / "verification.md").exists()
    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert run["model_call_count"] == 0
    assert run["network_request_count"] == 0


def test_evidence_cli_filters_claim_and_output_format(tmp_path) -> None:
    output = tmp_path / "one-claim"
    result = CliRunner().invoke(
        app,
        [
            "verify-evidence",
            "benchmarks/fixtures/evidence-v1",
            "--claim",
            "claim-cve-exists",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads((output / "verification.json").read_text(encoding="utf-8"))
    assert payload["claim_count"] == 1
    assert not (output / "verification.md").exists()
    assert (output / "run.json").exists()
