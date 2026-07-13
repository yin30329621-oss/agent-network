from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from fact_evidence_live_ab import (
    FactEvidenceLiveAbCase,
    FactEvidenceLiveAbEvaluator,
    FactEvidenceLiveAbRunConfig,
    LiveAbSafetyError,
)


class NeverCalledFact:
    def review(self, request):
        raise AssertionError("Fact model must not run")


def case() -> FactEvidenceLiveAbCase:
    return FactEvidenceLiveAbCase(
        "case-1",
        "claim",
        "Rancher Manager",
        "Cluster Agent",
        "supported",
        "official_evidence_available",
        ["doc"],
        [],
        "note",
    )


def test_live_harness_rejects_without_all_opt_in_confirmations() -> None:
    evaluator = FactEvidenceLiveAbEvaluator(NeverCalledFact())
    for config in (
        FactEvidenceLiveAbRunConfig(),
        FactEvidenceLiveAbRunConfig(enabled=True, model="model"),
        FactEvidenceLiveAbRunConfig(enabled=True, confirm_live_model_calls=True),
        FactEvidenceLiveAbRunConfig(
            enabled=True, confirm_live_model_calls=True, model="model", confirm_planned_call_count=1
        ),
    ):
        with pytest.raises(LiveAbSafetyError):
            evaluator.run([case()], config)


def test_live_harness_plan_is_bounded_and_does_not_call_models_or_network() -> None:
    evaluator = FactEvidenceLiveAbEvaluator(NeverCalledFact())
    config = FactEvidenceLiveAbRunConfig(
        max_cases=1, evidence_off_enabled=True, evidence_on_enabled=True
    )

    plan = evaluator.plan([case(), case()], config)

    assert plan["selected_case_count"] == 1
    assert plan["planned_fact_model_calls"] == 2
    assert plan["planned_off_calls"] == plan["planned_on_calls"] == 1
