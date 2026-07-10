import pytest

from agent_network.prompts import PromptRegistry


pytest.importorskip("yaml")


def test_prompt_registry_loads_prompt() -> None:
    prompt = PromptRegistry("prompts").load("fact_agent")

    assert prompt.id == "fact-agent"
    assert prompt.version == "0.1.0"
    assert "Fact Agent" in prompt.render()
