"""LLM client ports and LiteLLM adapter."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Protocol


class LLMClient(Protocol):
    """Minimal LLM client interface used by agents."""

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        """Return a text completion."""


class LiteLLMClient:
    """LiteLLM-backed implementation of the LLM client port."""

    def __init__(
        self,
        *,
        default_model: str,
        temperature: float = 0.1,
        max_tokens: int = 1200,
        timeout_seconds: int = 60,
        retry_attempts: int = 2,
        model_options: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.default_model = default_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.model_options = model_options or {}
        self.last_response_audit: dict[str, Any] = {}

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        load_dotenv_if_available()

        try:
            from litellm import completion
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("LiteLLM is required for model-backed reviews.") from exc

        selected_model = model or self.default_model
        options = self.model_options.get(selected_model, {})
        litellm_model = selected_model
        if options.get("litellm_provider"):
            litellm_model = f"{options['litellm_provider']}/{selected_model}"
        api_key_env = options.get("api_key_env")
        request_options = {}
        if api_key_env and os.getenv(api_key_env):
            request_options["api_key"] = os.getenv(api_key_env)
        if options.get("api_base"):
            request_options["api_base"] = options["api_base"]

        last_error: Exception | None = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = completion(
                    model=litellm_model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    timeout=timeout_seconds or self.timeout_seconds,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    **request_options,
                )
                text, audit = extract_response_text(response)
                audit["model"] = selected_model
                self.last_response_audit = audit
                return text
            except Exception as exc:  # pragma: no cover - network/provider path
                last_error = exc
                if attempt < self.retry_attempts:
                    time.sleep(min(2**attempt, 8))
        if last_error:
            raise last_error
        raise RuntimeError(f"LiteLLM completion failed for model {selected_model!r}.")


class MockLLMClient:
    """Local deterministic reviewer used when API keys are unavailable."""

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        lowered = system_prompt.lower()
        if "security agent" in lowered:
            payload = {
                "summary": "Security review found risky Kubernetes and container defaults.",
                "findings": [
                    {
                        "severity": "high",
                        "location": "Summary",
                        "issue": "The report recommends cluster-admin access for the application service account.",
                        "evidence_needed": "Confirm the exact Kubernetes RBAC verbs and resources the workload requires.",
                        "suggestion": "Use least-privilege Role or ClusterRole bindings scoped to required resources.",
                        "confidence": 0.95,
                    },
                    {
                        "severity": "medium",
                        "location": "Container Configuration",
                        "issue": "The report allows running the container as root without resource limits.",
                        "evidence_needed": "Provide runtime user, securityContext, CPU, and memory limit requirements.",
                        "suggestion": "Set runAsNonRoot, drop capabilities, and define requests and limits.",
                        "confidence": 0.9,
                    },
                ],
            }
        elif "fact agent" in lowered:
            payload = {
                "summary": "Fact review found claims that need evidence or qualification.",
                "findings": [
                    {
                        "severity": "medium",
                        "location": "Reliability Claim",
                        "issue": "The report says RollingUpdate guarantees zero downtime for every upgrade.",
                        "evidence_needed": "Show readiness probe behavior, PodDisruptionBudget, capacity, and rollout test results.",
                        "suggestion": "Rephrase as a goal and list the conditions required to approach zero downtime.",
                        "confidence": 0.88,
                    }
                ],
            }
        elif "logic agent" in lowered:
            payload = {
                "summary": "Logic review found unsupported reasoning around operations and reliability.",
                "findings": [
                    {
                        "severity": "medium",
                        "location": "Container Configuration",
                        "issue": "The report assumes autoscaling removes the need for resource limits.",
                        "evidence_needed": "Explain how scheduling, quotas, and noisy-neighbor controls are handled.",
                        "suggestion": "Separate cluster scaling from per-container resource governance.",
                        "confidence": 0.86,
                    }
                ],
            }
        else:
            payload = {"summary": "No findings.", "findings": []}
        content = json.dumps(payload)
        self.last_response_audit = {
            "provider_success": True,
            "choices_count": 1,
            "finish_reason": "mock",
            "content_is_none": False,
            "content_length": len(content),
            "reasoning_content_length": 0,
            "extracted_field": "message.content",
            "usage": {},
        }
        return content


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def any_configured_api_key(env_names: list[str]) -> bool:
    load_dotenv_if_available()
    return any(bool(os.getenv(name)) for name in env_names)


class StaticLLMClient:
    """Deterministic test double for agents and workflows."""

    def __init__(self, response: str = "No findings.") -> None:
        self.response = response
        self.last_response_audit = {}

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        return self.response


def extract_response_text(response: Any) -> tuple[str, dict[str, Any]]:
    """Extract response text and sanitized provider audit metadata."""

    choices = _get(response, "choices", []) or []
    audit: dict[str, Any] = {
        "provider_success": True,
        "choices_count": len(choices),
        "finish_reason": None,
        "content_is_none": True,
        "content_length": 0,
        "reasoning_content_length": 0,
        "extracted_field": None,
        "usage": _usage_dict(_get(response, "usage", {})),
    }
    if not choices:
        audit["extracted_field"] = "empty_choices"
        return "", audit

    choice = choices[0]
    audit["finish_reason"] = _get(choice, "finish_reason", None)
    message = _get(choice, "message", {}) or {}
    content = _get(message, "content", None)
    audit["content_is_none"] = content is None
    audit["content_length"] = len(content) if isinstance(content, str) else 0

    reasoning = _first_present(message, ["reasoning_content", "reasoning"])
    audit["reasoning_content_length"] = len(reasoning) if isinstance(reasoning, str) else 0

    if isinstance(content, str) and content.strip():
        audit["extracted_field"] = "message.content"
        return content, audit

    text = _get(choice, "text", None)
    if isinstance(text, str) and text.strip():
        audit["extracted_field"] = "choices[0].text"
        return text, audit

    delta = _get(choice, "delta", {}) or {}
    delta_content = _get(delta, "content", None)
    if isinstance(delta_content, str) and delta_content.strip():
        audit["extracted_field"] = "choices[0].delta.content"
        return delta_content, audit

    if isinstance(reasoning, str) and _looks_like_review_json(reasoning):
        audit["extracted_field"] = "message.reasoning_content"
        return reasoning, audit

    audit["extracted_field"] = "empty_response"
    return "", audit


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _first_present(obj: Any, names: list[str]) -> Any:
    for name in names:
        value = _get(obj, name, None)
        if value is not None:
            return value
    return None


def _usage_dict(usage: Any) -> dict[str, int | None]:
    return {
        "prompt_tokens": _get(usage, "prompt_tokens", None),
        "completion_tokens": _get(usage, "completion_tokens", None),
        "total_tokens": _get(usage, "total_tokens", None),
    }


def _looks_like_review_json(value: str) -> bool:
    return "{" in value and "}" in value and '"summary"' in value and '"findings"' in value
