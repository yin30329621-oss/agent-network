# Roadmap

## v0.1: Basic Real Multi-Agent Workflow

- Project skeleton with `uv`
- Core review schemas
- Prompt loading from `prompts/`
- Config loading from `configs/`
- Fact, Security, Logic, and Merge agents
- LangGraph workflow
- Markdown input and Markdown/JSON output
- Basic unit tests

## v0.2: Structured Review And Reporting (completed)

- Structured output parsing and repair retry
- Unified finding schema
- Merge Judge
- Rule-based deduplication
- Better Markdown review UX
- Run registry
- Baseline command
- Stats command

## v0.3: Reviewer Hardening

- Structured JSON validation for model outputs
- Golden-file tests for prompt rendering and report formatting
- Retry, timeout, and partial failure handling
- Provider/model selection per agent
- Review severity policy configuration

## Phase 3: Integrations

- GitHub pull request review
- MCP client and server adapters
- Dockerfile and Compose review helpers
- Kubernetes manifest review helpers

## Phase 4: Runtime Platform

- Persistent run history
- Human approval checkpoints
- Plugin SDK
- Docker image and Kubernetes deployment manifests
- Optional Web UI
