import json
import socket
from pathlib import Path

from typer.testing import CliRunner

from agent_network.cli import app
from agent_network.evidence.pipeline_benchmark import (
    EvidencePipelineBenchmarkFixture,
    run_evidence_pipeline_benchmark,
    write_evidence_pipeline_benchmark,
)


FIXTURE = Path("benchmarks/fixtures/evidence-pipeline-v1")


def test_benchmark_fixture_has_required_cases_and_fixture_only_urls() -> None:
    fixture = EvidencePipelineBenchmarkFixture.load(FIXTURE)

    assert fixture.fixture_notice.startswith("FIXTURE ONLY")
    assert len(fixture.cases) == 16
    assert len({case.case_id for case in fixture.cases}) == 16
    assert all(document.fixture_only for document in fixture.catalog)
    assert all(".invalid/" in document.canonical_url for document in fixture.catalog)


def test_benchmark_metrics_meet_v1_thresholds_and_are_reproducible() -> None:
    first = run_evidence_pipeline_benchmark(FIXTURE)
    second = run_evidence_pipeline_benchmark(FIXTURE)
    metrics = first.metrics

    assert metrics.total_cases == 16
    assert metrics.passed_cases == 16
    assert metrics.failed_cases == 0
    assert metrics.top1_accuracy >= 0.85
    assert metrics.recall_at_3 >= 0.90
    assert metrics.precision_at_3 == 1.0
    assert metrics.forbidden_hit_rate == 0.0
    assert metrics.product_isolation_accuracy == 1.0
    assert metrics.component_isolation_accuracy >= 0.90
    assert metrics.version_match_accuracy == 1.0
    assert metrics.not_found_accuracy == 1.0
    assert metrics.status_accuracy == 1.0
    assert metrics == second.metrics
    assert first.case_results == second.case_results
    assert first.network_request_count == 0
    assert first.model_call_count == 0


def test_benchmark_records_forbidden_and_status_failures(tmp_path: Path) -> None:
    fixture_path = tmp_path / "fixture"
    fixture_path.mkdir()
    for filename in ("metadata.json", "catalog.json", "cases.json"):
        (fixture_path / filename).write_text((FIXTURE / filename).read_text(encoding="utf-8"))
    cases_path = fixture_path / "cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases[0]["forbidden_document_ids"] = ["doc-cluster-agent"]
    cases[0]["expected_status"] = "not_verified"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")

    result = run_evidence_pipeline_benchmark(fixture_path)
    failure = next(item for item in result.case_results if item.case_id == "cluster-agent-connect")

    assert failure.passed is False
    assert failure.forbidden_hits == ["doc-cluster-agent"]
    assert "forbidden_document_hit" in failure.failure_reasons
    assert "unexpected_status" in failure.failure_reasons


def test_benchmark_writes_json_markdown_and_run_metadata(tmp_path: Path) -> None:
    result = run_evidence_pipeline_benchmark(FIXTURE)
    benchmark_path, markdown_path, run_path = write_evidence_pipeline_benchmark(result, tmp_path)

    payload = json.loads(benchmark_path.read_text(encoding="utf-8"))
    run = json.loads(run_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["metrics"]["top1_accuracy"] == 1.0
    assert run["network_request_count"] == 0
    assert run["model_call_count"] == 0
    assert (
        "本基准使用离线 fixture，只验证 Evidence Pipeline 逻辑，不代表真实官方文档检索准确率。"
        in markdown
    )


def test_benchmark_cli_is_offline_and_writes_requested_reports(tmp_path: Path, monkeypatch) -> None:
    def blocked_socket(*args, **kwargs):
        raise AssertionError("benchmark attempted a network request")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    output = tmp_path / "benchmark"
    result = CliRunner().invoke(
        app,
        ["benchmark-evidence-pipeline", str(FIXTURE), "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    assert "Cases: 16/16; Model calls: 0; Network requests: 0" in result.output
    assert (output / "benchmark.json").exists()
    assert (output / "benchmark.md").exists()
    assert (output / "run.json").exists()
