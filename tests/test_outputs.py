from agent_network.outputs import to_json, to_markdown
from agent_network.schemas import ReviewFinding, ReviewResult, Severity


def test_review_result_serializes_to_json() -> None:
    result = ReviewResult(
        summary="Review summary",
        findings=[
            ReviewFinding(
                agent="security",
                severity=Severity.HIGH,
                location="Security",
                issue="Unsafe recommendation",
                evidence_needed="RBAC policy",
                suggestion="Use a safer default.",
                confidence=0.9,
            )
        ],
    )

    payload = to_json(result)

    assert '"summary": {' in payload
    assert '"severity": "high"' in payload


def test_review_result_serializes_to_markdown() -> None:
    result = ReviewResult(
        summary="Review summary",
        findings=[
            ReviewFinding(
                agent="fact",
                severity=Severity.LOW,
                location="Summary",
                issue="Needs citation",
                evidence_needed="Primary source",
                suggestion="Add a citation.",
                confidence=0.8,
            )
        ],
    )

    markdown = to_markdown(result)

    assert markdown.startswith("# Technical Report Review")
    assert "## Consolidated Findings" in markdown
    assert "Needs citation" in markdown
    assert "Evidence Needed: Primary source" in markdown
    assert "```json" not in markdown
