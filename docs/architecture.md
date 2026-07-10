# Agent Network Architecture

## MVP Architecture

The first version of Agent Network is a Python 3.12 modular application focused
on multi-agent review of Markdown technical reports.

```text
Markdown Input
     |
Review CLI / API Boundary
     |
LangGraph Review Workflow
     |
+------------+  +----------------+  +-------------+
| Fact Agent |  | Security Agent |  | Logic Agent |
+------------+  +----------------+  +-------------+
          \          |          /
             Merge Agent
                  |
        Markdown + JSON Output
```

## Key Decisions

- Python 3.12 is the main implementation language.
- `uv` manages project dependencies and local execution.
- LangGraph orchestrates the multi-agent workflow.
- LiteLLM provides a single abstraction over SiliconFlow, OpenAI, DeepSeek, and
  GLM/ZAI providers.
- SiliconFlow is the default provider through its OpenAI-compatible API base.
- API keys are loaded from `.env` through `python-dotenv`.
- Missing API keys trigger deterministic mock mode for local testing.
- Prompt templates live outside code under `prompts/`.
- Runtime configuration lives under `configs/`.
- Docker, Kubernetes, GitHub, Web UI, and MCP are not implemented in the MVP,
  but their integration boundaries are reserved.

## Module Boundaries

| Module | Responsibility |
| --- | --- |
| `agents` | Agent interfaces and built-in reviewer agents |
| `workflow` | LangGraph graph construction and review orchestration |
| `llm` | LiteLLM adapter and test doubles |
| `prompts` | Prompt loading and rendering |
| `config` | YAML configuration loading |
| `schemas` | Shared review result data structures |
| `outputs` | Markdown and JSON serialization |
| `integrations` | Reserved ports for MCP, GitHub, Kubernetes, and Docker |

## Unified Finding Schema

Fact, Security, Logic, and Merge use one normalized finding schema with stable
fields for `id`, `agent`, `provider`, `model`, `severity`, `location`, `issue`,
`reason`, `evidence_needed`, `reference`, `suggestion`, `confidence`, and
`status`. Severity is normalized to `critical`, `high`, `medium`, `low`, or
`info`; confidence is clamped to `0..1`.

## Agent Execution Status

Each agent records status, provider, model, elapsed time, and sanitized error
metadata. Structured parsing failures are recorded as execution notes and are
kept separate from business findings.

## Judge And Deduplication

The Merge Agent receives all agent findings and execution statuses. A
deterministic deduplication pass groups obvious duplicates using normalized
locations, issue text, keyword rules, and string similarity without adding LLM
calls. The Merge Agent then acts as a Judge over merged findings and preserves
supporting agents, dissenting agents, original severities, decision reasons,
and human-review markers.

## Output Separation

`review.md` is human-readable and contains only the executive summary,
execution status, consolidated findings, disagreements, unique findings, and
execution notes. `review.json` preserves full audit details, including original
agent reviews.

## Run Registry

Completed runs are copied to `outputs/runs/<run-id>/` with `review.md`,
`review.json`, and `run.json`. `outputs/latest.json` points to the latest
completed run, with real runs preferred when available. Run records do not store
prompt text or API keys.

## Future Integration Ports

Integration ports are intentionally defined as interfaces first. Concrete
implementations can be added later without changing the agent workflow.

- MCP: expose tools and consume external MCP servers.
- GitHub: review pull requests and publish review comments.
- Kubernetes: inspect cluster manifests and live resources.
- Docker: inspect Dockerfiles, Compose files, and image metadata.

## Testing Strategy

The core schema, prompt loader, output serializers, and merge behavior should be
unit tested without model calls. LangGraph and LiteLLM integration tests should
use fake LLM clients by default and real providers only in opt-in tests.
