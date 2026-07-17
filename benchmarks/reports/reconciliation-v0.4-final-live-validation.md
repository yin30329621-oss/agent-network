# Agent Network v0.4 Final Live Validation

## Execution command

```bash
uv run agent-network verify-report \
  benchmarks/fixtures/report-verification-v0.4-baseline-v1/report.md \
  --output benchmarks/results-local/report-verification-v0.4-baseline-v1/live-artifact.json \
  --offline \
  --enable-dual-fact \
  --batch-size 5 \
  --confirm-live-model-calls \
  --confirm-planned-call-count 8
```

## Input fixture

`benchmarks/fixtures/report-verification-v0.4-baseline-v1/report.md`

## Artifact

`benchmarks/results-local/report-verification-v0.4-baseline-v1/live-artifact.json`

The artifact contains:

- `claims`
- `evidence`
- `fact_review`
- `reconciliation`
- `statistics`

## Validation results

| Metric | Result |
|---|---:|
| Claim count | 19 |
| Batch size | 5 |
| Planned reviewer calls | 8 |
| Actual reviewer batch calls | 8 |
| Fact A calls | 4 |
| Fact B calls | 4 |
| Workflow model call count | 8 |
| Evidence network requests | 0 |
| Reconciliation entries | 19 |
| Manual review required | 19 |

Reconciliation distribution:

- `manual_review_required`: 19
- `needs_manual_review=true`: 19

## Baseline comparison

| Metric | v0.3.1 baseline | v0.4 execution |
|---|---:|---:|
| Claims | 19 | 19 |
| Batch size | 5 | 5 |
| Fact A calls | 4 | 4 |
| Fact B calls | 4 | 4 |
| Total planned calls | 8 | 8 |
| Evidence network requests | 0 | 0 |

## Success assessment

The report-level workflow executed successfully and produced the expected
artifact shape, Claim count, batch plan, reviewer batch count, and zero-network
evidence behavior.

However, this is not a valid real-model live validation. The current
`verify-report` CLI constructs `FakeFactReviewer` for Fact A and Fact B.
The reported 8 calls represent deterministic reviewer batch executions; the
artifact also reports `coordinator_model_call_count=0`. No real provider model
call was made.

## Current limitations

- Real Fact A/B reviewer construction is not wired into `verify-report`.
- `--confirm-live-model-calls` currently gates the workflow but does not
  replace the fake reviewers with configured model-backed reviewers.
- The 8-call result must not be interpreted as a provider or model latency /
  response validation.
- A separate implementation is required before repeating this command as a
  genuine live validation.
