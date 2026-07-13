# Agent Network

Agent Network is a Python 3.12 multi-agent platform. The first MVP is a
**Multi-LLM Technical Report Reviewer** that reviews Markdown reports through
specialized agents and produces Markdown plus JSON review results.

Current release candidate: **v0.3.0**. See
[docs/release-v0.3.0.md](docs/release-v0.3.0.md) for release notes and
[docs/runbook-v0.3.md](docs/runbook-v0.3.md) for reproducible local workflows.

v0.3 adds an opt-in official-evidence foundation for Fact Agent grounding. The
default review path remains evidence-disabled and preserves the v0.2 workflow.

## MVP Scope

- Python 3.12 project managed by `uv`
- LangGraph-based multi-agent orchestration
- LiteLLM model access for OpenAI, DeepSeek, and GLM-compatible models
- Markdown input
- Markdown and JSON review output
- Prompt assets under `prompts/`
- Configuration under `configs/`
- Initial agents:
  - Fact Agent
  - Security Agent
  - Logic Agent
  - Merge Agent
- Reserved interfaces for future Web UI, Docker, Kubernetes, GitHub, and MCP

## Quick Start

```powershell
uv sync --extra dev
uv run agent-network doctor
uv run agent-network review reports/sample.md --output outputs/
uv run agent-network review reports/sample.md --mode mock --output outputs/mock
uv run agent-network review reports/sample.md --mode real --output outputs/real_balanced --open
uv run agent-network review reports/sample.md --only fact --mode mock
uv run agent-network review reports/sample.md --only merge --mode real --output outputs/real_merge
uv run agent-network baseline --input outputs/real_balanced/review.json --output docs/baseline-v0.1.md
uv run agent-network stats
uv run pytest
```

Minimal usage:

```powershell
uv run agent-network review reports/sample.md --mode mock --output outputs/mock
```

Model credentials are read by LiteLLM from `.env` environment variables. The
default provider is SiliconFlow through its OpenAI-compatible API. Set
`SILICONFLOW_API_KEY` for the default path, or use `OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`, and `ZAI_API_KEY` when switching agents back to official
providers.
When API keys are missing, the MVP falls back to deterministic mock mode so the
full review pipeline remains runnable.

Use `--mode real` to require real provider calls and fail fast when any required
API key is missing. Use `--mode mock` for deterministic local runs.
In real mode, the report content and prompt text are sent to the configured
external model provider. `.env` must not be committed and API keys are never
written to review outputs.

The SiliconFlow OpenAI-compatible API base is configured as:

```text
https://api.siliconflow.cn/v1
```

Default SiliconFlow models:

```text
Fact: deepseek-ai/DeepSeek-V4-Pro
Security: Qwen/Qwen3.6-35B-A3B
Logic: deepseek-ai/DeepSeek-V4-Flash
Merge: zai-org/GLM-5.2
```

Agent responsibilities:

```text
Fact: verify factual claims, evidence needs, citations, and technical accuracy.
Security: review cloud-native security risks, unsafe defaults, and hardening gaps.
Logic: check reasoning flow, assumptions, contradictions, and conclusion strength.
Merge: deduplicate and synthesize completed agent reviews into the final report.
```

Agent-level timeouts:

```text
Fact: 90s
Security: 180s
Logic: 120s
Merge: 120s
```

DeepSeek-R1 is kept as an optional `high_reasoning` profile and is not used by
default.

`--only merge` runs the Merge Agent against a fixed in-code fixture that mimics
Fact, Security, and Logic outputs. This makes Merge independently testable
without rerunning the upstream agents.

Security structured output handling:

- Agent responses are parsed as a unified JSON review schema.
- Markdown code fences and surrounding explanatory text are stripped before parsing.
- The first parse failure triggers one JSON-format repair retry.
- If repair fails, the agent is marked `parse_failed`; its raw business findings
  are not mixed into consolidated findings.

Output layout:

```text
outputs/
  review.md
  review.json
  latest.json
  runs/
    <run-id>/
      review.md
      review.json
      run.json
```

`review.md` is designed for direct human reading. In VS Code, open `review.md`
and press `Ctrl + Shift + V` to preview Markdown.

`review.json` keeps the audit trail: metadata, execution status, summary object,
merged findings, original agent reviews, disagreements, and execution notes.

Known compatibility note: with SiliconFlow + `Qwen/Qwen3.6-35B-A3B` + LiteLLM,
Security responses may place complete structured JSON in `message.reasoning_content`
while `message.content` is empty. Agent Network v0.2 keeps `message.content` as
the primary path and uses `reasoning_content` only when it clearly contains
complete review JSON.

## Project Layout

```text
configs/              Runtime configuration
docs/                 Architecture and roadmap documentation
examples/             Example Markdown reports and workflows
prompts/              Versioned agent prompt templates
src/agent_network/    Python package source
tests/                Unit tests
```

See [docs/architecture.md](docs/architecture.md) for the reviewer architecture and
[docs/architecture-v0.3-evidence-pipeline.md](docs/architecture-v0.3-evidence-pipeline.md)
for the official-evidence pipeline.
