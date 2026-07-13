import json
from datetime import date

from agent_network.agents import FactAgent, MergeAgent
from agent_network.outputs import to_json, to_markdown
from agent_network.prompts import PromptRegistry
from agent_network.schemas import (
    AgentReview,
    ReviewFinding,
    ReviewRequest,
    ReviewResult,
    Severity,
    determine_overall_status,
)


def finding(agent: str, severity: Severity, issue: str) -> ReviewFinding:
    return ReviewFinding(
        agent=agent,
        severity=severity,
        location="第6章 CVE 分析",
        issue=issue,
        reason="该时效性事实需要官方来源核验。",
        evidence_needed="核验 NVD 与 Rancher 官方安全公告。",
        suggestion="核验后修订结论。",
        confidence=0.8,
    )


def degraded_result() -> ReviewResult:
    fact = AgentReview(
        agent="fact",
        summary="事实审查需要外部核验。",
        findings=[finding("fact", Severity.CRITICAL, "CVE-2026-41053 的真实性缺少依据。")],
    )
    security = AgentReview(
        agent="security",
        summary="Security Agent call completed, but structured parsing failed.",
        status="parse_failed",
        error_type="ValueError",
    )
    logic = AgentReview(
        agent="logic",
        summary="逻辑审查发现同一 CVE 结论证据不足。",
        findings=[finding("logic", Severity.MEDIUM, "CVE-2026-41053 需要核验后再下结论。")],
    )
    merge_agent = MergeAgent()
    merge = merge_agent.merge([fact, security, logic], language="zh")
    result = ReviewResult(
        summary=merge.summary,
        agent_reviews=[fact, security, logic, merge],
        findings=merge.findings,
        merged_findings=merge_agent.last_merged_findings,
        disagreements=merge_agent.last_disagreements,
        potential_duplicates=merge_agent.last_potential_duplicates,
        execution_notes=["Security Agent 调用完成，但结构化解析失败。"],
        metadata={"language": "zh"},
    )
    result.overall_status = determine_overall_status(result)
    return result


def test_degraded_status_and_security_parse_failure_are_prominent() -> None:
    result = degraded_result()

    markdown = to_markdown(result)
    payload = json.loads(to_json(result))

    assert result.overall_status == "degraded"
    assert payload["overall_status"] == "degraded"
    assert "总体状态：降级" in markdown
    assert (
        "总体评估：本次审查为降级结果，部分 Agent 未产生可用结果，"
        "当前结论不完整，不建议直接作为最终安全判断。"
    ) in markdown
    assert "| Agent | 模型 | 服务商 | 状态 | 耗时 | 错误类型 |" in markdown
    assert "结构化解析失败，本 Agent 未产生可用业务结果" in markdown
    assert "| Model |" not in markdown
    assert "```json" not in markdown


def test_failed_without_findings_never_claims_no_issues() -> None:
    result = ReviewResult(
        summary="failed",
        agent_reviews=[
            AgentReview(agent="fact", summary="失败", status="failed"),
            AgentReview(
                agent="merge",
                summary="已跳过",
                status="skipped",
                skip_reason="no_valid_agent_findings",
            ),
        ],
        metadata={"language": "zh"},
        overall_status="failed",
    )

    markdown = to_markdown(result)

    assert (
        "总体评估：本次审查失败，专业 Agent 未产生足够的可用结果，无法评估报告中的安全风险。"
    ) in markdown
    assert "未生成可用综合审查结果。" in markdown
    assert "未发现实质性问题" not in markdown
    assert "报告无风险" not in markdown
    assert "Merge Agent：已跳过" in markdown
    assert "原因：没有可用的专业 Agent 审查结果" in markdown


def test_success_without_findings_is_the_only_no_issue_case() -> None:
    result = ReviewResult(
        summary="success",
        agent_reviews=[AgentReview(agent="merge", summary="done")],
        metadata={"language": "zh"},
        overall_status="success",
    )

    markdown = to_markdown(result)

    assert ("总体评估：本次审查已成功完成，未发现符合当前审查规则的实质性问题。") in markdown


def test_success_with_findings_reports_exact_count() -> None:
    result = degraded_result()
    result.overall_status = "success"

    markdown = to_markdown(result)

    assert "总体评估：本次审查已完成，共发现 1 项需要关注的问题。" in markdown


def test_chinese_cve_dedup_and_disagreement_share_one_source() -> None:
    result = degraded_result()
    payload = json.loads(to_json(result))
    markdown = to_markdown(result)

    assert len(payload["merged_findings"]) == 1
    merged = payload["merged_findings"][0]
    assert set(merged["supporting_agents"]) == {"fact", "logic"}
    assert merged["dissenting_agents"] == ["logic"]
    assert merged["original_severities"] == [
        {
            "agent": "fact",
            "finding_id": result.findings[0].id,
            "severity": "critical",
        },
        {
            "agent": "logic",
            "finding_id": result.findings[1].id,
            "severity": "medium",
        },
    ]
    assert len(payload["disagreements"]) == 1
    assert payload["disagreements"][0]["merged_finding_id"] == merged["id"]
    assert merged["id"] in markdown
    assert "存在分歧 Agent：logic" in markdown
    assert markdown.count("CVE-2026-41053 的真实性缺少依据。") == 1


class FactBoundaryLLM:
    def __init__(self) -> None:
        self.system_prompt = ""

    def complete(self, *, system_prompt, user_prompt, model=None, timeout_seconds=None):
        self.system_prompt = system_prompt
        return json.dumps(
            {
                "summary": "该 CVE 需要核验。",
                "findings": [
                    {
                        "severity": "high",
                        "location": "第6章",
                        "issue": "CVE-2026-41053 可能不存在。",
                        "reason": "模型记忆中没有该编号。",
                        "evidence_needed": "查询公开记录。",
                        "reference": None,
                        "suggestion": "删除该 CVE 和对应版本。",
                        "confidence": 0.9,
                    }
                ],
            },
            ensure_ascii=False,
        )


def test_fact_current_date_and_external_verification_boundary() -> None:
    llm = FactBoundaryLLM()
    agent = FactAgent(llm=llm, prompts=PromptRegistry("prompts"))

    review = agent.review(ReviewRequest(markdown="报告包含 CVE-2026-41053。", language="zh"))

    assert f"Current date: {date.today().isoformat()}" in llm.system_prompt
    assert "A CVE year equal to the current year is not evidence" in llm.system_prompt
    assert review.findings[0].evidence_needed.startswith("needs_external_verification:")
    assert review.findings[0].suggestion != "删除该 CVE 和对应版本。"
    assert review.findings[0].suggestion.startswith("先通过可验证的官方来源核实")
    assert "官方来源" in review.findings[0].suggestion


class TruncatedMergeLLM:
    def __init__(self) -> None:
        self.last_response_audit = {
            "finish_reason": "length",
            "content_is_none": False,
            "content_length": 18,
            "reasoning_content_length": 0,
            "extracted_field": "message.content",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        }

    def complete(self, **kwargs) -> str:
        return '{"summary":"残缺的模型输'


def test_merge_truncation_is_audited_without_partial_output() -> None:
    llm = TruncatedMergeLLM()
    merge_agent = MergeAgent(
        llm=llm,
        prompts=PromptRegistry("prompts"),
        model="zai-org/GLM-5.2",
        provider="siliconflow",
    )
    fact = AgentReview(
        agent="fact",
        summary="事实摘要。",
        findings=[finding("fact", Severity.MEDIUM, "完整的问题描述不得被截断。")],
    )

    merge = merge_agent.merge([fact], language="zh")
    result = ReviewResult(
        summary=merge.summary,
        agent_reviews=[fact, merge],
        findings=merge.findings,
        merged_findings=merge_agent.last_merged_findings,
        metadata={"language": "zh"},
    )
    markdown = to_markdown(result)
    audit = merge.provider_response_audit

    assert merge.status == "truncated"
    assert merge.error_type == "ResponseTruncated"
    assert audit["finish_reason"] == "length"
    assert audit["content_length"] == 18
    assert audit["prompt_tokens"] == 100
    assert audit["completion_tokens"] == 20
    assert audit["total_tokens"] == 120
    assert audit["response_truncated"] is True
    assert "残缺的模型输" not in markdown
    assert "完整的问题描述不得被截断。" in markdown
    assert determine_overall_status(result) == "degraded"


def test_failed_when_merge_fails_or_no_business_findings() -> None:
    failed_merge = ReviewResult(
        summary="merge failed",
        agent_reviews=[AgentReview(agent="merge", summary="failed", status="failed")],
    )
    empty = ReviewResult(
        summary="empty",
        agent_reviews=[AgentReview(agent="merge", summary="completed")],
    )

    assert determine_overall_status(failed_merge) == "failed"
    assert determine_overall_status(empty) == "failed"


def test_same_agent_merge_never_creates_self_disagreement() -> None:
    first = finding("fact", Severity.HIGH, "CVE-2026-41053 真实性需要核验。")
    second = finding("fact", Severity.INFO, "CVE-2026-41053 编号需要核验。")
    merge_agent = MergeAgent()

    merge_agent.merge(
        [AgentReview(agent="fact", summary="事实摘要。", findings=[first, second])],
        language="zh",
    )

    merged = merge_agent.last_merged_findings[0]
    assert merged.supporting_agents == ["fact"]
    assert merged.dissenting_agents == []
    assert merged.original_severities == [
        {"agent": "fact", "finding_id": first.id, "severity": "high"},
        {"agent": "fact", "finding_id": second.id, "severity": "info"},
    ]
    assert merge_agent.last_disagreements == []


def test_potential_duplicates_are_not_disagreements() -> None:
    first = finding(
        "fact",
        Severity.MEDIUM,
        "CVE-2024-58269 的修复版本为 Rancher v2.12.3，但未提供官方依据。",
    )
    second = finding(
        "fact",
        Severity.HIGH,
        "修复版本声明（Rancher v2.14.2、v2.13.6、v2.12.3）可能尚未发布或不存在。",
    )
    merge_agent = MergeAgent()

    merge_agent.merge(
        [AgentReview(agent="fact", summary="事实摘要。", findings=[first, second])],
        language="zh",
    )

    assert merge_agent.last_disagreements == []
    assert len(merge_agent.last_merged_findings) == 2
    assert len(merge_agent.last_potential_duplicates) == 1


def test_markdown_renders_potential_duplicates_separately() -> None:
    result = ReviewResult(
        summary="疑似重复",
        potential_duplicates=[
            {
                "finding_ids": ["finding-a", "finding-b"],
                "issues": ["问题甲", "问题乙"],
                "score": 0.68,
            }
        ],
        metadata={"language": "zh"},
    )

    markdown = to_markdown(result)

    assert "## 疑似重复项" in markdown
    assert "finding-a, finding-b" in markdown
    assert "问题甲 / 问题乙" in markdown
    assert "相似度：0.68" in markdown
    assert "## 分歧说明" in markdown
