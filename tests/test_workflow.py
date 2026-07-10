from agent_network.agents.builtin import MergeAgent
from agent_network.agents.base import parse_agent_review
from agent_network.llm import StaticLLMClient
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
    assert merged.summary == "Merged by model."
    assert merged.model == "deepseek-ai/DeepSeek-V4-Pro"
    assert merged.provider == "siliconflow"


def test_review_workflow_runs_with_static_llm() -> None:
    payload = """
    {
      "summary": "Static review response.",
      "findings": [
        {
          "severity": "medium",
          "location": "Summary",
          "issue": "Needs support",
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
    assert "did not complete" in result.summary


def test_parse_agent_review_extracts_structured_findings() -> None:
    review = parse_agent_review(
        agent="fact",
        content='{"summary":"ok","findings":[{"severity":"high","location":"L1","issue":"Bad claim","evidence_needed":"Source","suggestion":"Fix it","confidence":0.91}]}',
    )

    assert review.summary == "ok"
    assert review.findings[0].confidence == 0.91
