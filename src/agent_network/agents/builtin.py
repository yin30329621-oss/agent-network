"""Built-in MVP reviewer agents."""

from __future__ import annotations

import json

from agent_network.agents.base import LLMReviewerAgent
from agent_network.language import ZH_REVIEW_INSTRUCTION, is_chinese_language
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
        max_tokens: int | None = None,
    ) -> None:
        super().__init__(
            name="fact",
            prompt=prompts.load("fact_agent"),
            llm=llm,
            model=model,
            provider=provider,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
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
        max_tokens: int | None = None,
    ) -> None:
        super().__init__(
            name="security",
            prompt=prompts.load("security_agent"),
            llm=llm,
            model=model,
            provider=provider,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
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
        max_tokens: int | None = None,
    ) -> None:
        super().__init__(
            name="logic",
            prompt=prompts.load("logic_agent"),
            llm=llm,
            model=model,
            provider=provider,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
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
        max_tokens: int | None = None,
    ) -> None:
        self.prompts = prompts
        self.llm = llm
        self.model = model
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.last_merged_findings = []
        self.last_disagreements = []
        self.last_potential_duplicates = []

    def merge(self, reviews: list[AgentReview], language: str = "en") -> AgentReview:
        findings: list[ReviewFinding] = []
        summaries: list[str] = []
        for review in reviews:
            if review.status in {"completed", "completed_with_warnings"}:
                summaries.append(f"## {review.agent.title()} Agent\n\n{review.summary}")
            else:
                summaries.append(
                    f"## {review.agent.title()} Agent\n\n"
                    f"Status: {review.status}. Model `{review.model}` did not complete. "
                    f"Error: {review.error_type}."
                )
            findings.extend(review.findings)
        merged_findings, potential_duplicates = merge_findings(findings, language=language)
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
        self.last_potential_duplicates = potential_duplicates
        if self.llm and self.model and self.prompts:
            prompt = self.prompts.load("merge_agent")
            system_prompt = prompt.render()
            if is_chinese_language(language):
                system_prompt = f"{system_prompt}\n\n{ZH_REVIEW_INSTRUCTION}"
            payload = {
                "agent_reviews": [review.to_dict() for review in reviews],
                "findings": [finding.to_dict() for finding in findings],
                "merged_findings": [finding.to_dict() for finding in merged_findings],
            }
            request_options = {
                "system_prompt": system_prompt,
                "user_prompt": json.dumps(payload, ensure_ascii=False, indent=2),
                "model": self.model,
                "timeout_seconds": self.timeout_seconds,
            }
            if self.max_tokens is not None:
                request_options["max_tokens"] = self.max_tokens
            self.llm.complete(**request_options)
            audit = _normalized_provider_audit(getattr(self.llm, "last_response_audit", {}) or {})
            response_truncated = bool(
                audit.get("response_truncated") or audit.get("finish_reason") == "length"
            )
            summary = _structured_merge_summary(merged_findings, reviews, language)
            review = AgentReview(
                agent=self.name,
                summary=summary,
                findings=findings,
                model=self.model,
                provider=self.provider,
                status="truncated" if response_truncated else "completed",
                error_type="ResponseTruncated" if response_truncated else None,
                error_message=(
                    "Merge provider response reached its output limit."
                    if response_truncated
                    else None
                ),
                provider_response_audit=audit,
            )
            review.apply_request_audit(audit)
            return review
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


def _structured_merge_summary(merged_findings, reviews: list[AgentReview], language: str) -> str:
    completed = sum(review.status in {"completed", "completed_with_warnings"} for review in reviews)
    degraded = len(reviews) - completed
    if is_chinese_language(language):
        return (
            f"结构化合并完成：共 {len(merged_findings)} 条综合发现；"
            f"{completed} 个专业 Agent 完成，{degraded} 个结果缺失或不完整。"
        )
    return (
        f"Structured merge completed with {len(merged_findings)} findings; "
        f"{completed} specialist agents completed and {degraded} were incomplete."
    )


def _normalized_provider_audit(audit: dict) -> dict:
    usage = audit.get("usage") or {}
    normalized = dict(audit)
    for key in (
        "finish_reason",
        "content_is_none",
        "content_length",
        "reasoning_content_length",
        "extracted_field",
    ):
        normalized.setdefault(key, None)
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        normalized.setdefault(key, usage.get(key))
    for key in (
        "model_call_count",
        "request_attempt_count",
        "retry_count",
        "timeout_count",
    ):
        normalized.setdefault(key, 0)
    for key in (
        "request_started_at",
        "request_completed_at",
        "last_error_type",
        "last_error_message",
        "configured_timeout_seconds",
        "configured_max_tokens",
        "effective_elapsed_seconds",
    ):
        normalized.setdefault(key, None)
    normalized["response_truncated"] = bool(
        normalized.get("response_truncated") or normalized.get("finish_reason") == "length"
    )
    return normalized
