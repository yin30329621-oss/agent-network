from agent_network.agents.base import LLMReviewerAgent, parse_agent_review
from agent_network.prompts import PromptTemplate


VALID_JSON = """{
  "summary": "ok",
  "findings": [
    {
      "severity": "HIGH",
      "location": "Summary",
      "issue": "Uses latest tag",
      "reason": "Mutable tags are not reproducible.",
      "evidence_needed": "Image release policy",
      "reference": null,
      "suggestion": "Pin immutable image digests.",
      "confidence": 2
    }
  ]
}"""


class SequenceLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    def complete(self, **kwargs) -> str:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def test_parse_valid_json_normalizes_fields() -> None:
    review = parse_agent_review("security", VALID_JSON, provider="siliconflow", model="model")

    assert review.status == "completed"
    assert review.findings[0].severity.value == "high"
    assert review.findings[0].confidence == 1.0
    assert review.findings[0].provider == "siliconflow"


def test_parse_code_fence_json() -> None:
    review = parse_agent_review("security", f"```json\n{VALID_JSON}\n```")

    assert review.status == "completed"
    assert review.findings[0].issue == "Uses latest tag"


def test_parse_json_with_explanatory_text() -> None:
    review = parse_agent_review("security", f"Here is the result:\n{VALID_JSON}\nThanks")

    assert review.status == "completed"


def test_missing_fields_get_defaults() -> None:
    review = parse_agent_review("fact", '{"summary":"ok","findings":[{"issue":"Needs proof"}]}')

    assert review.findings[0].evidence_needed == "Not specified"
    assert review.findings[0].severity.value == "info"


def test_non_json_retry_success() -> None:
    llm = SequenceLLM([VALID_JSON.replace('"', "“")])
    agent = LLMReviewerAgent(
        name="security",
        prompt=PromptTemplate(id="p", version="1", role="r", template="prompt"),
        llm=llm,
        model="m",
        provider="p",
    )

    review = agent.review(type("Req", (), {"source_name": "sample.md", "markdown": "# report"})())

    assert llm.calls == 1
    assert review.status == "completed"
    assert review.parse_attempts == 2
    assert review.repair_attempted is True
    assert review.repair_status == "succeeded"


def test_non_json_retry_failure() -> None:
    llm = SequenceLLM(["not json", "still not json"])
    agent = LLMReviewerAgent(
        name="security",
        prompt=PromptTemplate(id="p", version="1", role="r", template="prompt"),
        llm=llm,
    )

    review = agent.review(type("Req", (), {"source_name": "sample.md", "markdown": "# report"})())

    assert llm.calls == 1
    assert review.status == "parse_failed"
    assert not review.findings
    assert review.parse_attempts == 2
    assert review.repair_attempted is True
    assert review.repair_status == "failed"
