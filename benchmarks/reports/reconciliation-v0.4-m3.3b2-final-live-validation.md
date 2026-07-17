# v0.4 M3.3b.2 Final Live Validation

## Requested execution

```bash
uv run agent-network verify-report benchmarks/rancher-report-v1.md \
  --output benchmarks/results-local/reconciliation-v0.4-m3.3b2-final-live-validation.json \
  --offline \
  --enable-dual-fact \
  --confirm-live-model-calls \
  --confirm-planned-call-count 8
```

## Result

Validation stopped during budget preflight before any reviewer execution.

The current report produced:

- Claim count: 7
- Planned Fact A calls: 3
- Planned Fact B calls: 3
- Planned total calls: 6
- Confirmed planned calls: 8
- Preflight result: rejected because `estimated=6` did not match `confirmed=8`

Therefore:

- Fact A actual calls: 0
- Fact B actual calls: 0
- Total actual model calls: 0
- Evidence network requests: 0
- Reviewer execution: not started
- Reconciliation distribution: unavailable
- Manual review count: unavailable
- Artifact: not generated because execution terminated before workflow completion

## Artifact schema

Because preflight rejected the request, no new artifact was produced for this
run. The artifact sections `claims`, `evidence`, `fact_review`,
`reconciliation`, and `statistics` were therefore not available for this
validation attempt.

## Conclusion

The safety policy behaved as designed: a planned call-count mismatch prevented
Fact A/B execution and avoided model or evidence-network calls. This is not a
successful 8-call live validation. A follow-up run requires either a report
that deterministically plans 8 calls or a separately approved adjustment to the
planned-call confirmation value. No source code, tests, or configuration were
changed.
