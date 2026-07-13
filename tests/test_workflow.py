import json
import sys
from types import SimpleNamespace

from agent_network.agents.builtin import MergeAgent
from agent_network.agents.base import parse_agent_review
from agent_network.config import load_config
from agent_network.llm import LiteLLMClient, StaticLLMClient
from agent_network.prompts import PromptRegistry
from agent_network.schemas import AgentReview, ReviewRequest
from agent_network.workflow import ReviewWorkflow


class FailingLLMClient:
    def complete(self, **kwargs) -> str:
        raise TimeoutError("simulated timeout")


class CountingLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, **kwargs) -> str:
        self.calls += 1
        return '{"summary":"Merged by model."}'


def test_merge_agent_combines_reviews() -> None:
    merged = MergeAgent().merge(
        [
            AgentReview(agent="fact", summary="Fact summary"),
            AgentReview(agent="security", summary="Security summary"),
            AgentReview(agent="logic", summary="Logic summary"),
        ]
    )

    assert merged.agent == "merge"
    assert "Fact summary" in merged.summary
    assert "Security summary" in merged.summary
    assert "Logic summary" in merged.summary
    assert merged.model == "local/deterministic"
    assert merged.provider == "local"


def test_merge_agent_calls_llm_when_model_is_configured() -> None:
    llm = CountingLLMClient()
    agent = MergeAgent(
        prompts=PromptRegistry("prompts"),
        llm=llm,
        model="deepseek-ai/DeepSeek-V4-Pro",
        provider="siliconflow",
        timeout_seconds=120,
    )

    merged = agent.merge([AgentReview(agent="fact", summary="Fact summary")])

    assert llm.calls == 1
    assert merged.summary.startswith("Structured merge completed")
    assert merged.model == "deepseek-ai/DeepSeek-V4-Pro"
    assert merged.provider == "siliconflow"
    assert "finish_reason" in merged.provider_response_audit
    assert "prompt_tokens" in merged.provider_response_audit
    assert "response_truncated" in merged.provider_response_audit


def test_review_workflow_runs_with_static_llm() -> None:
    payload = """
    {
      "summary": "Static review response.",
      "findings": [
        {
          "severity": "medium",
          "location": "Summary",
          "issue": "Needs support",
          "reason": "The claim lacks support.",
          "evidence_needed": "Benchmark data",
          "suggestion": "Add evidence.",
          "confidence": 0.7
        }
      ]
    }
    """
    workflow = ReviewWorkflow.from_llm(
        llm=StaticLLMClient(payload),
        prompts=PromptRegistry("prompts"),
    )

    result = workflow.run_sequential(ReviewRequest(markdown="# Report"))

    assert len(result.agent_reviews) == 4
    assert "Static review response." in result.summary
    assert len(result.findings) == 3


def test_review_workflow_runs_only_one_agent() -> None:
    payload = """
    {
      "summary": "Single agent response.",
      "findings": [
        {
          "severity": "low",
          "location": "Summary",
          "issue": "Needs detail",
          "reason": "The argument omits a required step.",
          "evidence_needed": "Design notes",
          "suggestion": "Add detail.",
          "confidence": 0.6
        }
      ]
    }
    """
    workflow = ReviewWorkflow.from_llm(
        llm=StaticLLMClient(payload),
        prompts=PromptRegistry("prompts"),
    )

    result = workflow.run_only(ReviewRequest(markdown="# Report"), "fact")

    assert len(result.agent_reviews) == 2
    assert result.agent_reviews[0].agent == "fact"
    assert len(result.findings) == 1


def test_review_workflow_records_agent_failure() -> None:
    workflow = ReviewWorkflow.from_llm(
        llm=FailingLLMClient(),
        prompts=PromptRegistry("prompts"),
    )

    result = workflow.run_only(ReviewRequest(markdown="# Report"), "security")

    assert result.agent_reviews[0].status == "failed"
    assert result.agent_reviews[0].error_type == "TimeoutError"
    assert result.agent_reviews[1].status == "skipped"
    assert result.agent_reviews[1].skip_reason == "no_valid_agent_findings"


def test_chinese_agent_failure_uses_chinese_status_text() -> None:
    workflow = ReviewWorkflow.from_llm(
        llm=FailingLLMClient(),
        prompts=PromptRegistry("prompts"),
    )

    result = workflow.run_only(ReviewRequest(markdown="# 中文报告", language="zh"), "logic")

    assert result.agent_reviews[0].summary == "Logic Agent 未完成。"
    assert "Logic Agent 状态为失败：TimeoutError。" in result.execution_notes


def test_long_report_profile_caps_full_workflow_at_four_model_calls(monkeypatch) -> None:
    calls = []
    payload = json.dumps(
        {
            "summary": "review summary",
            "findings": [
                {
                    "severity": "medium",
                    "location": "Summary",
                    "issue": "Needs evidence",
                    "reason": "The claim is unsupported.",
                    "evidence_needed": "Primary source",
                    "suggestion": "Add evidence",
                    "confidence": 0.8,
                }
            ],
        }
    )

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message={"content": payload})],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))
    config = load_config("configs/default.yaml").with_profile("long-report")
    llm = LiteLLMClient(
        default_model=config.default_model,
        retry_attempts=config.retry_attempts,
        model_options={},
    )
    workflow = ReviewWorkflow.from_config(llm=llm, prompts=PromptRegistry("prompts"), config=config)

    result = workflow.run(ReviewRequest(markdown="# Long report"))

    assert len(calls) == 4
    assert [call["max_tokens"] for call in calls] == [2400, 3200, 3200, 2400]
    assert [review.model_call_count for review in result.agent_reviews] == [1, 1, 1, 1]
    assert sum(review.retry_count for review in result.agent_reviews) == 0


def test_empty_specialist_results_skip_merge_without_model_call(monkeypatch) -> None:
    calls = []
    payload = json.dumps({"summary": "no findings", "findings": []})

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message={"content": payload})],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))
    config = load_config("configs/default.yaml").with_profile("long-report")
    llm = LiteLLMClient(default_model=config.default_model, retry_attempts=1)
    workflow = ReviewWorkflow.from_config(llm=llm, prompts=PromptRegistry("prompts"), config=config)

    result = workflow.run(ReviewRequest(markdown="# Long report", language="zh"))

    assert len(calls) == 3
    merge = result.agent_reviews[-1]
    assert merge.status == "skipped"
    assert merge.skip_reason == "no_valid_agent_findings"
    assert merge.model_call_count == 0
    assert sum(review.model_call_count for review in result.agent_reviews) == 3
    assert result.overall_status == "failed"


def test_parse_agent_review_extracts_structured_findings() -> None:
    review = parse_agent_review(
        agent="fact",
        content='{"summary":"ok","findings":[{"severity":"high","location":"L1","issue":"Bad claim","reason":"The claim lacks support.","evidence_needed":"Source","suggestion":"Fix it","confidence":0.91}]}',
    )

    assert review.summary == "ok"
    assert review.findings[0].confidence == 0.91
