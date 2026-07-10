# Agent Network v0.2 Release Notes

## v0.2 Goal

Agent Network v0.2 stabilizes the Multi-LLM Technical Report Reviewer around
structured output, auditable execution, readable reports, and a strict
four-call workflow.

## Four Agent Architecture

Workflow:

```text
Fact -> Security -> Logic -> Merge
```

No new default agents were added in v0.2.

## Model Assignment

| Agent | Provider | Model |
| --- | --- | --- |
| Fact | siliconflow | deepseek-ai/DeepSeek-V4-Pro |
| Security | siliconflow | Qwen/Qwen3.6-35B-A3B |
| Logic | siliconflow | deepseek-ai/DeepSeek-V4-Flash |
| Merge | siliconflow | zai-org/GLM-5.2 |

## Unified Finding Schema

Findings now use one normalized schema with:

- `id`
- `agent`
- `provider`
- `model`
- `severity`
- `location`
- `issue`
- `reason`
- `evidence_needed`
- `reference`
- `suggestion`
- `confidence`
- `status`

Severity is normalized to `critical`, `high`, `medium`, `low`, or `info`.
Confidence is clamped to `0..1`.

## Security Structured Parsing

Security output parsing now:

- Prefers `message.content`
- Falls back to compatible fields only when they clearly contain review JSON
- Records provider response audit metadata without storing API keys
- Separates parse failures from business findings

## Local JSON Repair

JSON repair is purely local. It does not call another model and does not
increase the default workflow call count.

## Four-Call Constraint

The default real workflow remains exactly four business model calls:

```text
Fact 1 + Security 1 + Logic 1 + Merge 1
```

## Merge Judge And Deduplication

Merge now performs rule-based deduplication and preserves:

- supporting agents
- dissenting agents
- source finding IDs
- original severities
- merged severity
- decision reason
- human review markers

## Output Structure

`review.md` is human-readable and includes:

- Executive Summary
- Agent Execution Status
- Consolidated Findings
- Agent Disagreements
- Unique Findings
- Execution Notes

`review.json` preserves audit details:

- metadata
- execution
- summary object
- merged findings
- original agent reviews
- disagreements
- execution notes

## Run Registry

Completed runs are stored under:

```text
outputs/runs/<run-id>/
  review.md
  review.json
  run.json
```

`outputs/latest.json` points to the latest completed run.

## CLI Additions

- `agent-network baseline`
- `agent-network stats`
- `agent-network review --open`
- `agent-network --version`

## Local Test Results

Release checks:

```text
uv run pytest
28 passed

uv run ruff check .
All checks passed!

uv run ruff format --check .
28 files already formatted
```

## Real API Validation

Three release-candidate real SiliconFlow runs completed with exactly four
business model calls each.

RC run IDs:

- `run-e92fe570a78b`
- `run-b2ae2dbbaa78`
- `run-5a6b889fb848`

Security completed in all three RC runs.

## Known Compatibility Note

With SiliconFlow + `Qwen/Qwen3.6-35B-A3B` + LiteLLM, Security responses may
return empty `message.content` while complete structured JSON appears in
`message.reasoning_content`. Agent Network v0.2 keeps `message.content` as the
primary extraction path and only uses `reasoning_content` when it clearly
contains complete review JSON.

## Known Limitations

- Security may still report `finish_reason=length` with this provider/model
  combination.
- Rule-based deduplication is intentionally conservative.
- `baseline` test result capture is currently marked `unavailable` unless
  provided externally.
- Real runs send report content and prompts to the configured external model
  provider.

## Upgrade Notes

- Set `SILICONFLOW_API_KEY` in `.env` for real mode.
- Do not commit `.env`.
- `outputs/` is ignored by default and should usually not be committed.
- Existing v0.1 commands remain compatible.

## Release Decision

v0.2 is approved for release with the compatibility note above. The default
workflow, structured outputs, run registry, and local tests are stable enough
for the v0.2 release baseline.
