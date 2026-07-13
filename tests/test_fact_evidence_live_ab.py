import json
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from fact_evidence_live_ab import (
    FactEvidenceLiveAbCase,
    FactEvidenceLiveAbCaseResult,
    FactEvidenceLiveAbEvaluator,
    FactEvidenceLiveAbRunConfig,
    LiveAbSafetyError,
    _summarize_results,
    load_live_ab_cases,
    load_live_ab_fixture,
    main,
    safe_results_directory,
)


class NeverCalledFact:
    def review(self, request):
        raise AssertionError("Fact model must not run")


def case(case_id: str = "case-1") -> FactEvidenceLiveAbCase:
    return FactEvidenceLiveAbCase(
        case_id,
        "claim",
        "Rancher Manager",
        "Cluster Agent",
        "supported",
        "official_evidence_available",
        ["doc"],
        [],
        "note",
    )


def test_fixture_loader_keeps_fixture_order_and_validates_requested_ids() -> None:
    fixture = load_live_ab_fixture()

    assert [item.case_id for item in fixture.cases[:2]] == ["cluster-agent", "reverse-tunnel"]
    assert [
        item.case_id for item in load_live_ab_cases(case_ids=("absolute", "cluster-agent"))
    ] == [
        "cluster-agent",
        "absolute",
    ]
    with pytest.raises(ValueError, match="Unknown live A/B case_id"):
        load_live_ab_cases(case_ids=("missing",))


def test_fixture_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    source = Path("benchmarks/fixtures/fact-evidence-live-ab-v1")
    for filename in ("metadata.json", "human-review-template.json"):
        (tmp_path / filename).write_text(
            (source / filename).read_text(encoding="utf-8"), encoding="utf-8"
        )
    duplicate = [json.loads((source / "cases.json").read_text(encoding="utf-8"))[0]] * 2
    (tmp_path / "cases.json").write_text(json.dumps(duplicate), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate or empty"):
        load_live_ab_fixture(tmp_path)


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


def test_plan_is_bounded_and_reports_deterministic_call_and_character_counts() -> None:
    evaluator = FactEvidenceLiveAbEvaluator(None)
    config = FactEvidenceLiveAbRunConfig(
        model="explicit-model", case_ids=("case-1", "case-2"), max_cases=2
    )

    plan = evaluator.plan([case(), case("case-2")], config)

    assert plan["selected_case_ids"] == ["case-1", "case-2"]
    assert plan["selected_case_count"] == 2
    assert plan["planned_fact_model_calls"] == 4
    assert plan["planned_off_calls"] == plan["planned_on_calls"] == 2
    assert plan["estimated_prompt_characters"] == 20
    assert plan["live_calls_enabled"] is False
    assert plan["output_path"] is None
    assert plan["timeout_per_call"] == 100.0
    assert plan["maximum_expected_wait_seconds"] == 400.0


def test_harness_watchdog_returns_timeout_and_does_not_block_follow_up(capsys) -> None:
    class BlockingFact:
        def __init__(self):
            self.started = threading.Event()

        def review(self, request):
            self.started.set()
            threading.Event().wait(1)

    fact = BlockingFact()
    evaluator = FactEvidenceLiveAbEvaluator(fact)
    config = FactEvidenceLiveAbRunConfig(
        enabled=True,
        confirm_live_model_calls=True,
        model="explicit-model",
        max_cases=1,
        evidence_off_enabled=True,
        evidence_on_enabled=False,
        confirm_planned_call_count=1,
        timeout_seconds=0.01,
    )

    result = evaluator.run([case()], config)

    assert fact.started.is_set()
    assert result.results[0].error_code == "harness_timeout"
    assert "token_usage_available=false" in capsys.readouterr().out


def test_plan_mode_does_not_require_api_key_or_call_network_or_models(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)

    assert main(["--plan", "--model", "explicit-model", "--case-id", "cluster-agent"]) == 0

    plan = json.loads(capsys.readouterr().out)
    assert plan["planned_fact_model_calls"] == 2
    assert plan["estimated_prompt_characters"] > 0


def test_live_mode_requires_exact_confirmation_and_missing_key_has_zero_calls(monkeypatch) -> None:
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    base = [
        "--run-live",
        "--model",
        "explicit-model",
        "--case-id",
        "cluster-agent",
        "--confirm-live-model-calls",
    ]
    with pytest.raises(LiveAbSafetyError, match="call plan"):
        main(base + ["--confirm-planned-call-count", "1"])
    with pytest.raises(LiveAbSafetyError, match="SILICONFLOW_API_KEY"):
        main(base + ["--confirm-planned-call-count", "2"])


def test_results_directory_is_confined_to_results_local() -> None:
    allowed = safe_results_directory("benchmarks/results-local/sample")
    assert allowed.name == "sample"
    with pytest.raises(LiveAbSafetyError, match="results-local"):
        safe_results_directory("outputs/not-allowed")
    with pytest.raises(LiveAbSafetyError, match="results-local"):
        safe_results_directory("benchmarks/results-local/../../outside")


def test_cli_help_is_available(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    assert "--run-live" in capsys.readouterr().out


def _scored_result(
    case_id: str, mode: str, verdict: str | None, relation: str
) -> FactEvidenceLiveAbCaseResult:
    return FactEvidenceLiveAbCaseResult(
        case_id=case_id,
        mode=mode,
        model="test-model",
        verdict=verdict,
        confidence=None,
        evidence_status="official_evidence_available",
        evidence_chunk_ids=[],
        evidence_document_ids=[],
        evidence_urls=[],
        evidence_limitations=[],
        validated_reference_count=0,
        rejected_reference_count=0,
        prompt_character_count=10,
        response_character_count=10,
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        model_call_count=1,
        network_request_count=0,
        latency_ms=0.0,
        evidence_relation=relation,
        verdict_scoring_available=verdict is not None,
    )


def test_summary_scores_explicit_verdict_and_relation_enums() -> None:
    expected = FactEvidenceLiveAbCase(
        "structured",
        "claim",
        "Rancher Manager",
        "Cluster Agent",
        "supported",
        "official_evidence_available",
        [],
        [],
        "test",
        expected_evidence_relation="direct_support",
    )

    summary = _summarize_results(
        [
            _scored_result("structured", "off", "supported", "direct_support"),
            _scored_result("structured", "on", "supported", "direct_support"),
        ],
        [expected],
    )

    assert summary["verdict_scoring_available"] is True
    assert summary["verdict_scored_case_count"] == 1
    assert summary["unscored_verdict_case_count"] == 0
    assert summary["off_verdict_accuracy"] == 1.0
    assert summary["on_verdict_accuracy"] == 1.0
    assert summary["off_relation_accuracy"] == summary["on_relation_accuracy"] == 1.0


def test_summary_does_not_score_natural_language_verdict() -> None:
    expected = FactEvidenceLiveAbCase(
        "natural",
        "claim",
        "Rancher Manager",
        "Cluster Agent",
        "supported",
        "official_evidence_available",
        [],
        [],
        "test",
        expected_evidence_relation="direct_support",
    )

    summary = _summarize_results(
        [_scored_result("natural", "off", None, "direct_support")], [expected]
    )

    assert summary["verdict_scoring_available"] is False
    assert summary["verdict_scored_case_count"] == 0
    assert summary["unscored_verdict_case_count"] == 1
    assert summary["off_verdict_accuracy"] is None
    assert summary["on_verdict_accuracy"] is None
    assert summary["verdict_accuracy_delta"] is None
    assert summary["off_relation_accuracy"] == 1.0
