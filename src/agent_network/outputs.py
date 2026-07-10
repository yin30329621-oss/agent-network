"""Review output serializers."""

from __future__ import annotations

import json
from pathlib import Path

from agent_network.merge import merge_findings
from agent_network.schemas import ReviewResult


def to_json(result: ReviewResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def to_markdown(result: ReviewResult) -> str:
    if not result.merged_findings and result.findings:
        result.merged_findings, _ = merge_findings(result.findings)
    summary = result.summary_stats or result.to_dict()["summary"]
    lines = ["# Technical Report Review", "", "## Executive Summary", ""]
    lines.append(f"- Overall assessment: {summary['overall_assessment']}")
    lines.append(
        "- Severity counts: "
        f"Critical {summary['critical']}, High {summary['high']}, "
        f"Medium {summary['medium']}, Low {summary['low']}, Info {summary['info']}"
    )
    completed = [item.agent for item in result.agent_reviews if item.status == "completed"]
    degraded = [item.agent for item in result.agent_reviews if item.status != "completed"]
    lines.append(f"- Completed agents: {', '.join(completed) if completed else 'none'}")
    lines.append(f"- Degraded agents: {', '.join(degraded) if degraded else 'none'}")
    lines.append(f"- Human review recommended: {'yes' if summary['needs_human_review'] else 'no'}")
    lines.extend(["", "## Agent Execution Status", ""])
    lines.append("| Agent | Model | Provider | Status | Elapsed | Error |")
    lines.append("| --- | --- | --- | --- | ---: | --- |")
    for review in result.agent_reviews:
        elapsed = f"{review.elapsed_seconds:.1f}s" if review.elapsed_seconds is not None else ""
        lines.append(
            f"| {review.agent} | {review.model or ''} | {review.provider or ''} | "
            f"{review.status} | {elapsed} | {review.error_type or ''} |"
        )

    lines.extend(["", "## Consolidated Findings", ""])
    if not result.merged_findings:
        lines.append("No consolidated findings.")
    for index, finding in enumerate(result.merged_findings, start=1):
        lines.append(f"### {index}. {finding.title}")
        lines.append("")
        lines.append(f"- Severity: {finding.merged_severity.value}")
        lines.append(f"- Location: {finding.location}")
        lines.append(f"- Supporting Agents: {', '.join(finding.supporting_agents)}")
        lines.append(f"- Confidence: {finding.confidence:.2f}")
        lines.append(f"- Reason: {finding.reason or finding.decision_reason}")
        lines.append(f"- Evidence Needed: {finding.combined_evidence_needed or 'Not specified'}")
        refs = ", ".join(finding.combined_references) if finding.combined_references else ""
        lines.append(f"- References: {refs}")
        lines.append(f"- Suggested Revision: {finding.final_suggestion}")
        lines.append(f"- Disagreement / Judge Decision: {finding.decision_reason}")
        lines.append(f"- Human Review Required: {'yes' if finding.needs_human_review else 'no'}")
        lines.append("")

    disagreements = [item for item in result.disagreements if item.get("dissenting_agents")]
    lines.extend(["## Agent Disagreements", ""])
    if disagreements:
        for item in disagreements:
            lines.append(
                f"- `{item['merged_finding_id']}` dissenting agents: "
                f"{', '.join(item['dissenting_agents'])}; {item['decision_reason']}"
            )
    else:
        lines.append("No severity disagreements.")

    unique = [finding for finding in result.merged_findings if len(finding.supporting_agents) == 1]
    lines.extend(["", "## Unique Findings", ""])
    if unique:
        for finding in unique:
            lines.append(f"- {finding.title} ({finding.supporting_agents[0]})")
    else:
        lines.append("No single-agent-only findings.")

    lines.extend(["", "## Execution Notes", ""])
    if result.execution_notes:
        for note in result.execution_notes:
            lines.append(f"- {note}")
    else:
        lines.append("No execution issues.")
    return "\n".join(lines).strip() + "\n"


def write_outputs(result: ReviewResult, output_dir: str | Path) -> tuple[Path, Path]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    markdown_path = path / "review.md"
    json_path = path / "review.json"
    markdown_path.write_text(to_markdown(result), encoding="utf-8")
    json_path.write_text(to_json(result), encoding="utf-8")
    return markdown_path, json_path
