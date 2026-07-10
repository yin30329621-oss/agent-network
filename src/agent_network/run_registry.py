"""Run registry and local reporting helpers."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from agent_network.config import AppConfig
from agent_network.schemas import ReviewResult, now_iso


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
    record = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "source_file": source_file,
        "profile": profile,
        "mode": mode,
        "output_directory": str(run_dir),
        "status": "completed",
        "total_elapsed_seconds": total_elapsed_seconds,
        "models": {
            agent: {
                "provider": config.provider_for_agent(agent),
                "model": config.model_for_agent(agent),
                "timeout_seconds": config.timeout_for_agent(agent),
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
