# v0.3.0 Release Candidate Baseline

## Scope

This baseline covers the v0.3 official-evidence foundation and its compatibility
with the existing four-agent review workflow. It is intentionally local and
deterministic.

## Required Verification

Run from the repository root:

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git diff --check
uv run agent-network --version
```

The release candidate expects package and CLI version `0.3.0`.

## RC Verification Result

Verified locally for this release-candidate preparation:

- `uv run pytest -q`: `268 passed`
- `uv run ruff check .`: passed
- `uv run ruff format --check .`: passed (`88 files already formatted`)
- `git diff --check`: passed
- `uv run agent-network --version`: `agent-network 0.3.0`

## Test Guarantees

The relevant suites cover catalog validation and ordering, URL/domain checks,
mocked HTTP behavior, cleaner determinism, chunk boundaries, BM25 filters,
cached multi-document retrieval, synchronizer atomic writes, Fact Evidence
injection, citation validation, relation/limitation validation, and A/B harness
safety gates.

Ordinary test execution must satisfy:

- real network requests: `0`
- real model calls: `0`
- automatic live A/B execution: disabled
- read access to private reports and generated review outputs: not required

## Runtime Invariants

- Evidence default configuration is disabled.
- `local_cache` has no network fallback.
- Fact Evidence injects bounded chunks only, never full HTML or full documents.
- Citation IDs must come from the provided evidence set.
- A normal full review with valid specialist results uses Fact, Security, Logic,
  and Merge for four business model calls.

## Result Recording

Record the actual release-candidate command results in the release review or
change record. Do not place live-model responses, API keys, local cache content,
or private reports in this baseline document.
