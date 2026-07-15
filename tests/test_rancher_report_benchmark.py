import json
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "rancher_report_benchmark", Path("benchmarks/rancher_report_benchmark.py")
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
run_benchmark = _MODULE.run_benchmark


FIXTURE = Path("benchmarks/fixtures/rancher-report-v1")


def test_rancher_report_fixture_has_expected_shape_and_status_coverage() -> None:
    claims = json.loads((FIXTURE / "claims.json").read_text(encoding="utf-8"))
    truth = json.loads((FIXTURE / "ground-truth.json").read_text(encoding="utf-8"))
    assert len(claims["claims"]) == 19
    assert {item["claim_id"] for item in claims["claims"]} == {
        item["claim_id"] for item in truth["claims"]
    }
    statuses = {item["expected_status"] for item in truth["claims"]}
    assert {
        "verified_supported",
        "contradicted",
        "insufficient_evidence",
        "needs_external_verification",
        "unavailable",
        "extraction_failed",
    }.issubset(statuses)
    assert all("rationale" in item and "limitations" in item for item in truth["claims"])


def test_rancher_report_benchmark_is_offline_and_deterministic() -> None:
    first = run_benchmark(FIXTURE)
    second = run_benchmark(FIXTURE)
    assert first["metrics"] == second["metrics"]
    assert first["audit"] == {"model_call_count": 0, "network_request_count": 0}
    assert first["metrics"]["total_claims"] == 19
    assert first["metrics"]["forbidden_hit_count"] == 0
    assert first["metrics"]["manual_review_rate"] == 1.0
