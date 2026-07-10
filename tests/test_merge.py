from agent_network.merge import merge_findings
from agent_network.schemas import ReviewFinding, Severity


def finding(agent: str, issue: str, severity: Severity = Severity.MEDIUM) -> ReviewFinding:
    return ReviewFinding(
        agent=agent,
        severity=severity,
        location="Deployment",
        issue=issue,
        reason="reason",
        evidence_needed="evidence",
        suggestion="suggestion",
        confidence=0.8,
    )


def test_dedup_latest_image_tag() -> None:
    merged, _ = merge_findings(
        [
            finding("fact", "The report recommends the latest image tag."),
            finding("logic", "Using latest image tags weakens release reasoning."),
        ]
    )

    assert len(merged) == 1
    assert set(merged[0].supporting_agents) == {"fact", "logic"}


def test_similar_but_not_same_is_not_forced_to_merge() -> None:
    merged, potential = merge_findings(
        [
            finding("fact", "The report lacks a citation for autoscaler behavior."),
            finding("logic", "The conclusion about zero downtime skips readiness conditions."),
        ]
    )

    assert len(merged) == 2
    assert isinstance(potential, list)


def test_severity_conflict_preserves_dissenting_agents() -> None:
    merged, _ = merge_findings(
        [
            finding("fact", "Cluster-admin access is too broad.", Severity.HIGH),
            finding("logic", "The cluster-admin conclusion needs more support.", Severity.MEDIUM),
        ]
    )

    assert merged[0].merged_severity == Severity.HIGH
    assert "logic" in merged[0].dissenting_agents
