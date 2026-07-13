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

## v0.3: Official Evidence Foundation (release candidate)

- Offline Claim, Evidence, Matcher, verification rules, fixtures, and reporting
- NVD and GitHub Global Security Advisory sources with cache, whitelist, and public-CVE pilot
- Official Document Catalog, HTTPS Fetcher, Cleaner, deterministic Chunker, and offline BM25
- Official Evidence Retriever, Synchronizer / Cache, and cached multi-document retrieval
- Optional Fact Evidence grounding through fixture or forced-offline `local_cache` providers
- Programmatic citation validation, `evidence_relation`, and `evidence_limitations`
- Evidence OFF / ON acceptance harnesses with explicit live-model safety gates

v0.3.0 is frozen for release-candidate validation. The default reviewer remains the
four-Agent workflow, while evidence is opt-in and does not enable network access by default.

## v0.4: Integrations And Evidence Expansion

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
