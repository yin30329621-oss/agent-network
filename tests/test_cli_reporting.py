import json

from typer.testing import CliRunner

from agent_network.cli import _print_progress, app
from agent_network.schemas import AgentReview


def test_stats_handles_no_latest(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["stats"])

    assert result.exit_code == 0
    assert "no completed run found" in result.output


def test_baseline_from_review_json(tmp_path) -> None:
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "metadata": {"source_file": "reports/sample.md", "timestamp": "now"},
                "summary": {"critical": 0, "high": 1, "medium": 0, "low": 0, "info": 0},
                "execution": [],
                "merged_findings": [],
                "disagreements": [],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "baseline.md"
    runner = CliRunner()

    result = runner.invoke(app, ["baseline", "--input", str(review), "--output", str(output)])

    assert result.exit_code == 0
    assert output.exists()
    assert "Agent Network Baseline" in output.read_text(encoding="utf-8")


def test_review_accepts_explicit_chinese_language(tmp_path, monkeypatch) -> None:
    report = tmp_path / "rancher.md"
    report.write_text("中文 Rancher Kubernetes RBAC WebSocket 审查报告。", encoding="utf-8")
    output = tmp_path / "review-output"
    monkeypatch.setattr("agent_network.cli.register_run", lambda **kwargs: None)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "review",
            str(report),
            "--mock",
            "--language",
            "zh",
            "--config",
            "configs/default.yaml",
            "--prompts",
            "prompts",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads((output / "review.json").read_text(encoding="utf-8"))
    markdown = (output / "review.md").read_text(encoding="utf-8")
    assert payload["metadata"]["language"] == "zh"
    assert len(payload["execution"]) == 4
    assert markdown.startswith("# 审查报告")


def test_balanced_profile_warns_for_long_input(tmp_path, monkeypatch) -> None:
    report = tmp_path / "long.md"
    report.write_text("中" * 20_001, encoding="utf-8")
    output = tmp_path / "review-output"
    monkeypatch.setattr("agent_network.cli.register_run", lambda **kwargs: None)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "review",
            str(report),
            "--mock",
            "--language",
            "zh",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "当前输入属于长报告" in result.output
    assert "--profile long-report" in result.output
    payload = json.loads((output / "review.json").read_text(encoding="utf-8"))
    assert payload["metadata"]["profile"] == "balanced"
    assert payload["metadata"]["input_size_class"] == "long"


def test_long_report_profile_is_explicit_and_suppresses_warning(tmp_path, monkeypatch) -> None:
    report = tmp_path / "long.md"
    report.write_text("中" * 20_001, encoding="utf-8")
    output = tmp_path / "review-output"
    monkeypatch.setattr("agent_network.cli.register_run", lambda **kwargs: None)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "review",
            str(report),
            "--mock",
            "--profile",
            "long-report",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "当前输入属于长报告" not in result.output
    payload = json.loads((output / "review.json").read_text(encoding="utf-8"))
    assert payload["metadata"]["profile"] == "long-report"


def test_progress_prints_final_business_status(capsys) -> None:
    _print_progress(
        "security",
        "parse_failed",
        40.8,
        AgentReview(agent="security", summary="", status="parse_failed"),
    )
    _print_progress(
        "logic",
        "failed",
        729.8,
        AgentReview(agent="logic", summary="", status="failed", error_type="Timeout"),
    )
    _print_progress(
        "merge",
        "skipped",
        0.0,
        AgentReview(agent="merge", summary="", status="skipped"),
    )

    output = capsys.readouterr().out
    assert "Security Agent parse_failed in 40.8s" in output
    assert "Logic Agent failed in 729.8s" in output
    assert "Merge Agent skipped in 0.0s" in output


def test_extract_claims_outputs_result_and_statistics(tmp_path) -> None:
    report = tmp_path / "technical-report.md"
    report.write_text(
        "# Architecture\n\n"
        "Cluster Agent connects to Rancher Server through a tunnel.\n\n"
        "- ServiceAccount requires RBAC permissions.\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["extract-claims", str(report)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["statistics"] == {
        "candidate_count": 2,
        "extracted_count": 2,
        "duplicate_count": 0,
        "failure_count": 0,
        "selected_count": 2,
        "truncated_count": 0,
    }
    assert payload["claims"][0]["claim_id"].startswith("claim-")
    assert payload["claims"][0]["source_file"] == "technical-report.md"
    assert payload["claims"][0]["heading_path"] == ["Architecture"]
    assert payload["claims"][0]["line_start"] == 3
    assert payload["claims"][0]["line_end"] == 3
    assert payload["claims"][0]["extraction_confidence"] == 0.9
    assert payload["claims"][0]["extraction_method"] == "deterministic"


def test_extract_claims_supports_output_and_source_name_override(tmp_path) -> None:
    report = tmp_path / "input.md"
    report.write_text("The server manages downstream clusters.\n", encoding="utf-8")
    output = tmp_path / "nested" / "claims.json"

    result = CliRunner().invoke(
        app,
        [
            "extract-claims",
            str(report),
            "--output",
            str(output),
            "--source-name",
            "stable-report.md",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["claims"][0]["source_file"] == "stable-report.md"
    assert "Wrote" in result.output
