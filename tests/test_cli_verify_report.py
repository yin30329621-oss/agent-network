import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from agent_network.cli import app


REPORT = """# Technical Report

Rancher supports downstream integration.
"""


def test_verify_report_writes_offline_artifact(tmp_path) -> None:
    report = tmp_path / "report.md"
    output = tmp_path / "artifact.json"
    report.write_text(REPORT, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["verify-report", str(report), "--output", str(output), "--offline"],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert set(artifact) == {
        "metadata",
        "claims",
        "evidence",
        "fact_review",
        "reconciliation",
        "statistics",
    }
    assert artifact["metadata"]["offline"] is True
    assert artifact["metadata"]["enable_dual_fact"] is False
    assert artifact["statistics"]["model_call_count"] == 0
    assert artifact["statistics"]["network_request_count"] == 0
    assert "Wrote" in result.output


def test_verify_report_dry_run_does_not_execute_dual_fact(tmp_path) -> None:
    report = tmp_path / "report.md"
    output = tmp_path / "dry-run.json"
    report.write_text(REPORT, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "verify-report",
            str(report),
            "--output",
            str(output),
            "--offline",
            "--dry-run",
            "--enable-dual-fact",
        ],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["metadata"]["dry_run"] is True
    assert artifact["metadata"]["dual_fact_requested"] is True
    assert artifact["metadata"]["enable_dual_fact"] is False
    assert artifact["fact_review"]["fact_a"] == []
    assert artifact["statistics"]["model_call_count"] == 0
    assert artifact["statistics"]["network_request_count"] == 0


def test_verify_report_rejects_online_mode(tmp_path) -> None:
    report = tmp_path / "report.md"
    report.write_text(REPORT, encoding="utf-8")

    result = CliRunner().invoke(app, ["verify-report", str(report), "--online"])

    assert result.exit_code != 0
    assert "only supports --offline" in result.output


def test_verify_report_defaults_to_fake_reviewer_without_confirmation(tmp_path) -> None:
    report = tmp_path / "report.md"
    output = tmp_path / "artifact.json"
    report.write_text(REPORT, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "verify-report",
            str(report),
            "--output",
            str(output),
            "--offline",
            "--enable-dual-fact",
        ],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["metadata"]["live_model_calls_confirmed"] is False
    assert artifact["statistics"]["model_call_count"] == 2


def test_verify_report_rejects_planned_call_count_mismatch(tmp_path) -> None:
    report = tmp_path / "report.md"
    report.write_text(REPORT, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "verify-report",
            str(report),
            "--offline",
            "--enable-dual-fact",
            "--confirm-live-model-calls",
            "--confirm-planned-call-count",
            "8",
        ],
    )

    assert result.exit_code != 0
    assert "estimated=2" in result.output
    assert "confirmed=8" in result.output


def test_verify_report_runs_in_default_fake_mode(tmp_path) -> None:
    report = tmp_path / "report.md"
    output = tmp_path / "artifact.json"
    report.write_text(REPORT, encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "verify-report",
            str(report),
            "--output",
            str(output),
            "--offline",
            "--enable-dual-fact",
        ],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["metadata"]["live_model_calls_confirmed"] is False
    assert artifact["statistics"]["model_call_count"] == 2
    assert artifact["statistics"]["network_request_count"] == 0


def test_verify_report_batch_size_five_plans_eight_calls(tmp_path) -> None:
    report = Path("benchmarks/fixtures/report-verification-v0.4-baseline-v1/report.md")
    output = tmp_path / "artifact.json"

    result = CliRunner().invoke(
        app,
        [
            "verify-report",
            str(report),
            "--output",
            str(output),
            "--offline",
            "--enable-dual-fact",
            "--batch-size",
            "5",
            "--confirm-planned-call-count",
            "8",
        ],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["metadata"]["reviewer_batch_size"] == 5
    assert artifact["statistics"]["total_claim_count"] == 19
    assert artifact["statistics"]["model_call_count"] == 8


def test_verify_report_default_batch_size_three_is_unchanged(tmp_path) -> None:
    report = Path("benchmarks/fixtures/report-verification-v0.4-baseline-v1/report.md")
    output = tmp_path / "artifact.json"

    result = CliRunner().invoke(
        app,
        [
            "verify-report",
            str(report),
            "--output",
            str(output),
            "--offline",
            "--enable-dual-fact",
            "--confirm-planned-call-count",
            "14",
        ],
    )

    assert result.exit_code == 0, result.output
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["metadata"]["reviewer_batch_size"] == 3
    assert artifact["statistics"]["model_call_count"] == 14


def test_verify_report_confirmation_builds_real_reviewers(monkeypatch, tmp_path) -> None:
    report = tmp_path / "report.md"
    output = tmp_path / "artifact.json"
    report.write_text(REPORT, encoding="utf-8")
    calls = []

    class RealReviewer:
        def __init__(self, reviewer_id):
            self.reviewer_id = reviewer_id
            self.config = SimpleNamespace(max_tokens=2400, timeout_seconds=90)

        def review_batch(self, inputs):
            calls.append(self.reviewer_id)
            return []

    class AppConfig:
        pass

    monkeypatch.setattr("agent_network.cli.load_config", lambda: AppConfig())
    monkeypatch.setattr(
        "agent_network.cli.fact_model_adapter_from_config",
        lambda config, reviewer: RealReviewer(reviewer),
    )

    result = CliRunner().invoke(
        app,
        [
            "verify-report",
            str(report),
            "--output",
            str(output),
            "--offline",
            "--enable-dual-fact",
            "--confirm-live-model-calls",
            "--confirm-planned-call-count",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["fact_a", "fact_b"]
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["metadata"]["live_model_calls_confirmed"] is True
    assert artifact["statistics"]["network_request_count"] == 0


def test_verify_report_planned_mismatch_does_not_load_provider(monkeypatch, tmp_path) -> None:
    report = tmp_path / "report.md"
    report.write_text(REPORT, encoding="utf-8")
    load_calls = []

    monkeypatch.setattr(
        "agent_network.cli.load_config",
        lambda: load_calls.append("load_config"),
    )
    monkeypatch.setattr(
        "agent_network.cli.fact_model_adapter_from_config",
        lambda *args: load_calls.append("adapter"),
    )

    result = CliRunner().invoke(
        app,
        [
            "verify-report",
            str(report),
            "--offline",
            "--enable-dual-fact",
            "--confirm-live-model-calls",
            "--confirm-planned-call-count",
            "8",
        ],
    )

    assert result.exit_code != 0
    assert "estimated=2" in result.output
    assert load_calls == []
