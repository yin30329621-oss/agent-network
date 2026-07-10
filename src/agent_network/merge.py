"""Deterministic finding deduplication and judge helpers."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from uuid import uuid4

from agent_network.schemas import (
    FindingStatus,
    MergedFinding,
    ReviewFinding,
    SEVERITY_RANK,
    Severity,
)

KEYWORD_GROUPS = {
    "latest image tag": {"latest", "image", "tag"},
    "cluster-admin": {"cluster-admin", "cluster", "admin", "rbac"},
    "run as root": {"root", "runasroot", "runasnonroot"},
    "resource limits": {"resource", "limits", "requests", "cpu", "memory"},
    "secrets env vars": {"secret", "secrets", "environment", "env"},
    "zero downtime": {"zero", "downtime", "rollingupdate", "upgrade"},
}


def merge_findings(findings: list[ReviewFinding]) -> tuple[list[MergedFinding], list[dict]]:
    groups: list[list[ReviewFinding]] = []
    potential_duplicates: list[dict] = []
    for finding in findings:
        matched = False
        for group in groups:
            score = _similarity(finding, group[0])
            if score >= 0.72:
                group.append(finding)
                matched = True
                break
            if score >= 0.55:
                potential_duplicates.append(
                    {
                        "finding_ids": [finding.id, group[0].id],
                        "issues": [finding.issue, group[0].issue],
                        "score": round(score, 2),
                    }
                )
        if not matched:
            groups.append([finding])
    merged = [_merge_group(group) for group in groups]
    return merged, potential_duplicates


def _merge_group(group: list[ReviewFinding]) -> MergedFinding:
    severities = {item.agent: item.severity.value for item in group}
    merged_severity = max((item.severity for item in group), key=lambda item: SEVERITY_RANK[item])
    agents = sorted({item.agent for item in group})
    dissenting = sorted(
        {
            item.agent
            for item in group
            if len({finding.severity for finding in group}) > 1 and item.severity != merged_severity
        }
    )
    title = _title_for(group[0])
    evidence = sorted({item.evidence_needed for item in group if item.evidence_needed})
    references = sorted({item.reference for item in group if item.reference})
    suggestions = [item.suggestion for item in group if item.suggestion]
    confidence = sum(item.confidence for item in group) / len(group)
    status = FindingStatus.VALID if len(group) > 1 else FindingStatus.UNIQUE
    return MergedFinding(
        id=f"merged-{uuid4().hex[:12]}",
        title=title,
        location=group[0].location,
        supporting_agents=agents,
        dissenting_agents=dissenting,
        source_finding_ids=[item.id for item in group],
        original_severities=severities,
        merged_severity=merged_severity,
        decision_reason=_decision_reason(group, merged_severity, dissenting),
        reason=_combine_text([item.reason for item in group]),
        combined_evidence_needed=_combine_text(evidence),
        combined_references=references,
        final_suggestion=_combine_text(suggestions),
        confidence=max(0.0, min(1.0, confidence)),
        needs_human_review=bool(
            dissenting or merged_severity in {Severity.HIGH, Severity.CRITICAL}
        ),
        status=status,
    )


def _similarity(left: ReviewFinding, right: ReviewFinding) -> float:
    left_key = _canonical_key(left)
    right_key = _canonical_key(right)
    if left_key and left_key == right_key:
        return 1.0
    left_text = _normalize(f"{left.location} {left.issue}")
    right_text = _normalize(f"{right.location} {right.issue}")
    ratio = SequenceMatcher(None, left_text, right_text).ratio()
    left_tokens = set(left_text.split())
    right_tokens = set(right_text.split())
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return max(ratio, overlap)


def _canonical_key(finding: ReviewFinding) -> str | None:
    text = _normalize(f"{finding.location} {finding.issue} {finding.reason}")
    tokens = set(text.split())
    for key, expected in KEYWORD_GROUPS.items():
        if len(tokens & expected) >= min(2, len(expected)):
            return key
    return None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _title_for(finding: ReviewFinding) -> str:
    issue = finding.issue.strip().rstrip(".")
    return issue[:90] or "Untitled finding"


def _combine_text(values: list[str]) -> str:
    unique: list[str] = []
    for value in values:
        clean = value.strip()
        if clean and clean not in unique:
            unique.append(clean)
    return " ".join(unique)


def _decision_reason(
    group: list[ReviewFinding], merged_severity: Severity, dissenting_agents: list[str]
) -> str:
    if dissenting_agents:
        return (
            f"Severity set to {merged_severity.value} because the highest-impact agent rationale "
            "indicates greater publication risk; dissenting severities are preserved for review."
        )
    if len(group) > 1:
        return f"Severity set to {merged_severity.value} because multiple agents reported the same issue."
    return f"Severity kept as {merged_severity.value} from the originating agent."
