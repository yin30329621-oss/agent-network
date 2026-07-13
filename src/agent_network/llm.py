"""LLM client ports and LiteLLM adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
import os
import re
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
        max_tokens: int | None = None,
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
        max_tokens: int | None = None,
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

        configured_timeout = timeout_seconds or self.timeout_seconds
        configured_max_tokens = max_tokens or self.max_tokens
        request_started_at = datetime.now(UTC).isoformat()
        request_started = time.monotonic()
        model_call_count = 0
        timeout_count = 0
        last_error: Exception | None = None
        max_attempts = max(1, self.retry_attempts)
        for attempt in range(1, max_attempts + 1):
            model_call_count += 1
            try:
                response = completion(
                    model=litellm_model,
                    temperature=self.temperature,
                    max_tokens=configured_max_tokens,
                    timeout=configured_timeout,
                    num_retries=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    **request_options,
                )
                text, audit = extract_response_text(response)
                audit["model"] = selected_model
                audit.update(
                    _request_audit(
                        model_call_count=model_call_count,
                        timeout_count=timeout_count,
                        request_started_at=request_started_at,
                        request_started=request_started,
                        configured_timeout_seconds=configured_timeout,
                        configured_max_tokens=configured_max_tokens,
                        last_error=last_error,
                    )
                )
                self.last_response_audit = audit
                return text
            except Exception as exc:  # pragma: no cover - network/provider path
                last_error = exc
                if _is_timeout_error(exc):
                    timeout_count += 1
                self.last_response_audit = {
                    **_empty_provider_response_audit(),
                    "model": selected_model,
                    **_request_audit(
                        model_call_count=model_call_count,
                        timeout_count=timeout_count,
                        request_started_at=request_started_at,
                        request_started=request_started,
                        configured_timeout_seconds=configured_timeout,
                        configured_max_tokens=configured_max_tokens,
                        last_error=last_error,
                    ),
                }
                if attempt < max_attempts:
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
        max_tokens: int | None = None,
    ) -> str:
        lowered = system_prompt.lower()
        chinese = any("\u4e00" <= char <= "\u9fff" for char in user_prompt)
        if "security agent" in lowered and chinese:
            payload = {
                "summary": "发现 Rancher 报告中的安全风险。",
                "findings": [
                    {
                        "severity": "high",
                        "location": "Rancher Cluster Agent 通信",
                        "issue": "报告未说明 Cluster Agent 到 Rancher Server 的 HTTPS WebSocket 安全边界。",
                        "reason": "缺少 API、RBAC 和网络访问控制说明会影响 Rancher 管理面安全判断。",
                        "evidence_needed": "需要补充 Rancher 官方文档、RBAC 策略和网络连通性说明。",
                        "reference": "CVE-2023-32197",
                        "suggestion": "补充 Cluster Agent、Rancher Server、Kubernetes API 与 RBAC 的权限边界。",
                        "confidence": 0.9,
                    }
                ],
            }
        elif "security agent" in lowered:
            payload = {
                "summary": "Security review found risky Kubernetes and container defaults.",
                "findings": [
                    {
                        "severity": "high",
                        "location": "Summary",
                        "issue": "The report recommends cluster-admin access for the application service account.",
                        "reason": "The recommendation grants broader Kubernetes permissions than the workload demonstrates it needs.",
                        "evidence_needed": "Confirm the exact Kubernetes RBAC verbs and resources the workload requires.",
                        "suggestion": "Use least-privilege Role or ClusterRole bindings scoped to required resources.",
                        "confidence": 0.95,
                    },
                    {
                        "severity": "medium",
                        "location": "Container Configuration",
                        "issue": "The report allows running the container as root without resource limits.",
                        "reason": "The configuration increases workload privilege and resource exhaustion risk.",
                        "evidence_needed": "Provide runtime user, securityContext, CPU, and memory limit requirements.",
                        "suggestion": "Set runAsNonRoot, drop capabilities, and define requests and limits.",
                        "confidence": 0.9,
                    },
                ],
            }
        elif "fact agent" in lowered and chinese:
            payload = {
                "summary": "事实审查发现需要补充来源的表述。",
                "findings": [
                    {
                        "severity": "medium",
                        "location": "Rancher 架构说明",
                        "issue": "报告对 Rancher Server 与 Cluster Agent 的关系缺少来源。",
                        "reason": "没有引用官方文档时，读者难以验证架构描述是否准确。",
                        "evidence_needed": "需要 Rancher 官方文档或架构图作为证据。",
                        "reference": "",
                        "suggestion": "补充 Rancher Server、Cluster Agent 与 Kubernetes API 的官方引用。",
                        "confidence": 0.85,
                    }
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
                        "reason": "The conclusion does not follow without availability controls and rollout evidence.",
                        "evidence_needed": "Show readiness probe behavior, PodDisruptionBudget, capacity, and rollout test results.",
                        "suggestion": "Rephrase as a goal and list the conditions required to approach zero downtime.",
                        "confidence": 0.88,
                    }
                ],
            }
        elif "logic agent" in lowered and chinese:
            payload = {
                "summary": "逻辑审查发现论证链条需要补强。",
                "findings": [
                    {
                        "severity": "medium",
                        "location": "安全结论",
                        "issue": "报告从 HTTPS 连接直接推导为整体安全，论证不充分。",
                        "reason": "HTTPS 只能说明传输加密，不能替代 API 权限、RBAC 和审计控制。",
                        "evidence_needed": "需要补充 RBAC、审计日志和 Kubernetes 资源访问范围。",
                        "reference": "",
                        "suggestion": "将传输安全、身份认证和授权控制分开论证。",
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
                        "reason": "Cluster scaling and per-container resource governance address different constraints.",
                        "evidence_needed": "Explain how scheduling, quotas, and noisy-neighbor controls are handled.",
                        "suggestion": "Separate cluster scaling from per-container resource governance.",
                        "confidence": 0.86,
                    }
                ],
            }
        elif "merge agent" in lowered and chinese:
            payload = {
                "summary": "# 审查报告\n\n综合来看，Rancher 报告需要补充事实来源、安全边界和逻辑论证。"
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
        max_tokens: int | None = None,
    ) -> str:
        return self.response


def extract_response_text(response: Any) -> tuple[str, dict[str, Any]]:
    """Extract response text and sanitized provider audit metadata."""

    choices = _get(response, "choices", []) or []
    usage = _usage_dict(_get(response, "usage", {}))
    audit: dict[str, Any] = {
        "provider_success": True,
        "choices_count": len(choices),
        "finish_reason": None,
        "content_is_none": True,
        "content_length": 0,
        "reasoning_content_length": 0,
        "extracted_field": None,
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "total_tokens": usage["total_tokens"],
        "response_truncated": False,
        "usage": usage,
    }
    if not choices:
        audit["extracted_field"] = "empty_choices"
        return "", audit

    choice = choices[0]
    audit["finish_reason"] = _get(choice, "finish_reason", None)
    audit["response_truncated"] = audit["finish_reason"] == "length"
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


def _request_audit(
    *,
    model_call_count: int,
    timeout_count: int,
    request_started_at: str,
    request_started: float,
    configured_timeout_seconds: int | float,
    configured_max_tokens: int,
    last_error: Exception | None,
) -> dict[str, Any]:
    return {
        "model_call_count": model_call_count,
        "request_attempt_count": model_call_count,
        "retry_count": max(0, model_call_count - 1),
        "timeout_count": timeout_count,
        "request_started_at": request_started_at,
        "request_completed_at": datetime.now(UTC).isoformat(),
        "last_error_type": type(last_error).__name__ if last_error else None,
        "last_error_message": _sanitize_error_message(last_error),
        "configured_timeout_seconds": configured_timeout_seconds,
        "configured_max_tokens": configured_max_tokens,
        "effective_elapsed_seconds": time.monotonic() - request_started,
    }


def _empty_provider_response_audit() -> dict[str, Any]:
    return {
        "provider_success": False,
        "choices_count": None,
        "finish_reason": None,
        "content_is_none": None,
        "content_length": None,
        "reasoning_content_length": None,
        "extracted_field": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "response_truncated": None,
        "usage": {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        },
    }


def _is_timeout_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return isinstance(exc, TimeoutError) or "timeout" in name or "timed out" in message


def _sanitize_error_message(exc: Exception | None) -> str | None:
    if exc is None:
        return None
    message = str(exc)
    for env_name in (
        "SILICONFLOW_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "ZAI_API_KEY",
    ):
        value = os.getenv(env_name)
        if value:
            message = message.replace(value, "[REDACTED]")
    message = re.sub(r"(?i)bearer\s+[a-z0-9._~+\-/]+=*", "Bearer [REDACTED]", message)
    return message[:1000]
