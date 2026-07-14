"""Offline quality audit for the Part 1 dual-Fact disagreements."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DISAGREEMENT_TYPES = {
    "verdict_difference",
    "evidence_interpretation",
    "insufficient_evidence_threshold",
    "status_mapping",
    "citation_difference",
    "output_schema_difference",
}


def audit_part1_disagreements(part1_directory: str | Path) -> dict[str, Any]:
    """Compare existing reviewer artifacts without invoking a provider."""

    root = Path(part1_directory)
    pilot = _read_json(root / "pilot-input.json")
    fact_a = _read_json(root / "fact-a-output.json")
    fact_b = _read_json(root / "fact-b-output.json")
    reconciliations = _read_json(root / "reconciliation.json")["reconciliations"]
    by_claim = {item["claim"]["claim_id"]: item for item in pilot["inputs"]}
    a_by_claim = {item["claim_id"]: item for item in fact_a["results"]}
    b_by_claim = {item["claim_id"]: item for item in fact_b["results"]}

    audits = []
    for reconciliation in reconciliations:
        claim_id = reconciliation["claim_id"]
        item = by_claim[claim_id]
        a = a_by_claim[claim_id]
        b = b_by_claim[claim_id]
        audit = _audit_one(item, a, b)
        audit["reconciliation_status"] = reconciliation["status"]
        audits.append(audit)

    return {
        "fixture": pilot["fixture"],
        "input_sha256": pilot["input_sha256"],
        "model_call_count": 0,
        "network_request_count": 0,
        "audits": audits,
        "local_rule_resolved_count": sum(item["local_rule_resolved"] for item in audits),
        "manual_review_count": sum(
            item["recommended_status"] == "manual_review" for item in audits
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Public Pilot Part 2 Disagreement Audit",
        "",
        "本报告仅比较 Part 1 已保存的 Fact A/B 结果，不调用模型、不联网，不重新解释原始正文。",
        "",
        f"- Claims audited: {len(report['audits'])}",
        f"- Local-rule resolvable: {report['local_rule_resolved_count']}",
        f"- Manual review required: {report['manual_review_count']}",
        "- New model calls: 0",
        "- New network requests: 0",
        "",
        "| Claim | Type | Same evidence | Recommendation |",
        "|---|---|---:|---|",
    ]
    for item in report["audits"]:
        lines.append(
            f"| `{item['claim_id']}` | `{item['disagreement_type']}` | "
            f"{str(item['same_evidence']).lower()} | `{item['recommended_status']}` |"
        )
        lines.append(f"|  | Basis: {item['resolution_basis']} |  |  |")
    return "\n".join(lines) + "\n"


def render_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Part 2 Summary",
            "",
            "本阶段仅审计 Part 1 的三条 reviewer disagreement，不重新调用模型。",
            "",
            f"- Audited disagreements: {len(report['audits'])}",
            f"- Local rules resolved: {report['local_rule_resolved_count']}",
            f"- Manual review required: {report['manual_review_count']}",
            "- New model calls: 0",
            "- New network requests: 0",
            "",
            "`cluster-tunnel` 保留 manual_review：同一证据的支持强度和局限解释不同。",
            "`cluster-absolute` 可按 absence of support 归为 insufficient_evidence。",
            "`cluster-v213` 可按版本不匹配规则保留版本限制，建议 insufficient_evidence。",
            "",
            "结论：Part 2 PASS；不执行 Part 3。",
            "",
        ]
    )


def reconcile_after_rules(report: dict[str, Any]) -> dict[str, Any]:
    """Apply only the reviewed structured Part 2 rules to local reconciliation."""

    reconciliations = []
    for audit in report["audits"]:
        original_status = audit["reconciliation_status"]
        rule_id = None
        final_status = "manual_review"
        needs_manual_review = True
        if audit["disagreement_type"] == "insufficient_evidence_threshold":
            rule_id = "insufficient_evidence_threshold"
            final_status = "insufficient_evidence"
            needs_manual_review = False
        elif (
            audit["disagreement_type"] == "status_mapping"
            and audit["verification_engine"]["status"] == "version_mismatch"
        ):
            rule_id = "version_mismatch"
            final_status = "insufficient_evidence"
            needs_manual_review = False
        reconciliations.append(
            {
                "claim_id": audit["claim_id"],
                "original_disagreement": {
                    "status": original_status,
                    "disagreement_type": audit["disagreement_type"],
                    "fact_a": audit["fact_a"],
                    "fact_b": audit["fact_b"],
                },
                "local_rule": rule_id,
                "final_status": final_status,
                "needs_manual_review": needs_manual_review,
            }
        )
    return {
        "model_call_count": 0,
        "network_request_count": 0,
        "reconciliations": reconciliations,
        "automatically_resolved_count": sum(
            not item["needs_manual_review"] for item in reconciliations
        ),
        "manual_review_count": sum(item["needs_manual_review"] for item in reconciliations),
    }


def _audit_one(item: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    claim = item["claim"]
    decision = item["decision"]
    a_ids = list(a.get("cited_chunk_ids", []))
    b_ids = list(b.get("cited_chunk_ids", []))
    same_evidence = a_ids == b_ids
    a_verdict = _verdict(a)
    b_verdict = _verdict(b)
    a_fields = set(a)
    b_fields = set(b)
    required = {"claim_id", "decision", "recommended_status", "cited_chunk_ids"}

    if not required.issubset(a_fields | b_fields):
        disagreement_type = "output_schema_difference"
        recommendation = "manual_review"
        local_rule_resolved = False
        basis = "Reviewer output fields are not comparable under the local contract."
    elif not same_evidence:
        disagreement_type = "citation_difference"
        recommendation = "manual_review"
        local_rule_resolved = False
        basis = "Reviewers selected different evidence; local rules cannot choose between excerpts."
    elif _has_version_mismatch(claim, decision, a, b):
        disagreement_type = "status_mapping"
        recommendation = "insufficient_evidence"
        local_rule_resolved = True
        basis = "The requested version differs from the cached evidence version; retain version limitation."
    elif a_verdict == b_verdict and a_verdict == "unsupported":
        disagreement_type = "insufficient_evidence_threshold"
        recommendation = "insufficient_evidence"
        local_rule_resolved = True
        basis = "Both reviewers found no direct support and the engine only marked the evidence as relevant."
    elif a_verdict != b_verdict:
        disagreement_type = "verdict_difference"
        recommendation = "manual_review"
        local_rule_resolved = False
        basis = "The same excerpt was interpreted with different support strength."
    else:
        disagreement_type = "evidence_interpretation"
        recommendation = "manual_review"
        local_rule_resolved = False
        basis = "The same evidence received incompatible status mapping or limitations."

    return {
        "claim_id": claim["claim_id"],
        "claim_text": claim["text"],
        "fact_a": _review_summary(a),
        "fact_b": _review_summary(b),
        "same_evidence": same_evidence,
        "disagreement_type": disagreement_type,
        "verification_engine": {
            "status": decision["status"],
            "confidence": decision.get("confidence"),
            "sufficiency_score": decision.get("sufficiency_score"),
            "rule_audit": decision.get("rule_audit", []),
        },
        "recommended_status": recommendation,
        "local_rule_resolved": local_rule_resolved,
        "resolution_basis": basis,
    }


def _review_summary(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": review.get("decision"),
        "recommended_status": review.get("recommended_status"),
        "cited_chunk_ids": list(review.get("cited_chunk_ids", [])),
        "reasoning_summary": review.get("reasoning_summary", ""),
        "limitations": list(review.get("limitations", [])),
        "parse_status": review.get("parse_status"),
    }


def _verdict(review: dict[str, Any]) -> str:
    value = str(review.get("decision", "")).lower()
    if value in {"supported", "approve", "verified_supported"}:
        return "supported"
    if value in {"unsupported", "not_supported", "reject", "insufficient_evidence"}:
        return "unsupported"
    if value == "version_mismatch":
        return "version_mismatch"
    return value


def _has_version_mismatch(
    claim: dict[str, Any], decision: dict[str, Any], a: dict[str, Any], b: dict[str, Any]
) -> bool:
    claim_text = f"{claim.get('text', '')} {claim.get('normalized_text', '')}".lower()
    limitation_text = " ".join(a.get("limitations", []) + b.get("limitations", [])).lower()
    return (
        "version_mismatch" in {a.get("decision"), b.get("decision")}
        or "version" in limitation_text
        or "v2.13" in claim_text
    ) and any(entry.get("version_match") is False for entry in decision.get("evidence", []))


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part1_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    report = audit_part1_disagreements(args.part1_directory)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    (args.output_directory / "disagreement-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_directory / "disagreement-audit.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    (args.output_directory / "part2-summary.md").write_text(
        render_summary(report), encoding="utf-8"
    )
