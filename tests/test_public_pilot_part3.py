import importlib.util
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "public_pilot_part2", Path("benchmarks/public_pilot_part2.py")
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_part3_applies_only_confirmed_structured_rules() -> None:
    report = _MODULE.audit_part1_disagreements(Path("artifacts/public-pilot/part1"))
    result = _MODULE.reconcile_after_rules(report)

    assert [item["final_status"] for item in result["reconciliations"]] == [
        "manual_review",
        "insufficient_evidence",
        "insufficient_evidence",
    ]
    assert result["automatically_resolved_count"] == 2
    assert result["manual_review_count"] == 1
    assert result["model_call_count"] == result["network_request_count"] == 0


def test_part3_preserves_both_original_review_results() -> None:
    report = _MODULE.audit_part1_disagreements(Path("artifacts/public-pilot/part1"))
    result = _MODULE.reconcile_after_rules(report)
    original = result["reconciliations"][0]["original_disagreement"]

    assert original["fact_a"]["verdict"] == "supported"
    assert original["fact_b"]["verdict"] == "supported"
    assert original["fact_a"]["cited_chunk_ids"] == original["fact_b"]["cited_chunk_ids"]
    assert result["reconciliations"][0]["needs_manual_review"] is True
