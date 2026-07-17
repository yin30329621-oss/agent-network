# v0.4 M3.3b.2 Live Validation Report

## Validation scope

Target chain:

`report.md+ßuÁ‚ùÁR verify-report ∫w^~)ﬁv Claim Extraction"È›y¯ßy“ Evidence Pipeline ∫w^~)ﬁv Dual Fact ∫w^~)ﬁv Reconciliation+ßuÁ‚ùÁR artifact`

The requested command was:

```bash
uv run agent-network verify-report benchmarks/fixtures/report-verification-e2e-v1/report.md \
  --output /tmp/report-verification-m3.3b2.json \
  --offline \
  --enable-dual-fact \
  --confirm-live-model-calls \
  --confirm-planned-call-count 8
```

## Result

The current `verify-report` CLI does not define `--confirm-live-model-calls` or
`--confirm-planned-call-count`. The requested command therefore exits before
executing the workflow with:

`No such option: --confirm-live-model-calls`

No source code or test changes were made to work around this limitation.

For diagnostic purposes, the currently supported equivalent was executed:

```bash
uv run agent-network verify-report benchmarks/fixtures/report-verification-e2e-v1/report.md \
  --output /tmp/report-verification-m3.3b2.json \
  --offline \
  --enable-dual-fact
```

## Offline artifact observations

- Claim count: 2
- Evidence results: 2
- Evidence network requests: 0
- Fact A results: 2
- Fact B results: 2
- Estimated reviewer calls: 2
- Actual reviewer calls: 2
- Reported model calls: 2
- Reconciliation entries: 2
- Reconciliation distribution: `manual_review_required=2`
- Artifact sections present: `metadata`, `claims`, `evidence`, `fact_review`, `reconciliation`, `statistics`

Fact A and Fact B are emitted as separate reviewer result collections with
distinct reviewer identifiers. The coordinator metadata reports zero provider
model calls because the CLI uses `FakeFactReviewer`; the workflow-level
metadata counts the two deterministic reviewer executions.

## Conclusion

The offline end-to-end artifact path executes successfully and preserves the
artifact sections and reconciliation claim IDs. M3.3b.2 live validation is not
completed: the current CLI lacks the requested live-call confirmation options,
and its offline Dual Fact path uses deterministic fake reviewers rather than
real model providers. The target of 8 model calls cannot be verified without a
separate implementation change.
