from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "benchmarks" / "rancher_report_dual_fact_benchmark.py"
SPEC = importlib.util.spec_from_file_location("rancher_report_dual_fact_benchmark", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_dry_run_uses_fixed_five_claim_batches() -> None:
    inputs = MODULE.build_review_inputs()
    plan = MODULE.build_plan(inputs, batch_size=5)

    assert len(inputs) == 19
    assert [batch["claim_count"] for batch in plan["batches"]] == [5, 5, 5, 4]
    assert plan["planned_fact_a_calls"] == 4
    assert plan["planned_fact_b_calls"] == 4
    assert plan["planned_total_model_calls"] == 8
    assert plan["estimated_network_request_count"] == 0
    assert plan["per_claim_model_calls"] == 0


def test_fact_a_and_fact_b_input_hashes_match_per_batch() -> None:
    plan = MODULE.build_plan(MODULE.build_review_inputs(), batch_size=5)

    assert all(batch["input_hashes_match"] for batch in plan["batches"])
    assert all(
        batch["fact_a_input_sha256"] == batch["fact_b_input_sha256"] for batch in plan["batches"]
    )
    assert len({batch["fact_a_input_sha256"] for batch in plan["batches"]}) == 4
