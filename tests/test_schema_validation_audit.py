import json

from agent_network.agents.base import parse_agent_review
from agent_network.workflow.review import _execution_notes


def _finding(**overrides) -> dict:
    finding = {
        "severity": "medium",
        "location": "Section 1",
        "issue": "The claim lacks evidence.",
        "reason": "The conclusion is not supported by the report.",
        "evidence_needed": "Primary documentation.",
        "reference": None,
        "suggestion": "Add a primary source.",
        "confidence": 0.8,
    }
    finding.update(overrides)
    return finding


def _response(*findings: dict) -> str:
    return json.dumps({"summary": "reviewed", "findings": list(findings)})


def test_nullable_display_fields_are_normalized_without_agent_failure() -> None:
    review = parse_agent_review(
        "fact",
        _response(_finding(location=None, evidence_needed=None, reference=None, suggestion=None)),
    )

    assert review.status == "completed"
    assert review.findings[0].location == ""
    assert review.findings[0].evidence_needed == ""
    assert review.findings[0].reference is None
    assert review.findings[0].suggestion == ""


def test_invalid_core_field_rejects_only_that_finding() -> None:
    audit = {"provider_success": True, "last_error_type": None}
    review = parse_agent_review(
        "fact",
        _response(_finding(issue=None), _finding(issue="A valid issue.")),
        provider_response_audit=audit,
    )

    assert review.status == "completed_with_warnings"
    assert [item.issue for item in review.findings] == ["A valid issue."]
    assert review.raw_finding_count == 2
    assert review.valid_finding_count == 1
    assert review.rejected_finding_count == 1
    assert review.rejected_findings[0]["index"] == 0
    assert review.rejected_findings[0]["error_type"] == "schema_validation_error"
    assert review.parse_error_type == "schema_validation_error"
    assert review.failure_stage == "schema_validation"
    assert review.provider_response_audit["provider_success"] is True
    assert review.provider_response_audit["last_error_type"] is None


def test_reason_null_rejects_finding_without_exposing_input() -> None:
    review = parse_agent_review(
        "logic",
        _response(_finding(reason=None)),
        provider_response_audit={"provider_success": True},
    )

    assert review.status == "parse_failed"
    assert review.failure_stage == "schema_validation"
    assert review.rejected_finding_count == 1
    assert "input_value" not in review.rejected_findings[0]["error_message"]
    assert "Provider 调用成功" in _execution_notes([review], "zh")[0]


def test_top_level_schema_error_is_parse_failed() -> None:
    review = parse_agent_review("security", '{"summary":"bad","findings":null}')

    assert review.status == "parse_failed"
    assert review.parse_error_type == "schema_validation_error"
    assert review.failure_stage == "schema_validation"
    assert review.repair_attempted is False


def test_invalid_json_and_empty_response_have_distinct_audit_types() -> None:
    invalid = parse_agent_review("security", "not json")
    empty = parse_agent_review("security", "")

    assert invalid.parse_error_type == "json_decode_error"
    assert empty.parse_error_type == "empty_response"
    assert invalid.failure_stage == "json_decode"


def test_truncated_invalid_json_is_classified_separately() -> None:
    review = parse_agent_review(
        "security",
        '{"summary":"cut off",',
        provider_response_audit={"response_truncated": True},
    )

    assert review.parse_error_type == "truncated_response"
