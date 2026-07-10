"""Agent interfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
import re
from typing import Protocol

from agent_network.llm import LLMClient
from agent_network.prompts import PromptTemplate
from agent_network.schemas import AgentReview, FindingStatus, ReviewRequest


class ReviewerAgent(Protocol):
    """Interface implemented by report reviewer agents."""

    name: str

    def review(self, request: ReviewRequest) -> AgentReview:
        """Review a Markdown report."""


@dataclass(slots=True)
class LLMReviewerAgent:
    """Base implementation for model-backed reviewer agents."""

    name: str
    prompt: PromptTemplate
    llm: LLMClient
    model: str | None = None
    provider: str | None = None
    timeout_seconds: int | None = None

    def review(self, request: ReviewRequest) -> AgentReview:
        content = self.llm.complete(
            system_prompt=self.prompt.render(),
            user_prompt=f"Source: {request.source_name}\n\n{request.markdown}",
            model=self.model,
            timeout_seconds=self.timeout_seconds,
        )
        provider_response_audit = getattr(self.llm, "last_response_audit", {})
        review = parse_agent_review(
            agent=self.name,
            content=content,
            provider=self.provider,
            model=self.model,
            provider_response_audit=provider_response_audit,
        )
        review.model = self.model
        review.provider = self.provider
        return review


def parse_agent_review(
    agent: str,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    original_debug_response: str | None = None,
    provider_response_audit: dict | None = None,
) -> AgentReview:
    """Parse a model response into the structured review schema."""

    parse_attempts = 1
    try:
        data = _parse_json_response(content)
    except (JSONDecodeError, ValueError):
        parse_attempts += 1
        try:
            repaired = _local_json_repair(content)
            data = _parse_json_response(repaired)
        except (JSONDecodeError, ValueError) as repair_exc:
            return _parse_failed_review(
                agent=agent,
                provider=provider,
                model=model,
                content=original_debug_response or content,
                error_type=type(repair_exc).__name__,
                parse_attempts=parse_attempts,
                repair_status="failed",
                provider_response_audit=provider_response_audit,
            )
    if not isinstance(data, dict):
        return _parse_failed_review(
            agent=agent,
            provider=provider,
            model=model,
            content=original_debug_response or content,
            error_type="SchemaError",
            parse_attempts=parse_attempts,
            repair_status="not_applicable",
            provider_response_audit=provider_response_audit,
        )
    review = AgentReview.from_dict(agent=agent, data=data, provider=provider, model=model)
    review.status = "completed"
    review.parse_attempts = parse_attempts
    review.repair_attempted = parse_attempts > 1
    review.repair_status = "succeeded" if parse_attempts > 1 else "not_needed"
    review.provider_response_audit = provider_response_audit or {}
    for finding in review.findings:
        finding.agent = agent
        finding.provider = provider
        finding.model = model
        finding.status = FindingStatus.VALID
    return review


def _parse_json_response(content: str) -> object:
    try:
        return json.loads(content.strip())
    except JSONDecodeError:
        return json.loads(_extract_json_object(content))


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start = stripped.find("{")
    if start < 0:
        raise ValueError("No JSON object found in model response.")
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(stripped[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    raise ValueError("No complete JSON object found in model response.")


def _local_json_repair(content: str) -> str:
    repaired = _strip_code_fences(content)
    repaired = _extract_json_object(repaired)
    repaired = repaired.replace("\ufeff", "").strip()
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = repaired.replace("“", '"').replace("”", '"').replace("’", "'")
    return repaired


def _strip_code_fences(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _parse_failed_review(
    *,
    agent: str,
    provider: str | None,
    model: str | None,
    content: str,
    error_type: str,
    parse_attempts: int,
    repair_status: str,
    provider_response_audit: dict | None = None,
) -> AgentReview:
    return AgentReview(
        agent=agent,
        summary=f"{agent.title()} Agent call completed, but structured parsing failed.",
        findings=[],
        status="parse_failed",
        provider=provider,
        model=model,
        error_type=error_type,
        error_message="Model response was not valid review JSON.",
        debug_response=_sanitize_debug_response(content),
        parse_attempts=parse_attempts,
        repair_attempted=True,
        repair_status=repair_status,
        parse_error_type=error_type,
        provider_response_audit=provider_response_audit or {},
    )


def _sanitize_debug_response(content: str, limit: int = 4000) -> str:
    redacted = content.replace("SILICONFLOW_API_KEY", "[REDACTED_ENV_NAME]")
    return redacted[:limit]
