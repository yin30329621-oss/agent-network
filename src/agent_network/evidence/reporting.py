"""JSON, Markdown, and run metadata output for offline verification."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_network import __version__
from agent_network.evidence.schemas import VerificationStatus
from agent_network.evidence.verifier import VerificationReport


STATUS_ZH = {
    VerificationStatus.VERIFIED.value: "已核验",
    VerificationStatus.CONTRADICTED.value: "与证据冲突",
    VerificationStatus.PARTIALLY_VERIFIED.value: "部分核验",
    VerificationStatus.NOT_VERIFIED.value: "未核验",
    VerificationStatus.CONFLICTING_SOURCES.value: "来源冲突",
    VerificationStatus.VERSION_MISMATCH.value: "版本不匹配",
    VerificationStatus.INSUFFICIENT_EVIDENCE.value: "证据不足",
    VerificationStatus.NOT_APPLICABLE.value: "不适用",
}


def to_json(report: VerificationReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def to_markdown(report: VerificationReport) -> str:
    evidence_by_id = {item.evidence_id: item for item in report.evidence}
    claim_by_id = {item.claim_id: item for item in report.claims}
    lines = [
        "# 离线证据核验报告",
        "",
        "> **本次使用离线 fixture，并非真实官方核验结果。**",
        "",
        "## 核验摘要",
        "",
        f"- Claim 数量：{report.claim_count}",
        f"- Evidence 数量：{report.evidence_count}",
        f"- 模型调用次数：{report.metadata.get('model_call_count', 0)}",
        f"- 网络请求次数：{report.metadata.get('network_request_count', 0)}",
        "",
        "## 状态统计",
        "",
        "| 状态 | 数量 |",
        "| --- | ---: |",
    ]
    for status in VerificationStatus:
        lines.append(f"| {STATUS_ZH[status.value]} | {report.status_counts[status.value]} |")
    lines.extend(["", "## Claim 核验结果", ""])
    for index, result in enumerate(report.verification_results, start=1):
        claim = claim_by_id[result.claim_id]
        evidence_ids = [
            *result.supporting_evidence_ids,
            *result.contradicting_evidence_ids,
        ]
        if not evidence_ids:
            evidence_ids = [
                detail.evidence_id
                for detail in result.match_details
                if detail.evidence_id in evidence_by_id
            ]
        lines.extend(
            [
                f"### {index}. `{claim.claim_id}`",
                "",
                f"- 原文：{claim.original_text}",
                f"- 章节：{claim.section}（第 {claim.line_start}-{claim.line_end} 行）",
                f"- 类型：`{claim.claim_type.value}`",
                f"- 产品 / 组件：`{claim.product}` / `{claim.component}`",
                f"- 版本范围：{claim.version_scope.raw}",
                f"- 核验状态：**{STATUS_ZH[result.verification_status.value]}**",
                f"- 判定原因：{result.explanation}",
                f"- 官方值：{result.official_value or '未提供'}",
                f"- 是否需要人工复核：{'是' if result.requires_human_review else '否'}",
                "",
            ]
        )
        if evidence_ids:
            lines.extend(["#### Evidence", ""])
            for evidence_id in dict.fromkeys(evidence_ids):
                item = evidence_by_id[evidence_id]
                lines.extend(
                    [
                        f"- Evidence ID：`{item.evidence_id}`",
                        f"  - 来源：{item.source_title}",
                        f"  - URL：{item.source_url}",
                        f"  - 官方域名（fixture 声明）：`{item.official_domain}`",
                        f"  - 检索时间：{item.retrieved_at.isoformat()}",
                        f"  - 产品版本：{item.product_version or '未知'}",
                        f"  - 证据片段：{item.excerpt}",
                        f"  - 片段哈希：`{item.excerpt_hash}`",
                    ]
                )
        else:
            lines.extend(["- Evidence：未找到可用证据。", ""])
    lines.extend(["", "## 执行说明", ""])
    lines.extend(f"- {note}" for note in report.execution_notes)
    return "\n".join(lines).strip() + "\n"


def write_report(
    report: VerificationReport,
    output_dir: str | Path,
    output_format: str = "both",
    fixture_path: str | Path | None = None,
    claim_filter: str | None = None,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    if output_format in {"json", "both"}:
        paths["json"] = output / "verification.json"
        paths["json"].write_text(to_json(report), encoding="utf-8")
    if output_format in {"markdown", "both"}:
        paths["markdown"] = output / "verification.md"
        paths["markdown"].write_text(to_markdown(report), encoding="utf-8")
    run_id = f"evidence-run-{uuid4().hex[:12]}"
    run = {
        "run_id": run_id,
        "version": __version__,
        "mode": "offline_fixture",
        "started_at": report.metadata.get("generated_at"),
        "completed_at": datetime.now(UTC).isoformat(),
        "fixture_path": str(fixture_path) if fixture_path is not None else None,
        "claim_filter": claim_filter,
        "claim_count": report.claim_count,
        "evidence_count": report.evidence_count,
        "status_counts": report.status_counts,
        "model_call_count": report.metadata.get("model_call_count", 0),
        "network_request_count": report.metadata.get("network_request_count", 0),
        "output_files": {name: str(path) for name, path in paths.items()},
    }
    paths["run"] = output / "run.json"
    paths["run"].write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths
