"""Run registry and local reporting helpers."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from agent_network.config import AppConfig
from agent_network.schemas import ReviewResult, determine_overall_status, now_iso


@dataclass(slots=True)
class RunRecord:
    run_id: str
    run_dir: Path
    review_json: Path
    review_md: Path
    run_json: Path


def register_run(
    *,
    result: ReviewResult,
    markdown_path: Path,
    json_path: Path,
    output_root: str | Path,
    source_file: str,
    mode: str,
    profile: str,
    config: AppConfig,
    started_at: str,
    completed_at: str,
    total_elapsed_seconds: float,
) -> RunRecord:
    run_id = f"run-{uuid4().hex[:12]}"
    root = Path(output_root)
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_md = run_dir / "review.md"
    run_json = run_dir / "review.json"
    run_meta = run_dir / "run.json"
    shutil.copy2(markdown_path, run_md)
    shutil.copy2(json_path, run_json)
    per_agent_call_counts = {
        review.agent: review.model_call_count for review in result.agent_reviews
    }
    overall_status = result.overall_status or determine_overall_status(result)
    record = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "source_file": source_file,
        "profile": profile,
        "mode": mode,
        "output_directory": str(run_dir),
        "status": overall_status,
        "overall_status": overall_status,
        "language": result.metadata.get("language"),
        "version": result.metadata.get("version"),
        "merged_findings_count": len(result.merged_findings),
        "disagreements_count": len(result.disagreements),
        "potential_duplicates_count": len(result.potential_duplicates),
        "total_elapsed_seconds": total_elapsed_seconds,
        "retry_attempts": config.retry_attempts,
        "configured_timeout_seconds": {
            agent: config.timeout_for_agent(agent)
            for agent in ("fact", "security", "logic", "merge")
        },
        "configured_max_tokens": {
            agent: config.max_tokens_for_agent(agent)
            for agent in ("fact", "security", "logic", "merge")
        },
        "total_model_call_count": sum(per_agent_call_counts.values()),
        "total_retry_count": sum(review.retry_count for review in result.agent_reviews),
        "per_agent_call_counts": per_agent_call_counts,
        "input_characters": result.metadata.get("input_characters"),
        "input_lines": result.metadata.get("input_lines"),
        "estimated_input_tokens": result.metadata.get("estimated_input_tokens"),
        "input_size_class": result.metadata.get("input_size_class"),
        "models": {
            agent: {
                "provider": config.provider_for_agent(agent),
                "model": config.model_for_agent(agent),
                "timeout_seconds": config.timeout_for_agent(agent),
                "max_tokens": config.max_tokens_for_agent(agent),
                "reasoning_mode": config.reasoning_mode_for_agent(agent),
                "json_mode": config.json_mode_for_agent(agent),
                "provider_capability_status": config.provider_capability_status_for_agent(agent),
            }
            for agent in ("fact", "security", "logic", "merge")
        },
        "agents": [
            {
                "agent": review.agent,
                "status": review.status,
                "provider": review.provider,
                "model": review.model,
                "elapsed_seconds": review.elapsed_seconds,
                "error_type": review.error_type,
                "error_message": review.error_message,
                "skip_reason": review.skip_reason,
                "model_call_count": review.model_call_count,
                "request_attempt_count": review.request_attempt_count,
                "retry_count": review.retry_count,
                "timeout_count": review.timeout_count,
                "request_started_at": review.request_started_at,
                "request_completed_at": review.request_completed_at,
                "last_error_type": review.last_error_type,
                "last_error_message": review.last_error_message,
                "configured_timeout_seconds": review.configured_timeout_seconds
                or config.timeout_for_agent(review.agent),
                "configured_max_tokens": review.configured_max_tokens
                or config.max_tokens_for_agent(review.agent),
                "effective_elapsed_seconds": review.effective_elapsed_seconds,
                "parse_attempts": review.parse_attempts,
                "repair_attempted": review.repair_attempted,
                "repair_status": review.repair_status,
                "parse_error_type": review.parse_error_type,
                "failure_stage": review.failure_stage,
                "raw_finding_count": review.raw_finding_count,
                "valid_finding_count": review.valid_finding_count,
                "rejected_finding_count": review.rejected_finding_count,
                "rejected_findings": review.rejected_findings,
                "reasoning_mode": config.reasoning_mode_for_agent(review.agent),
                "json_mode": config.json_mode_for_agent(review.agent),
                "provider_capability_status": config.provider_capability_status_for_agent(
                    review.agent
                ),
            }
            for review in result.agent_reviews
        ],
        "errors": [
            {"agent": review.agent, "error_type": review.error_type}
            for review in result.agent_reviews
            if review.error_type
        ],
        "review_json": str(run_json),
        "review_md": str(run_md),
    }
    atomic_write_json(run_meta, record)
    if mode == "real":
        atomic_write_json(root / "latest.json", record)
    elif not (root / "latest.json").exists():
        atomic_write_json(root / "latest.json", record)
    return RunRecord(run_id, run_dir, run_json, run_md, run_meta)


def load_latest(output_root: str | Path = "outputs") -> dict | None:
    latest = Path(output_root) / "latest.json"
    if not latest.exists():
        return None
    return json.loads(latest.read_text(encoding="utf-8"))


def atomic_write_json(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def baseline_from_review(review_json: str | Path, output: str | Path, config: AppConfig) -> Path:
    review_path = Path(review_json)
    if not review_path.exists():
        raise FileNotFoundError(f"Review JSON not found: {review_path}")
    data = json.loads(review_path.read_text(encoding="utf-8"))
    metadata = data.get("metadata", {})
    summary = data.get("summary", {})
    execution = data.get("execution", [])
    lines = [
        "# Agent Network Baseline v0.1",
        "",
        "## Version",
        "",
        "0.1.0",
        "",
        "## Date",
        "",
        metadata.get("timestamp") or now_iso(),
        "",
        "## Source Report",
        "",
        metadata.get("source_file", "unavailable"),
        "",
        "## Workflow",
        "",
        "Fact -> Security -> Logic -> Merge",
        "",
        "## Models",
        "",
        "| Agent | Provider | Model | Timeout |",
        "| --- | --- | --- | ---: |",
    ]
    for agent in ("fact", "security", "logic", "merge"):
        lines.append(
            f"| {agent} | {config.provider_for_agent(agent)} | "
            f"{config.model_for_agent(agent)} | {config.timeout_for_agent(agent)}s |"
        )
    lines.extend(
        ["", "## Runtime", "", "| Agent | Status | Elapsed | Error |", "| --- | --- | ---: | --- |"]
    )
    for item in execution:
        elapsed = item.get("elapsed_seconds") or 0
        lines.append(
            f"| {item.get('agent')} | {item.get('status')} | {elapsed:.1f}s | {item.get('error_type') or ''} |"
        )
    total = metadata.get("total_elapsed_seconds", "unavailable")
    lines.extend(
        [
            "",
            "## Total Runtime",
            "",
            f"{total}s",
            "",
            "## Output Files",
            "",
            f"- {review_path}",
            "",
            "## Finding Statistics",
            "",
            f"- Critical: {summary.get('critical', 0)}",
            f"- High: {summary.get('high', 0)}",
            f"- Medium: {summary.get('medium', 0)}",
            f"- Low: {summary.get('low', 0)}",
            f"- Info: {summary.get('info', 0)}",
            f"- Merged findings: {len(data.get('merged_findings', []))}",
            f"- Disagreements: {len(data.get('disagreements', []))}",
            f"- Unique findings: {len([f for f in data.get('merged_findings', []) if len(f.get('supporting_agents', [])) == 1])}",
            "",
            "## Tests",
            "",
            "unavailable",
            "",
            "## Current Features",
            "",
            "- Multi-agent review workflow",
            "- Structured output parsing and retry",
            "- Merge Judge, deduplication, baseline, and stats",
            "",
            "## Known Limitations",
            "",
            "- Semantic deduplication is rule-based in v0.2.",
            "",
            "## Next Milestone",
            "",
            "Improve plugin and integration boundaries.",
        ]
    )
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path
