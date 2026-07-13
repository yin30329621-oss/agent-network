import json

from agent_network.outputs import to_json, to_markdown
from agent_network.prompts import PromptRegistry
from agent_network.schemas import AgentReview, ReviewRequest, ReviewResult
from agent_network.workflow import ReviewWorkflow


class ChineseCountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system_prompt, user_prompt, model=None, timeout_seconds=None):
        self.calls += 1
        assert "Simplified Chinese" in system_prompt
        if "Fact Agent" in system_prompt:
            return json.dumps(
                {
                    "summary": "事实审查发现 Rancher 架构描述需要补充来源。",
                    "findings": [
                        {
                            "severity": "medium",
                            "location": "Rancher 架构",
                            "issue": "Rancher Server 与 Cluster Agent 的关系缺少官方依据。",
                            "reason": "缺少来源会影响读者判断 Kubernetes 管理链路是否准确。",
                            "evidence_needed": "需要 Rancher 官方文档和 Kubernetes API 访问说明。",
                            "reference": "CVE-2023-32197",
                            "suggestion": (
                                "补充 Rancher Server、Cluster Agent、API 和 RBAC 的官方引用，"
                                "保留 CVE-2023-32197、https://example.invalid/api/v1、"
                                "kubectl get pods 和 /etc/rancher/config.yaml。"
                            ),
                            "confidence": 0.86,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        if "Security Agent" in system_prompt:
            return json.dumps(
                {
                    "summary": "安全审查发现 Rancher 报告缺少边界说明。",
                    "findings": [
                        {
                            "severity": "high",
                            "location": "Cluster Agent 通信",
                            "issue": "未说明 Cluster Agent 到 Rancher Server 的 HTTPS WebSocket 安全边界。",
                            "reason": "需要明确 API、RBAC 和 Kubernetes 资源访问权限。",
                            "evidence_needed": "需要 RBAC 策略、网络路径和 Rancher 官方说明。",
                            "reference": "",
                            "suggestion": "补充 HTTPS、WebSocket、RBAC 和 Kubernetes API 的安全控制。",
                            "confidence": 0.9,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        if "Logic Agent" in system_prompt:
            return json.dumps(
                {
                    "summary": "逻辑审查发现结论跳跃。",
                    "findings": [
                        {
                            "severity": "medium",
                            "location": "安全结论",
                            "issue": "不能仅凭 HTTPS 推导 Rancher 整体安全。",
                            "reason": "传输加密不等于 API 授权和 RBAC 配置正确。",
                            "evidence_needed": "需要补充权限、审计和 Kubernetes 资源范围。",
                            "reference": "",
                            "suggestion": "分别说明传输安全、认证授权和审计控制。",
                            "confidence": 0.88,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {"summary": "# 审查报告\n\n综合审查结果需要人工复核。"}, ensure_ascii=False
        )


def test_chinese_review_keeps_schema_and_technical_terms() -> None:
    llm = ChineseCountingLLM()
    workflow = ReviewWorkflow.from_llm(llm=llm, prompts=PromptRegistry("prompts"))
    workflow.merge_agent.model = "zai-org/GLM-5.2"
    workflow.merge_agent.provider = "siliconflow"
    request = ReviewRequest(
        markdown="这是一份 Rancher 中文报告，讨论 Kubernetes、Cluster Agent、Rancher Server、API、RBAC、HTTPS 和 CVE-2023-32197。",
        source_name="rancher.md",
        language="zh-CN",
    )

    result = workflow.run(request)
    result.metadata["language"] = "zh-CN"
    payload = json.loads(to_json(result))
    markdown = to_markdown(result)

    assert llm.calls == 4
    assert payload["overall_status"] == "success"
    assert "本次审查已完成" in payload["summary"]["overall_assessment"]
    assert "High-risk issues" not in payload["summary"]["overall_assessment"]
    assert "issue" in payload["agent_reviews"][0]["findings"][0]
    assert "suggestion" in payload["agent_reviews"][0]["findings"][0]
    assert set(payload) == {
        "metadata",
        "overall_status",
        "execution",
        "summary",
        "merged_findings",
        "agent_reviews",
        "disagreements",
        "potential_duplicates",
        "execution_notes",
        "findings",
    }
    assert payload["agent_reviews"][1]["findings"][0]["severity"] == "high"
    assert "Rancher Server" in payload["agent_reviews"][0]["findings"][0]["suggestion"]
    assert "Kubernetes API" in payload["agent_reviews"][1]["findings"][0]["suggestion"]
    assert "CVE-2023-32197" in payload["agent_reviews"][0]["findings"][0]["reference"]
    suggestion = payload["agent_reviews"][0]["findings"][0]["suggestion"]
    assert "https://example.invalid/api/v1" in suggestion
    assert "kubectl get pods" in suggestion
    assert "/etc/rancher/config.yaml" in suggestion
    assert "# 审查报告" in markdown
    assert "## 执行状态" in markdown
    assert "## 审查摘要" in markdown
    assert "## 综合审查结果" in markdown
    assert "## 各 Agent 审查结果" in markdown
    assert "## 分歧说明" in markdown
    assert "## 执行说明" in markdown
    assert "建议补充证据" in markdown
    assert "参考依据" in markdown
    assert "支持 Agent" in markdown
    assert "存在分歧 Agent" in markdown
    assert "高危" in markdown
    assert "Kubernetes" in markdown
    assert "```json" not in markdown


def test_prompts_include_consistent_chinese_instruction() -> None:
    expected = (
        "The input document may be written in Simplified Chinese. If it is, return all "
        "human-readable review content in Simplified Chinese; otherwise use the input "
        "document language. Keep JSON field names, severity enum values, CVE identifiers,"
    )
    registry = PromptRegistry("prompts")

    for name in ("fact_agent", "security_agent", "logic_agent", "merge_agent"):
        assert expected in registry.load(name).template.replace("\n", " ")


def test_security_and_logic_prompts_enforce_long_report_boundaries() -> None:
    registry = PromptRegistry("prompts")
    security = registry.load("security_agent").template
    logic = registry.load("logic_agent").template

    assert "at most 3 findings" in security
    assert 'Start the response with "{"' in security
    assert "reasoning" in security
    assert "Limit the review to structure" in logic
    assert "needs_external_verification:" in logic
    assert "Do not invent CVSS vectors" in logic


def test_parse_failed_is_not_rendered_as_business_finding() -> None:
    result = ReviewResult(
        summary="结构化解析失败，需要人工检查执行状态。",
        agent_reviews=[
            AgentReview(
                agent="security",
                summary="Security Agent 调用完成，但结构化解析失败。",
                status="parse_failed",
                error_type="JSONDecodeError",
            )
        ],
        execution_notes=["Security Agent 调用完成，但结构化解析失败。"],
        metadata={"language": "zh"},
    )

    markdown = to_markdown(result)

    assert "未生成可用综合审查结果。" in markdown
    assert "未发现实质性问题" not in markdown
    assert "### 1." not in markdown


class EnglishLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, system_prompt, user_prompt, model=None, timeout_seconds=None):
        self.calls += 1
        assert "The input document is written in Simplified Chinese" not in system_prompt
        if "Merge Agent" in system_prompt:
            return json.dumps({"summary": "English merged review summary."})
        return json.dumps({"summary": "English review summary.", "findings": []})


def test_english_mode_remains_english() -> None:
    llm = EnglishLLM()
    workflow = ReviewWorkflow.from_llm(llm=llm, prompts=PromptRegistry("prompts"))
    workflow.merge_agent.model = "zai-org/GLM-5.2"
    result = workflow.run(ReviewRequest(markdown="An English Rancher report.", language="en"))
    result.metadata["language"] = "en"

    markdown = to_markdown(result)

    assert llm.calls == 3
    assert result.agent_reviews[-1].status == "skipped"
    assert markdown.startswith("# Technical Report Review")
    assert "# 审查报告" not in markdown
