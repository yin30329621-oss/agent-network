"""Configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import os
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppConfig:
    """Application configuration wrapper."""

    raw: dict[str, Any]
    profile_name: str = "balanced"

    def with_profile(self, profile_name: str) -> "AppConfig":
        profiles = self.raw.get("profiles", {})
        if profile_name not in profiles:
            available = ", ".join(sorted(profiles)) or "none"
            raise ValueError(f"Unknown profile {profile_name!r}. Available profiles: {available}")
        raw = deepcopy(self.raw)
        profile = profiles[profile_name] or {}
        review_agents = raw.setdefault("review", {}).setdefault("agents", {})
        for agent in ("fact", "security", "logic", "merge"):
            override = profile.get(agent)
            if isinstance(override, dict):
                review_agents.setdefault(agent, {}).update(override)
        if "retry_attempts" in profile:
            raw.setdefault("llm", {})["retry_attempts"] = int(profile["retry_attempts"])
        return AppConfig(raw=raw, profile_name=profile_name)

    @property
    def available_profiles(self) -> tuple[str, ...]:
        return tuple(sorted(self.raw.get("profiles", {})))

    @property
    def default_model(self) -> str:
        return str(self.raw.get("llm", {}).get("default_model", "gpt-4o-mini"))

    @property
    def temperature(self) -> float:
        return float(self.raw.get("llm", {}).get("temperature", 0.1))

    @property
    def mock_when_missing_api_key(self) -> bool:
        return self.mode == "auto"

    @property
    def mode(self) -> str:
        return str(self.raw.get("llm", {}).get("mode", "auto")).lower()

    @property
    def max_tokens(self) -> int:
        return int(self.raw.get("llm", {}).get("max_tokens", 1200))

    @property
    def timeout_seconds(self) -> int:
        return int(self.raw.get("llm", {}).get("timeout_seconds", 60))

    @property
    def retry_attempts(self) -> int:
        return int(self.raw.get("llm", {}).get("retry_attempts", 2))

    def model_for_agent(self, agent: str) -> str:
        review_config = self.raw.get("review", {})
        agent_config = review_config.get("agents", {}).get(agent, {})
        return str(agent_config.get("model") or self.default_model)

    def timeout_for_agent(self, agent: str) -> int:
        review_config = self.raw.get("review", {})
        agent_config = review_config.get("agents", {}).get(agent, {})
        return int(agent_config.get("timeout_seconds") or self.timeout_seconds)

    def max_tokens_for_agent(self, agent: str) -> int:
        review_config = self.raw.get("review", {})
        agent_config = review_config.get("agents", {}).get(agent, {})
        return int(agent_config.get("max_tokens") or self.max_tokens)

    def reasoning_mode_for_agent(self, agent: str) -> str:
        agent_config = self.raw.get("review", {}).get("agents", {}).get(agent, {})
        return str(agent_config.get("reasoning_mode") or "provider_default")

    def json_mode_for_agent(self, agent: str) -> str:
        agent_config = self.raw.get("review", {}).get("agents", {}).get(agent, {})
        return str(agent_config.get("json_mode") or "disabled")

    def provider_capability_status_for_agent(self, agent: str) -> str:
        agent_config = self.raw.get("review", {}).get("agents", {}).get(agent, {})
        return str(agent_config.get("provider_capability_status") or "not_configured")

    def provider_request_options_for_agent(self, agent: str) -> dict[str, Any]:
        """Return only provider options explicitly marked as verified."""

        agent_config = self.raw.get("review", {}).get("agents", {}).get(agent, {})
        if agent_config.get("provider_capability_status") != "verified":
            return {}
        options = agent_config.get("provider_request_options")
        return dict(options) if isinstance(options, dict) else {}

    def document_source_config(self, source_name: str) -> dict[str, Any]:
        sources = self.raw.get("evidence", {}).get("document_sources", {})
        config = sources.get(source_name)
        if not isinstance(config, dict):
            raise ValueError(f"Unknown document evidence source: {source_name}")
        return dict(config)

    def document_source_domains(self, source_name: str) -> set[str]:
        config = self.document_source_config(source_name)
        domains = config.get("domains") or []
        if not isinstance(domains, list) or not all(isinstance(domain, str) for domain in domains):
            raise ValueError(f"Document source {source_name} must define string domains")
        return set(domains)

    def document_fetcher_config(self, source_name: str) -> dict[str, Any]:
        config = self.document_source_config(source_name).get("fetcher") or {}
        if not isinstance(config, dict):
            raise ValueError(f"Document source {source_name} fetcher must be a mapping")
        required = {
            "timeout_seconds",
            "maximum_response_bytes",
            "maximum_redirects",
            "user_agent",
        }
        if not required.issubset(config):
            raise ValueError(f"Document source {source_name} fetcher configuration is incomplete")
        return dict(config)

    def role_for_agent(self, agent: str) -> str:
        roles = {
            "fact": "Verify factual claims, evidence needs, citations, and technical accuracy.",
            "security": "Review cloud-native security risks, unsafe defaults, and hardening gaps.",
            "logic": "Check reasoning flow, assumptions, contradictions, and conclusion strength.",
            "merge": "Deduplicate and synthesize completed agent reviews into the final report.",
        }
        return roles.get(agent, "Review technical report content.")

    def provider_for_agent(self, agent: str) -> str:
        review_config = self.raw.get("review", {})
        agent_config = review_config.get("agents", {}).get(agent, {})
        return str(
            agent_config.get("provider") or review_config.get("default_provider") or "openai"
        )

    def api_key_env_for_provider(self, provider: str) -> str:
        providers = self.raw.get("llm", {}).get("providers", {})
        provider_config = providers.get(provider, {})
        fallback = {
            "siliconflow": "SILICONFLOW_API_KEY",
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "glm": "ZAI_API_KEY",
            "zai": "ZAI_API_KEY",
        }
        return str(provider_config.get("api_key_env") or fallback.get(provider, "OPENAI_API_KEY"))

    def api_base_for_provider(self, provider: str) -> str | None:
        providers = self.raw.get("llm", {}).get("providers", {})
        value = providers.get(provider, {}).get("api_base")
        return str(value) if value else None

    def litellm_provider_for_provider(self, provider: str) -> str | None:
        providers = self.raw.get("llm", {}).get("providers", {})
        value = providers.get(provider, {}).get("litellm_provider")
        return str(value) if value else None

    def has_api_key_for_agent(self, agent: str) -> bool:
        provider = self.provider_for_agent(agent)
        return bool(os.getenv(self.api_key_env_for_provider(provider)))

    def llm_options_by_model(self) -> dict[str, dict[str, str]]:
        options: dict[str, dict[str, str]] = {}
        for agent in ("fact", "security", "logic", "merge"):
            provider = self.provider_for_agent(agent)
            model = self.model_for_agent(agent)
            model_options: dict[str, str] = {
                "provider": provider,
                "api_key_env": self.api_key_env_for_provider(provider),
            }
            api_base = self.api_base_for_provider(provider)
            if api_base:
                model_options["api_base"] = api_base
            litellm_provider = self.litellm_provider_for_provider(provider)
            if litellm_provider:
                model_options["litellm_provider"] = litellm_provider
            options[model] = model_options
        return options


def load_config(path: str | Path = "configs/default.yaml") -> AppConfig:
    """Load YAML configuration from disk."""

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("PyYAML is required to load Agent Network config.") from exc

    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return AppConfig(raw=data)
