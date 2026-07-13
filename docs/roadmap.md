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

## v0.3: Evidence Verification / RAG MVP (in progress)

- Phase 1: offline Claim, Evidence, Matcher, verification rules, fixtures, and reporting
- Phase 2A: NVD and GitHub Global Security Advisory sources, cache, whitelist, and
  public-CVE pilot command (implemented; real pilot pending explicit approval)
- Phase 2B: Rancher/SUSE Security Advisory and Release Notes sources
- Phase 3: versioned local Rancher/SUSE/Kubernetes document index
- Phase 4: evidence-aware Security review and Merge Evidence Judge
- Phase 5: verification accuracy, evidence recall, citation error, cost, and latency benchmark

v0.3 is under development and is not released. The v0.2 four-Agent workflow remains
the stable default while Phase 1 is developed as an isolated offline subsystem.

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
