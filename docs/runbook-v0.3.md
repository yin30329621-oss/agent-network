# v0.3.0 Runbook

## Local Setup

```powershell
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run agent-network --version
```

Normal tests are offline and use no real model calls. Do not use a private report
or generated review output as a release fixture.

## Standard Review

Evidence is off by default, so normal review behavior is compatible with v0.2:

```powershell
uv run agent-network review reports/sample.md --mode mock --output outputs/mock
```

Real review requires the configured provider credentials and sends the report and
prompts to that provider. Treat it as a separate, operator-approved activity.

## Local-Cache Evidence

Before enabling `local_cache`, create a controlled official-document cache through
the opt-in synchronization tooling. Configure Fact Evidence with `enabled: true`,
`provider: local_cache`, and a cache directory under
`data/official-evidence-cache/`. Local-cache retrieval is strictly offline and
never downloads missing documents during review.

Keep Fact evidence bounds at the configured limits: Top-K evidence, a maximum
per-evidence character count, and a maximum total-evidence character count.
Only validated chunk IDs, document IDs, and canonical URLs may appear in Fact
citations.

## Synchronizer And Cache Inspection

Use the benchmark synchronization entrypoints in plan mode first. A live sync
requires explicit network permission, explicit cache directory, and exact planned
document-count confirmation. Cache entries contain `raw.html`, `cleaned.json`,
and `metadata.json`; do not commit them.

## Live Fact Evidence A/B

The live harness is opt-in and is not part of pytest or CI. First use plan mode:

```powershell
uv run python -m benchmarks.fact_evidence_live_ab --plan --model <configured-fact-model> --max-cases 2
```

Live execution additionally requires `--run-live`, explicit model selection,
`--confirm-live-model-calls`, and an exact
`--confirm-planned-call-count`. It defaults to no saved results, redacted prompts,
and no raw model responses. When saving, use only `benchmarks/results-local/`.

## Release Checks

Before release, run the commands in [baseline-v0.3.md](baseline-v0.3.md), confirm
that `.env`, `outputs/`, private reports, and local cache directories are ignored,
and review [known-limitations-v0.3.md](known-limitations-v0.3.md). Do not create a
tag or publish until the release reviewer accepts the documented limitations.
