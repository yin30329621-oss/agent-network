# Agent Network Baseline v0.2 Release Candidate

## Version

0.2.0 release candidate

## Date

2026-07-10

## Source Report

reports/sample.md

## Workflow

Fact -> Security -> Logic -> Merge

## Models

| Agent | Provider | Model | Timeout |
| --- | --- | --- | ---: |
| Fact | siliconflow | deepseek-ai/DeepSeek-V4-Pro | 90s |
| Security | siliconflow | Qwen/Qwen3.6-35B-A3B | 180s |
| Logic | siliconflow | deepseek-ai/DeepSeek-V4-Flash | 120s |
| Merge | siliconflow | zai-org/GLM-5.2 | 120s |

## Runtime

Baseline run: `run-b2ae2dbbaa78`

| Agent | Status | Elapsed | Error |
| --- | --- | ---: | --- |
| fact | completed | 177.3s |  |
| security | completed | 14.6s |  |
| logic | completed | 111.1s |  |
| merge | completed | 28.3s |  |

## Total Runtime

331.3s

## Output Files

- outputs/runs/run-b2ae2dbbaa78/review.md
- outputs/runs/run-b2ae2dbbaa78/review.json
- outputs/runs/run-b2ae2dbbaa78/run.json

## Finding Statistics

- Critical: 1
- High: 5
- Medium: 2
- Low: 0
- Info: 1
- Merged findings: 9
- Disagreements: 1
- Needs human review: true

## Release Candidate Validation

Three real SiliconFlow runs were executed with four business model calls each.
Security completed in all three runs, but all three Security responses ended
with `finish_reason=length` and were extracted from `message.reasoning_content`
rather than `message.content`.

| Run | Security Status | Finish Reason | Content Length | Reasoning Length | Extracted Field |
| --- | --- | --- | ---: | ---: | --- |
| run-e92fe570a78b | completed | length | 0 | 6896 | message.reasoning_content |
| run-b2ae2dbbaa78 | completed | length | 0 | 7096 | message.reasoning_content |
| run-5a6b889fb848 | completed | length | 0 | 6942 | message.reasoning_content |

## Tests

- `uv run pytest`: 28 passed
- `uv run ruff check .`: passed
- `uv run ruff format --check .`: passed

## Current Features

- Four-agent technical report review workflow
- SiliconFlow real mode and deterministic mock mode
- Structured parser with local repair
- Provider response audit metadata
- Merge Judge and rule-based deduplication
- Markdown and JSON outputs
- Run registry, baseline, and stats commands

## Known Limitations

- Security model `Qwen/Qwen3.6-35B-A3B` frequently returns empty
  `message.content` with useful JSON in `message.reasoning_content` when
  `finish_reason=length`.
- The compatibility path safely extracts `reasoning_content` only when it
  contains complete review JSON, but the release candidate did not meet the
  target of at least two Security runs using `message.content`.
- One of the three RC runs had a Logic Agent validation failure, while Security
  still completed successfully.

## Next Milestone

Evaluate a Security-specific token budget or prompt/provider behavior change
without increasing the default workflow call count.
