# Agent Network v0.4 Real Live Validation

## Execution command

```bash
uv run agent-network verify-report \
  benchmarks/fixtures/report-verification-v0.4-baseline-v1/report.md \
  --output benchmarks/results-local/report-verification-v0.4-baseline-v1/live-artifact-real.json \
  --offline \
  --enable-dual-fact \
  --batch-size 5 \
  --confirm-live-model-calls \
  --confirm-planned-call-count 8
```

## Input and artifact

- Input fixture: `benchmarks/fixtures/report-verification-v0.4-baseline-v1/report.md`
- Artifact: `benchmarks/results-local/report-verification-v0.4-baseline-v1/live-artifact-real.json`
- Runtime: approximately 282.3 seconds
- Claim count: 19
- Batch size: 5

## Call results

| Metric | Result |
|---|---:|
| Planned reviewer calls | 8 |
| Fact A calls | 4 |
| Fact B calls | 4 |
| Actual reviewer batch calls | 8 |
| Workflow model call count | 8 |
| Coordinator model call counter | 0 |
| Adapter model call counter | 0 |
| Evidence network requests | 0 |

The command completed successfully with the live confirmation flags. Fact A
and Fact B returned reviewer result batches through the real reviewer branch.
The workflow's `actual_reviewer_calls=8` records the eight provider batch
executions.

The artifact's `coordinator_model_call_count=0` and
`adapter_model_call_count=0` remain zero because the current coordinator
telemetry does not increment those counters for provider-backed reviewer
adapters. They should not be interpreted as evidence that no provider calls
occurred.

## Reconciliation distribution

- `single_reviewer_available`: 5
- `reviewer_disagreement`: 14
- Total reconciliation entries: 19

## Baseline comparison

| Metric | v0.3.1 baseline | v0.4 real validation |
|---|---:|---:|
| Claims | 19 | 19 |
| Batch size | 5 | 5 |
| Fact A calls | 4 | 4 |
| Fact B calls | 4 | 4 |
| Total planned calls | 8 | 8 |
| Evidence network requests | 0 | 0 |

## Assessment

The real-model live validation completed successfully for the full report-level
workflow. Claim extraction, offline evidence processing, Fact A/B execution,
and reconciliation all completed with the expected 19-claim and 8-call plan.

Current limitation: provider-level call counters in the artifact are not
populated by the existing coordinator telemetry. The reliable call evidence
for this run is the successful real reviewer batch execution and
`actual_reviewer_calls=8`; provider counter instrumentation would be a
separate follow-up improvement.
