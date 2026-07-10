"""Built-in MVP reviewer agents."""

from __future__ import annotations

import json

from agent_network.agents.base import LLMReviewerAgent
from agent_network.llm import LLMClient
from agent_network.merge import merge_findings
from agent_network.prompts import PromptRegistry
from agent_network.schemas import AgentReview, ReviewFinding, ReviewRequest


class FactAgent(LLMReviewerAgent):
    def __init__(
        self,
        *,
        llm: LLMClient,
        prompts: PromptRegistry,
        model: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        super().__init__(
            name="fact",
            prompt=prompts.load("fact_agent"),
            llm=llm,
            model=model,
            provider=provider,
            timeout_seconds=timeout_seconds,
        )


class SecurityAgent(LLMReviewerAgent):
    def __init__(
        self,
        *,
        llm: LLMClient,
        prompts: PromptRegistry,
        model: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        super().__init__(
            name="security",
            prompt=prompts.load("security_agent"),
            llm=llm,
            model=model,
            provider=provider,
            timeout_seconds=timeout_seconds,
        )


class LogicAgent(LLMReviewerAgent):
    def __init__(
        self,
        *,
        llm: LLMClient,
        prompts: PromptRegistry,
        model: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        super().__init__(
            name="logic",
            prompt=prompts.load("logic_agent"),
            llm=llm,
            model=model,
            provider=provider,
            timeout_seconds=timeout_seconds,
        )


class MergeAgent:
    """Merge individual agent reviews into a single review."""

    name = "merge"

    def __init__(
        self,
        *,
        prompts: PromptRegistry | None = None,
        llm: LLMClient | None = None,
        model: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self.prompts = prompts
        self.llm = llm
        self.model = model
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.last_merged_findings = []
        self.last_disagreements = []

    def merge(self, reviews: list[AgentReview]) -> AgentReview:
        findings: list[ReviewFinding] = []
        summaries: list[str] = []
        for review in reviews:
            if review.status == "completed":
                summaries.append(f"## {review.agent.title()} Agent\n\n{review.summary}")
            else:
                summaries.append(
                    f"## {review.agent.title()} Agent\n\n"
                    f"Status: {review.status}. Model `{review.model}` did not complete. "
                    f"Error: {review.error_type}."
                )
            findings.extend(review.findings)
        merged_findings, potential_duplicates = merge_findings(findings)
        self.last_merged_findings = merged_findings
        self.last_disagreements = [
            {
                "merged_finding_id": finding.id,
                "supporting_agents": finding.supporting_agents,
                "dissenting_agents": finding.dissenting_agents,
                "original_severities": finding.original_severities,
                "decision_reason": finding.decision_reason,
            }
            for finding in merged_findings
            if finding.dissenting_agents
        ]
        self.last_disagreements.extend(
            {"type": "potential_duplicate", **item} for item in potential_duplicates
        )
        if self.llm and self.model and self.prompts:
            prompt = self.prompts.load("merge_agent")
            payload = {
                "agent_reviews": [review.to_dict() for review in reviews],
                "findings": [finding.to_dict() for finding in findings],
                "merged_findings": [finding.to_dict() for finding in merged_findings],
            }
            content = self.llm.complete(
                system_prompt=prompt.render(),
                user_prompt=json.dumps(payload, ensure_ascii=False, indent=2),
                model=self.model,
                timeout_seconds=self.timeout_seconds,
            )
            summary = _extract_merge_summary(content)
            return AgentReview(
                agent=self.name,
                summary=summary,
                findings=findings,
                model=self.model,
                provider=self.provider,
            )
        summary = (
            "# Technical Report Review\n\n"
            f"Reviewed by {len(reviews)} agents. "
            f"Total findings: {len(findings)}.\n\n" + "\n\n".join(summaries)
        )
        return AgentReview(
            agent=self.name,
            summary=summary,
            findings=findings,
            model="local/deterministic",
            provider="local",
        )

    def review(self, request: ReviewRequest) -> AgentReview:
        raise NotImplementedError("MergeAgent expects agent reviews, not raw Markdown.")


def _extract_merge_summary(content: str) -> str:
    stripped = content.strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end >= start:
            try:
                data = json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                return stripped
        else:
            return stripped
    if isinstance(data, dict):
        return str(data.get("summary") or data.get("markdown") or stripped)
    return stripped
