import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "benchmarks" / "report_verification_e2e_benchmark.py"
SPEC = importlib.util.spec_from_file_location("report_verification_e2e_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


FIXTURE = ROOT / "benchmarks" / "fixtures" / "report-verification-e2e-v1"


def test_report_verification_e2e_fixture_is_offline_and_complete() -> None:
    result = MODULE.run_benchmark(FIXTURE)

    assert result["passed"] is True
    assert result["metrics"]["candidate_count"] == 3
    assert result["metrics"]["extracted_count"] == 2
    assert result["metrics"]["evidence_decision_count"] == 1
    assert result["metrics"]["failure_slot_count"] == 1
    assert result["metrics"]["claim_id_aligned"] is True
    assert result["metrics"]["model_call_count"] == 0
    assert result["metrics"]["network_request_count"] == 0
    assert result["audit"]["model_call_count"] == 0
    assert result["audit"]["network_request_count"] == 0


def test_report_verification_e2e_benchmark_is_deterministic() -> None:
    assert MODULE.run_benchmark(FIXTURE) == MODULE.run_benchmark(FIXTURE)


BASELINE_FIXTURE = ROOT / "benchmarks" / "fixtures" / "report-verification-v0.4-baseline-v1"


def test_report_verification_v04_baseline_plans_eight_dual_fact_calls() -> None:
    result = MODULE.run_benchmark(BASELINE_FIXTURE)

    assert result["passed"] is True
    assert result["metrics"]["extracted_count"] == 19
    assert result["metrics"]["fact_a_calls"] == 4
    assert result["metrics"]["fact_b_calls"] == 4
    assert result["metrics"]["total_planned_calls"] == 8
    assert result["metrics"]["model_call_count"] == 8
    assert result["metrics"]["network_request_count"] == 0
    assert result["metrics"]["reconciliation_executed"] is True
