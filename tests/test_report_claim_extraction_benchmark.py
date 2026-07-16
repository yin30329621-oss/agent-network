import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "benchmarks" / "report_claim_extraction_benchmark.py"
SPEC = importlib.util.spec_from_file_location("report_claim_extraction_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


FIXTURE = ROOT / "benchmarks" / "fixtures" / "report-claim-extraction-v1"


def test_report_claim_extraction_fixture_matches_expected_contract() -> None:
    result = MODULE.run_benchmark(FIXTURE)

    assert result["passed"] is True
    assert result["metrics"] == {
        "candidate_count": 10,
        "extracted_count": 3,
        "duplicate_count": 1,
        "failure_count": 0,
    }
    assert result["audit"] == {"model_call_count": 0, "network_request_count": 0}
    assert result["checks"] == {
        "statistics_match": True,
        "claim_ids_match": True,
        "heading_paths_match": True,
    }


def test_report_claim_extraction_benchmark_is_deterministic() -> None:
    first = MODULE.run_benchmark(FIXTURE)
    second = MODULE.run_benchmark(FIXTURE)

    assert first == second
