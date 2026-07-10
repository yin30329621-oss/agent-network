import json

from typer.testing import CliRunner

from agent_network.cli import app


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
