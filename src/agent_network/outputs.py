"""Review output serializers."""

from __future__ import annotations

import json
from pathlib import Path

from agent_network.language import is_chinese_language
from agent_network.merge import merge_findings
from agent_network.schemas import ReviewResult, determine_overall_status

ZH_SEVERITY = {
    "info": "信息",
    "low": "低危",
    "medium": "中危",
    "high": "高危",
    "critical": "严重",
}


def to_json(result: ReviewResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def to_markdown(result: ReviewResult) -> str:
    if not result.merged_findings and result.findings:
        result.merged_findings, _ = merge_findings(
            result.findings, language=str(result.metadata.get("language") or "en")
        )
    chinese = is_chinese_language(result.metadata.get("language")) or _result_has_chinese(result)
    summary = result.summary_stats or result.to_dict()["summary"]
    overall_status = result.overall_status or determine_overall_status(result)
    result.overall_status = overall_status
    completed = [item.agent for item in result.agent_reviews if item.status == "completed"]
    degraded = [item.agent for item in result.agent_reviews if item.status != "completed"]
    if chinese:
        status_label = _display_status(overall_status, True)
        lines = ["# 审查报告", "", f"> **总体状态：{status_label}**", ""]
        if overall_status == "degraded":
            lines.extend(
                [
                    "> 本次审查为降级结果，部分 Agent 结果缺失或不完整，"
                    "不建议作为最终安全结论直接采用。",
                    "",
                ]
            )
        lines.extend(["## 执行状态", ""])
        lines.append(
            f"- 总体评估：{_overall_assessment_zh(overall_status, len(result.merged_findings))}"
        )
        lines.append(
            "- 风险统计："
            f"严重 {summary['critical']}，高危 {summary['high']}，"
            f"中危 {summary['medium']}，低危 {summary['low']}，信息 {summary['info']}"
        )
        lines.append(f"- 已完成 Agent：{', '.join(completed) if completed else '无'}")
        lines.append(f"- 异常或降级 Agent：{', '.join(degraded) if degraded else '无'}")
        lines.append(f"- 是否建议人工复核：{'是' if summary['needs_human_review'] else '否'}")
        lines.extend(
            [
                "",
                "## 审查摘要",
                "",
                f"本次结构化审查形成 {len(result.merged_findings)} 条综合发现，"
                f"总体状态为{status_label}。",
            ]
        )
    else:
        lines = ["# Technical Report Review", "", "## Executive Summary", ""]
        lines.append(f"- Overall assessment: {summary['overall_assessment']}")
        lines.append(
            "- Severity counts: "
            f"Critical {summary['critical']}, High {summary['high']}, "
            f"Medium {summary['medium']}, Low {summary['low']}, Info {summary['info']}"
        )
        lines.append(f"- Completed agents: {', '.join(completed) if completed else 'none'}")
        lines.append(f"- Degraded agents: {', '.join(degraded) if degraded else 'none'}")
        lines.append(
            f"- Human review recommended: {'yes' if summary['needs_human_review'] else 'no'}"
        )
        lines.extend(["", "## Agent Execution Status", ""])
    if chinese:
        lines.append("| Agent | 模型 | 服务商 | 状态 | 耗时 | 错误类型 |")
    else:
        lines.append("| Agent | Model | Provider | Status | Elapsed | Error |")
    lines.append("| --- | --- | --- | --- | ---: | --- |")
    for review in result.agent_reviews:
        elapsed = f"{review.elapsed_seconds:.1f}s" if review.elapsed_seconds is not None else ""
        lines.append(
            f"| {review.agent} | {review.model or ''} | {review.provider or ''} | "
            f"{_display_status(review.status, chinese)} | {elapsed} | "
            f"{review.error_type or ''} |"
        )

    lines.extend(["", "## 综合审查结果" if chinese else "## Consolidated Findings", ""])
    if not result.merged_findings:
        if chinese and overall_status == "success":
            lines.append("未发现符合当前审查规则的综合问题。")
        else:
            lines.append(
                "未生成可用综合审查结果。" if chinese else "No usable consolidated results."
            )
    for index, finding in enumerate(result.merged_findings, start=1):
        severity = _display_severity(finding.merged_severity.value, chinese)
        heading = f"{severity}问题" if chinese else "Finding"
        lines.append(f"### {index}. {heading}")
        lines.append("")
        lines.append(f"- {'严重程度' if chinese else 'Severity'}: {severity}")
        lines.append(f"- {'位置' if chinese else 'Location'}: {finding.location}")
        lines.append(f"- {'问题' if chinese else 'Issue'}: {finding.title}")
        lines.append(
            f"- {'支持 Agent' if chinese else 'Supporting Agents'}: "
            f"{', '.join(finding.supporting_agents)}"
        )
        lines.append(
            f"- {'存在分歧 Agent' if chinese else 'Dissenting Agents'}: "
            f"{', '.join(finding.dissenting_agents) if finding.dissenting_agents else ('无' if chinese else 'none')}"
        )
        lines.append(f"- {'置信度' if chinese else 'Confidence'}: {finding.confidence:.2f}")
        lines.append(
            f"- {'原因' if chinese else 'Reason'}: {finding.reason or finding.decision_reason}"
        )
        evidence = finding.combined_evidence_needed or ("未说明" if chinese else "Not specified")
        lines.append(f"- {'建议补充证据' if chinese else 'Evidence Needed'}: {evidence}")
        refs = ", ".join(finding.combined_references) if finding.combined_references else ""
        lines.append(
            f"- {'参考依据' if chinese else 'References'}: {refs or ('未提供' if chinese else '')}"
        )
        lines.append(
            f"- {'修复建议' if chinese else 'Suggested Revision'}: {finding.final_suggestion}"
        )
        lines.append(
            f"- {'分歧决策' if chinese else 'Disagreement / Judge Decision'}: {finding.decision_reason}"
        )
        lines.append(
            f"- {'是否需要人工复核' if chinese else 'Human Review Required'}: "
            f"{'是' if finding.needs_human_review and chinese else 'yes' if finding.needs_human_review else '否' if chinese else 'no'}"
        )
        lines.append("")

    if chinese:
        lines.extend(["## 各 Agent 审查结果", ""])
        for review in result.agent_reviews:
            lines.append(f"### {review.agent.title()} Agent")
            lines.append("")
            if review.agent == "merge" and review.status == "skipped":
                lines.append("- Merge Agent：已跳过")
                lines.append("- 原因：没有可用的专业 Agent 审查结果")
            else:
                lines.append(f"- 状态：{_display_status(review.status, True)}")
            if review.agent == "merge" and review.status != "skipped":
                lines.append("- 摘要：结构化合并状态见执行状态，合并结果见综合审查结果。")
            elif review.status == "parse_failed":
                lines.append("- 摘要：结构化解析失败，本 Agent 未产生可用业务结果。")
            elif review.agent != "merge":
                lines.append(f"- 摘要：{_clean_summary(review.summary)}")
            lines.append("")

    disagreements = [item for item in result.disagreements if item.get("dissenting_agents")]
    lines.extend(["## 疑似重复项" if chinese else "## Potential Duplicates", ""])
    if result.potential_duplicates:
        for item in result.potential_duplicates:
            finding_ids = ", ".join(item.get("finding_ids", []))
            issues = " / ".join(item.get("issues", []))
            score = item.get("score")
            if chinese:
                lines.append(f"- Finding IDs：{finding_ids}；问题摘要：{issues}；相似度：{score}")
            else:
                lines.append(f"- Finding IDs: {finding_ids}; issues: {issues}; score: {score}")
    else:
        lines.append("未发现疑似重复项。" if chinese else "No potential duplicates.")

    lines.append("")
    lines.extend(["## 分歧说明" if chinese else "## Agent Disagreements", ""])
    if disagreements:
        for item in disagreements:
            if chinese:
                lines.append(
                    f"- `{item['merged_finding_id']}`：存在分歧 Agent："
                    f"{', '.join(item['dissenting_agents'])}；{item['decision_reason']}"
                )
            else:
                lines.append(
                    f"- `{item['merged_finding_id']}` dissenting agents: "
                    f"{', '.join(item['dissenting_agents'])}; {item['decision_reason']}"
                )
    else:
        lines.append("未发现严重程度分歧。" if chinese else "No severity disagreements.")

    lines.extend(["", "## 执行说明" if chinese else "## Execution Notes", ""])
    if result.execution_notes:
        for note in result.execution_notes:
            lines.append(f"- {_translate_execution_note(note) if chinese else note}")
    else:
        lines.append("无执行异常。" if chinese else "No execution issues.")
    return "\n".join(lines).strip() + "\n"


def write_outputs(result: ReviewResult, output_dir: str | Path) -> tuple[Path, Path]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    markdown_path = path / "review.md"
    json_path = path / "review.json"
    markdown_path.write_text(to_markdown(result), encoding="utf-8")
    json_path.write_text(to_json(result), encoding="utf-8")
    return markdown_path, json_path


def _display_severity(severity: str, chinese: bool) -> str:
    return ZH_SEVERITY.get(severity, severity) if chinese else severity


def _result_has_chinese(result: ReviewResult) -> bool:
    text = " ".join(
        [
            finding.title + finding.reason + finding.final_suggestion
            for finding in result.merged_findings
        ]
    )
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _translate_execution_note(note: str) -> str:
    if "structured parsing failed" in note:
        return note.replace(
            "Agent call completed but structured parsing failed.",
            "Agent 调用完成，但结构化解析失败。",
        )
    if "Agent status is" in note:
        return note.replace("Agent status is", "Agent 状态为")
    return note


def _display_status(status: str, chinese: bool) -> str:
    if not chinese:
        return status
    return {
        "success": "成功",
        "degraded": "降级",
        "failed": "失败",
        "completed": "已完成",
        "completed_with_warnings": "已完成（有警告）",
        "parse_failed": "解析失败",
        "truncated": "输出截断",
        "skipped": "已跳过",
        "valid": "有效",
    }.get(status, status)


def _overall_assessment_zh(overall_status: str, finding_count: int) -> str:
    if overall_status == "success" and finding_count > 0:
        return f"本次审查已完成，共发现 {finding_count} 项需要关注的问题。"
    if overall_status == "success":
        return "本次审查已成功完成，未发现符合当前审查规则的实质性问题。"
    if overall_status == "degraded":
        return (
            "本次审查为降级结果，部分 Agent 未产生可用结果，当前结论不完整，"
            "不建议直接作为最终安全判断。"
        )
    return "本次审查失败，专业 Agent 未产生足够的可用结果，无法评估报告中的安全风险。"


def _clean_summary(summary: str) -> str:
    if "```" in summary or summary.lstrip().startswith("{"):
        return "Agent 返回了非预期的结构化摘要，已从 Markdown 中省略。"
    return " ".join(summary.split()) or "未提供摘要。"
