import sys
from types import SimpleNamespace

import pytest

from agent_network.agents.base import parse_agent_review
from agent_network.llm import LiteLLMClient, ProviderConfigurationError, extract_response_text


def response(choice, usage=None):
    return SimpleNamespace(choices=[choice], usage=usage or SimpleNamespace())


def test_extract_content_normal() -> None:
    text, audit = extract_response_text(
        response(SimpleNamespace(finish_reason="stop", message={"content": "hello"}))
    )

    assert text == "hello"
    assert audit["extracted_field"] == "message.content"
    assert audit["content_length"] == 5


def test_extract_content_none() -> None:
    text, audit = extract_response_text(
        response(SimpleNamespace(finish_reason="stop", message={"content": None}))
    )

    assert text == ""
    assert audit["content_is_none"] is True
    assert audit["extracted_field"] == "empty_response"


def test_extract_content_empty_string() -> None:
    text, audit = extract_response_text(
        response(SimpleNamespace(finish_reason="stop", message={"content": ""}))
    )

    assert text == ""
    assert audit["content_is_none"] is False
    assert audit["content_length"] == 0


def test_extract_compatible_text_field() -> None:
    text, audit = extract_response_text(
        response(SimpleNamespace(finish_reason="stop", message={"content": ""}, text="from text"))
    )

    assert text == "from text"
    assert audit["extracted_field"] == "choices[0].text"


def test_extract_empty_choices() -> None:
    text, audit = extract_response_text(SimpleNamespace(choices=[], usage=SimpleNamespace()))

    assert text == ""
    assert audit["choices_count"] == 0
    assert audit["extracted_field"] == "empty_choices"


def test_finish_reason_length_and_usage_are_audited() -> None:
    text, audit = extract_response_text(
        response(
            SimpleNamespace(finish_reason="length", message={"content": ""}),
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )
    )

    assert text == ""
    assert audit["finish_reason"] == "length"
    assert audit["usage"]["completion_tokens"] == 20
    assert audit["prompt_tokens"] == 10
    assert audit["completion_tokens"] == 20
    assert audit["total_tokens"] == 30
    assert audit["response_truncated"] is True


def test_completion_tokens_with_empty_content_stays_parse_failed() -> None:
    _, audit = extract_response_text(
        response(
            SimpleNamespace(finish_reason="stop", message={"content": ""}),
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )
    )
    review = parse_agent_review(
        "security",
        "",
        provider="siliconflow",
        model="Qwen/Qwen3.6-35B-A3B",
        provider_response_audit=audit,
    )

    assert review.status == "parse_failed"
    assert not review.findings
    assert review.provider_response_audit["usage"]["completion_tokens"] == 20


def test_model_request_retries_are_counted_separately(monkeypatch) -> None:
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TimeoutError("simulated timeout")
        return response(
            SimpleNamespace(finish_reason="stop", message={"content": "ok"}),
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        )

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))
    client = LiteLLMClient(default_model="test/model", retry_attempts=2, timeout_seconds=7)

    assert client.complete(system_prompt="system", user_prompt="user") == "ok"

    audit = client.last_response_audit
    assert len(calls) == 2
    assert all(call["num_retries"] == 0 for call in calls)
    assert audit["model_call_count"] == 2
    assert audit["request_attempt_count"] == 2
    assert audit["retry_count"] == 1
    assert audit["timeout_count"] == 1
    assert audit["configured_timeout_seconds"] == 7
    assert audit["last_error_type"] == "TimeoutError"
    assert audit["request_started_at"]
    assert audit["request_completed_at"]
    assert audit["effective_elapsed_seconds"] >= 0


def test_final_timeout_keeps_complete_request_audit(monkeypatch) -> None:
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        raise TimeoutError("simulated final timeout")

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(completion=completion))
    client = LiteLLMClient(default_model="test/model", retry_attempts=2)

    with pytest.raises(TimeoutError):
        client.complete(system_prompt="system", user_prompt="user")

    audit = client.last_response_audit
    assert len(calls) == 2
    assert audit["provider_success"] is False
    assert audit["model_call_count"] == 2
    assert audit["retry_count"] == 1
    assert audit["timeout_count"] == 2
    assert audit["last_error_type"] == "TimeoutError"
    assert audit["last_error_message"] == "simulated final timeout"
    for key in (
        "choices_count",
        "finish_reason",
        "content_is_none",
        "content_length",
        "reasoning_content_length",
        "extracted_field",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "response_truncated",
    ):
        assert key in audit
        assert audit[key] is None


def test_provider_configuration_fails_before_network_and_audits_safely(monkeypatch) -> None:
    monkeypatch.setattr("agent_network.llm.load_dotenv_if_available", lambda: None)
    monkeypatch.delenv("TEST_OFFICIAL_KEY", raising=False)
    completion_calls: list[dict[str, object]] = []
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(completion=lambda **kwargs: completion_calls.append(kwargs)),
    )
    client = LiteLLMClient(
        default_model="official/model",
        model_options={
            "official/model": {
                "provider": "deepseek_official",
                "api_key_env": "TEST_OFFICIAL_KEY",
                "api_base": "https://api.example/v1",
                "base_url_required": "true",
                "provider_configured": "false",
            }
        },
    )

    with pytest.raises(ProviderConfigurationError, match="missing_api_key"):
        client.complete(system_prompt="system", user_prompt="user")

    assert completion_calls == []
    assert client.last_response_audit["provider"] == "deepseek_official"
    assert client.last_response_audit["base_url_host"] == "api.example"
    assert client.last_response_audit["provider_configured"] is False
    assert client.last_response_audit["configuration_error_type"] == "missing_api_key"
    assert client.last_response_audit["model_call_count"] == 0


def test_provider_base_url_is_passed_from_model_options(monkeypatch) -> None:
    monkeypatch.setattr("agent_network.llm.load_dotenv_if_available", lambda: None)
    monkeypatch.setenv("TEST_OFFICIAL_KEY", "test-secret-value")
    calls: list[dict[str, object]] = []
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(
            completion=lambda **kwargs: (
                calls.append(kwargs)
                or response(SimpleNamespace(finish_reason="stop", message={"content": "ok"}))
            )
        ),
    )
    client = LiteLLMClient(
        default_model="official/model",
        model_options={
            "official/model": {
                "provider": "dashscope_official",
                "api_key_env": "TEST_OFFICIAL_KEY",
                "api_base": "https://dashscope.example/v1",
                "base_url_required": "true",
                "provider_configured": "true",
                "litellm_provider": "openai",
            }
        },
    )

    assert client.complete(system_prompt="system", user_prompt="user") == "ok"

    assert calls[0]["api_base"] == "https://dashscope.example/v1"
    assert calls[0]["api_key"] == "test-secret-value"
    assert client.last_response_audit["base_url_host"] == "dashscope.example"


def test_extra_body_is_forwarded_only_when_configured(monkeypatch) -> None:
    monkeypatch.setattr("agent_network.llm.load_dotenv_if_available", lambda: None)
    monkeypatch.setenv("TEST_OFFICIAL_KEY", "test-secret-value")
    calls: list[dict[str, object]] = []
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(
            completion=lambda **kwargs: (
                calls.append(kwargs)
                or response(SimpleNamespace(finish_reason="stop", message={"content": "ok"}))
            )
        ),
    )
    client = LiteLLMClient(
        default_model="official/model",
        model_options={
            "official/model": {
                "provider": "dashscope_official",
                "api_key_env": "TEST_OFFICIAL_KEY",
                "api_base": "https://dashscope.example/v1",
                "base_url_required": "true",
                "provider_configured": "true",
            }
        },
    )

    client.complete(
        system_prompt="system",
        user_prompt="user",
        extra_body={"enable_thinking": False},
    )

    assert calls[0]["extra_body"] == {"enable_thinking": False}
