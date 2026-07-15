"""Configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


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

    def fact_evidence_config(self) -> dict[str, Any]:
        config = self.raw.get("evidence", {}).get("fact_agent") or {}
        if not isinstance(config, dict):
            raise ValueError("Fact evidence configuration must be a mapping")
        defaults = {
            "enabled": False,
            "provider": "fixture",
            "top_k": 5,
            "max_chars_per_evidence": 1600,
            "max_total_evidence_chars": 6000,
            "allow_network": False,
            "local_cache": {},
            "claim_verification": {},
        }
        defaults.update(config)
        provider = str(defaults["provider"]).strip().lower()
        if provider not in {"fixture", "local_cache"}:
            raise ValueError(f"Unknown Fact evidence provider: {provider}")
        defaults["provider"] = provider
        if not isinstance(defaults["local_cache"], dict):
            raise ValueError("Fact local_cache configuration must be a mapping")
        if not isinstance(defaults["claim_verification"], dict):
            raise ValueError("Fact claim_verification configuration must be a mapping")
        return defaults

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
        """Resolve a provider base URL without exposing any API-key value."""

        providers = self.raw.get("llm", {}).get("providers", {})
        provider_config = providers.get(provider, {})
        base_url_env = provider_config.get("base_url_env")
        if base_url_env:
            configured = os.getenv(str(base_url_env))
            if configured:
                return configured
        value = provider_config.get("api_base")
        return str(value) if value else None

    def base_url_env_for_provider(self, provider: str) -> str | None:
        providers = self.raw.get("llm", {}).get("providers", {})
        value = providers.get(provider, {}).get("base_url_env")
        return str(value) if value else None

    def provider_runtime_config(self, provider: str) -> dict[str, Any]:
        """Return safe provider configuration for a request audit and LiteLLM.

        Keys themselves are intentionally not returned.  A configured API key is
        represented only by a boolean, while a base URL is reduced to its host in
        audit-facing fields.
        """

        # Provider validation runs while adapters are constructed, before
        # LiteLLMClient.complete() loads dotenv values.
        from agent_network.llm import load_dotenv_if_available

        load_dotenv_if_available()
        providers = self.raw.get("llm", {}).get("providers", {})
        provider_config = providers.get(provider)
        if not isinstance(provider_config, dict):
            raise ValueError(f"Unknown LLM provider: {provider}")
        api_key_env = self.api_key_env_for_provider(provider)
        base_url_env = self.base_url_env_for_provider(provider)
        api_base = self.api_base_for_provider(provider)
        base_url_required = bool(provider_config.get("base_url_required", bool(base_url_env)))
        missing: list[str] = []
        if not os.getenv(api_key_env):
            missing.append("missing_api_key")
        if base_url_required and not api_base:
            missing.append("missing_base_url")
        return {
            "provider": provider,
            "api_key_env": api_key_env,
            "base_url_env": base_url_env,
            "api_base": api_base,
            "base_url_host": _base_url_host(api_base),
            "base_url_required": base_url_required,
            "configured": not missing,
            "configuration_error_type": missing[0] if missing else None,
            "litellm_provider": self.litellm_provider_for_provider(provider),
        }

    def dual_fact_reviewer_config(self, reviewer: str) -> dict[str, Any]:
        """Load a dual-Fact reviewer configuration without changing workflow agents."""

        reviewers = self.raw.get("fact_review", {}).get("reviewers", {})
        config = reviewers.get(reviewer)
        if not isinstance(config, dict):
            raise ValueError(f"Unknown Fact reviewer: {reviewer}")
        provider = str(config.get("provider") or "").strip()
        model = str(config.get("model") or "").strip()
        if not provider or not model:
            raise ValueError(f"Fact reviewer {reviewer} must define provider and model")
        self.provider_runtime_config(provider)
        request_options = config.get("request_options")
        if request_options is None:
            request_options = {}
        if not isinstance(request_options, dict):
            raise ValueError(f"Fact reviewer {reviewer} request_options must be a mapping")
        if provider == "dashscope_official":
            if "enable_thinking" in request_options and (
                request_options["enable_thinking"] is not None
                and not isinstance(request_options["enable_thinking"], bool)
            ):
                raise ValueError("DashScope enable_thinking must be true, false, or null")
            request_options = {
                key: request_options[key] for key in ("enable_thinking",) if key in request_options
            }
        elif provider == "deepseek_official":
            response_format = request_options.get("response_format")
            request_options = (
                {"response_format": {"type": "json_object"}}
                if isinstance(response_format, dict)
                and response_format.get("type") == "json_object"
                else {}
            )
        else:
            request_options = {}
        if "enable_thinking" in request_options and request_options["enable_thinking"] is None:
            request_options = {}
        return {
            "reviewer_id": reviewer.replace("_", "-"),
            "provider": provider,
            "model": model,
            "timeout_seconds": int(config.get("timeout_seconds") or self.timeout_seconds),
            "max_tokens": int(config.get("max_tokens") or self.max_tokens),
            "retry_attempts": int(config.get("retry_attempts", 0)),
            "request_options": dict(request_options),
        }

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
            options[model] = self.llm_options_for(provider, model)
        return options

    def llm_options_for(self, provider: str, model: str) -> dict[str, str]:
        """Build one model's provider-neutral LiteLLM options from configuration."""

        runtime = self.provider_runtime_config(provider)
        options: dict[str, str] = {
            "provider": str(runtime["provider"]),
            "api_key_env": str(runtime["api_key_env"]),
            "base_url_required": str(runtime["base_url_required"]),
            "provider_configured": str(runtime["configured"]),
        }
        if runtime["base_url_env"]:
            options["base_url_env"] = str(runtime["base_url_env"])
        if runtime["api_base"]:
            options["api_base"] = str(runtime["api_base"])
        if runtime["litellm_provider"]:
            options["litellm_provider"] = str(runtime["litellm_provider"])
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


def _base_url_host(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    return parsed.hostname
