from agent_network.config import load_config


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
