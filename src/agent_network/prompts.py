"""Prompt template loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """A versioned prompt template stored outside code."""

    id: str
    version: str
    role: str
    template: str

    def render(self, **variables: Any) -> str:
        return self.template.format(**variables) if variables else self.template


class PromptRegistry:
    """Loads prompt templates from a directory."""

    def __init__(self, prompt_dir: str | Path = "prompts") -> None:
        self.prompt_dir = Path(prompt_dir)

    def load(self, name: str) -> PromptTemplate:
        try:
            import yaml
        except ImportError:
            yaml = None

        path = self.prompt_dir / f"{name}.yaml"
        with path.open("r", encoding="utf-8") as file:
            content = file.read()
        data = yaml.safe_load(content) if yaml else _load_simple_prompt_yaml(content)
        return PromptTemplate(
            id=str(data["id"]),
            version=str(data["version"]),
            role=str(data["role"]),
            template=str(data["template"]),
        )


def _load_simple_prompt_yaml(content: str) -> dict[str, str]:
    """Parse the small prompt YAML subset used by built-in prompts.

    This keeps prompt loading testable before the project dependencies are
    installed. Full YAML support is provided by PyYAML in normal uv environments.
    """

    data: dict[str, str] = {}
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("template: |"):
            index += 1
            block: list[str] = []
            while index < len(lines):
                block_line = lines[index]
                block.append(block_line[2:] if block_line.startswith("  ") else block_line)
                index += 1
            data["template"] = "\n".join(block).strip() + "\n"
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()
        index += 1
    return data
