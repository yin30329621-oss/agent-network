import json

from agent_network.config import load_config
from agent_network.run_registry import register_run
from agent_network.schemas import AgentReview, ReviewResult


def audited_review(
    agent: str, calls: int, retries: int, timeouts: int, parse_attempts: int = 0
) -> AgentReview:
    review = AgentReview(
        agent=agent,
        summary="summary",
        parse_attempts=parse_attempts,
        repair_attempted=parse_attempts > 1,
    )
    review.apply_request_audit(
        {
            "model_call_count": calls,
            "request_attempt_count": calls,
            "retry_count": retries,
            "timeout_count": timeouts,
            "request_started_at": "2026-07-10T00:00:00+00:00",
            "request_completed_at": "2026-07-10T00:00:01+00:00",
            "last_error_type": "TimeoutError" if timeouts else None,
            "last_error_message": "simulated timeout" if timeouts else None,
            "configured_timeout_seconds": 120,
            "effective_elapsed_seconds": 1.0,
        }
    )
    return review


def test_run_registry_sums_model_calls_without_parse_attempts(tmp_path) -> None:
    reviews = [
        audited_review("fact", 1, 0, 0),
        audited_review("security", 1, 0, 0, parse_attempts=2),
        audited_review("logic", 1, 0, 0),
        audited_review("merge", 1, 0, 0),
    ]
    result = ReviewResult(
        summary="summary",
        agent_reviews=reviews,
        metadata={
            "language": "zh",
            "version": "0.2.0",
            "input_characters": 25_356,
            "input_lines": 426,
            "estimated_input_tokens": 15_000,
            "input_size_class": "long",
        },
    )
    review_md = tmp_path / "review.md"
    review_json = tmp_path / "review.json"
    review_md.write_text("# Review\n", encoding="utf-8")
    review_json.write_text("{}\n", encoding="utf-8")

    record = register_run(
        result=result,
        markdown_path=review_md,
        json_path=review_json,
        output_root=tmp_path / "outputs",
        source_file="reports/sample.md",
        mode="mock",
        profile="long-report",
        config=load_config("configs/default.yaml").with_profile("long-report"),
        started_at="2026-07-10T00:00:00+00:00",
        completed_at="2026-07-10T00:00:05+00:00",
        total_elapsed_seconds=5.0,
    )

    payload = json.loads(record.run_json.read_text(encoding="utf-8"))
    assert payload["profile"] == "long-report"
    assert payload["retry_attempts"] == 1
    assert payload["total_model_call_count"] == 4
    assert payload["total_retry_count"] == 0
    assert payload["per_agent_call_counts"] == {
        "fact": 1,
        "security": 1,
        "logic": 1,
        "merge": 1,
    }
    assert payload["configured_timeout_seconds"] == {
        "fact": 600,
        "security": 240,
        "logic": 600,
        "merge": 240,
    }
    assert payload["configured_max_tokens"] == {
        "fact": 2400,
        "security": 3200,
        "logic": 3200,
        "merge": 2400,
    }
    assert payload["input_characters"] == 25_356
    assert payload["estimated_input_tokens"] == 15_000
    assert payload["input_size_class"] == "long"
    assert payload["language"] == "zh"
    assert payload["version"] == "0.2.0"
    assert payload["overall_status"] == payload["status"]
    assert payload["merged_findings_count"] == 0
    assert payload["disagreements_count"] == 0
    assert payload["potential_duplicates_count"] == 0
    assert payload["models"]["security"]["reasoning_mode"] == "provider_default"
    assert payload["models"]["security"]["json_mode"] == "disabled"
    assert payload["models"]["security"]["provider_capability_status"] == "unverified_for_model"
    security = next(item for item in payload["agents"] if item["agent"] == "security")
    assert security["model_call_count"] == 1
    assert security["parse_attempts"] == 2
    assert security["repair_attempted"] is True
    assert security["configured_max_tokens"] == 3200
