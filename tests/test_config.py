import os

import pytest

from agent_network.config import AppConfig, load_config


def test_default_config_sets_agent_models_and_cost_controls() -> None:
    config = load_config("configs/default.yaml")

    assert config.provider_for_agent("fact") == "siliconflow"
    assert config.provider_for_agent("security") == "siliconflow"
    assert config.provider_for_agent("logic") == "siliconflow"
    assert config.provider_for_agent("merge") == "siliconflow"
    assert config.model_for_agent("fact") == "deepseek-ai/DeepSeek-V4-Pro"
    assert config.model_for_agent("security") == "Qwen/Qwen3.6-35B-A3B"
    assert config.model_for_agent("logic") == "deepseek-ai/DeepSeek-V4-Flash"
    assert config.model_for_agent("merge") == "zai-org/GLM-5.2"
    assert config.api_key_env_for_provider("siliconflow") == "SILICONFLOW_API_KEY"
    assert config.api_base_for_provider("siliconflow") == "https://api.siliconflow.cn/v1"
    assert config.litellm_provider_for_provider("siliconflow") == "openai"
    assert config.timeout_for_agent("fact") == 90
    assert config.timeout_for_agent("security") == 180
    assert config.timeout_for_agent("logic") == 120
    assert config.timeout_for_agent("merge") == 120
    assert "factual claims" in config.role_for_agent("fact")
    assert "security risks" in config.role_for_agent("security")
    assert "reasoning flow" in config.role_for_agent("logic")
    assert "synthesize" in config.role_for_agent("merge")
    assert config.max_tokens == 1600
    assert config.timeout_seconds == 60
    assert config.retry_attempts == 2


def test_long_report_profile_overrides_timeouts_and_retry_only() -> None:
    config = load_config("configs/default.yaml").with_profile("long-report")

    assert config.profile_name == "long-report"
    assert config.retry_attempts == 1
    assert config.timeout_for_agent("fact") == 600
    assert config.timeout_for_agent("security") == 240
    assert config.timeout_for_agent("logic") == 600
    assert config.timeout_for_agent("merge") == 240
    assert config.max_tokens_for_agent("fact") == 2400
    assert config.max_tokens_for_agent("security") == 3200
    assert config.max_tokens_for_agent("logic") == 3200
    assert config.max_tokens_for_agent("merge") == 2400
    assert config.model_for_agent("fact") == "deepseek-ai/DeepSeek-V4-Pro"
    assert config.model_for_agent("security") == "Qwen/Qwen3.6-35B-A3B"
    assert config.model_for_agent("logic") == "deepseek-ai/DeepSeek-V4-Flash"
    assert config.model_for_agent("merge") == "zai-org/GLM-5.2"
    assert config.reasoning_mode_for_agent("security") == "provider_default"
    assert config.json_mode_for_agent("security") == "disabled"
    assert config.provider_capability_status_for_agent("security") == "unverified_for_model"
    assert config.provider_request_options_for_agent("security") == {}


def test_rancher_document_fetcher_configuration_loads() -> None:
    config = load_config("configs/default.yaml")

    assert config.document_fetcher_config("rancher") == {
        "timeout_seconds": 20,
        "maximum_response_bytes": 1_000_000,
        "maximum_redirects": 3,
        "user_agent": "agent-network-document-fetcher/0.3",
    }


def test_fact_evidence_provider_defaults_to_fixture_and_rejects_unknown_values() -> None:
    config = load_config("configs/default.yaml")

    assert config.fact_evidence_config()["provider"] == "fixture"
    with pytest.raises(ValueError, match="Unknown Fact evidence provider"):
        AppConfig(raw={"evidence": {"fact_agent": {"provider": "other"}}}).fact_evidence_config()


def test_official_provider_config_uses_env_for_keys_and_base_urls(monkeypatch) -> None:
    config = load_config("configs/default.yaml")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.example/v1")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-dashscope-key")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://dashscope.example/v1")

    deepseek = config.provider_runtime_config("deepseek_official")
    dashscope = config.provider_runtime_config("dashscope_official")

    assert deepseek["api_key_env"] == "DEEPSEEK_API_KEY"
    assert deepseek["base_url_env"] == "DEEPSEEK_BASE_URL"
    assert deepseek["base_url_host"] == "api.deepseek.example"
    assert deepseek["configured"] is True
    assert dashscope["api_key_env"] == "DASHSCOPE_API_KEY"
    assert dashscope["base_url_host"] == "dashscope.example"


def test_provider_runtime_config_loads_dotenv_before_preflight(monkeypatch) -> None:
    config = load_config("configs/default.yaml")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    def load_test_dotenv() -> None:
        os.environ["DEEPSEEK_API_KEY"] = "dotenv-key"
        os.environ["DEEPSEEK_BASE_URL"] = "https://dotenv.example/v1"

    import agent_network.llm as llm

    monkeypatch.setattr(llm, "load_dotenv_if_available", load_test_dotenv)
    runtime = config.provider_runtime_config("deepseek_official")

    assert runtime["configured"] is True
    assert runtime["base_url_host"] == "dotenv.example"


def test_provider_configuration_reports_missing_key_or_base_url(monkeypatch) -> None:
    config = load_config("configs/default.yaml")
    import agent_network.llm as llm

    monkeypatch.setattr(llm, "load_dotenv_if_available", lambda: None)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    runtime = config.provider_runtime_config("deepseek_official")

    assert runtime["configured"] is False
    assert runtime["configuration_error_type"] == "missing_api_key"
    assert runtime["base_url_host"] is None


def test_siliconflow_remains_a_configurable_fallback(monkeypatch) -> None:
    config = load_config("configs/default.yaml")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test-siliconflow-key")
    monkeypatch.setenv("SILICONFLOW_BASE_URL", "https://fallback.example/v1")

    runtime = config.provider_runtime_config("siliconflow")

    assert runtime["configured"] is True
    assert runtime["base_url_host"] == "fallback.example"
