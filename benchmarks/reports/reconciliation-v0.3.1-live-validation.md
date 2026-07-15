# Reconciliation v0.3.1 Live Validation Report

**Checkpoint:** 0d6ba50  
**Validation date:** 2026-07-15  
**Benchmark:** Rancher Report Dual Fact Benchmark v1  
**Execution:** Existing live benchmark workflow with 8 confirmed model calls

## 1. Execution summary

The benchmark was run with the existing command and current v0.3.1 code:

- Claims: 19
- Batches: 4, sized [5, 5, 5, 4]
- Fact A calls: 4
- Fact B calls: 4
- Total model calls: 8
- Per-claim model calls: 0
- Retry count: 0
- Runtime: 306.41 seconds
- Result records: 19

No source code, tests, configuration, or workflow files were modified.

## 2. Evidence and provider availability

| Metric | Result |
| --- | ---: |
| Fact A available | 19/19 |
| Fact B available | 19/19 |
| Fact A parsed | 19/19 |
| Fact B parsed | 19/19 |
| Fact A audit status completed | 19/19 |
| Fact B audit status completed | 19/19 |
| Fact A finish_reason=stop | 19/19 |
| Fact B finish_reason=stop | 19/19 |
| Citation audit warnings | 0 |
| Evidence/retrieval network calls | 0 |

The evidence path used the existing offline fixture and local retrieval flow. The provider runtime emitted a LiteLLM warning after a timeout while attempting to fetch its remote model-cost map; it fell back to the local backup. This was auxiliary provider metadata handling, not an evidence retrieval call, and did not change the planned 8 model calls.

## 3. Reconciliation status distribution

| Status | Claims | Share |
| --- | ---: | ---: |
| consensus | 3 | 15.8% |
| engine_challenged | 1 | 5.3% |
| reviewer_disagreement | 12 | 63.2% |
| manual_review_required | 3 | 15.8% |
| **Total** | **19** | **100%** |

There were no invalid_citation, single_reviewer_available, or parse-failure results in this run.

The 12 reviewer disagreements were:

- rr-004
- rr-005
- rr-006
- rr-007
- rr-008
- rr-009
- rr-010
- rr-011
- rr-016
- rr-017
- rr-018
- rr-019

## 4. Manual review distribution

| Routing field | Result |
| --- | ---: |
| needs_manual_review=true | 15/19 |
| needs_manual_review=false | 4/19 |
| review_priority=high | 3 |
| review_priority=normal | 16 |

Manual-review reasons:

| Reason | Claims |
| --- | ---: |
| reviewer_status_disagreement | 12 |
| evidence_gate_blocked_upgrade | 3 |

The 3 high-priority evidence-gated claims were:

- rr-012
- rr-014
- rr-015

The remaining 12 manually routed claims were genuine reviewer disagreements and retained normal priority.

## 5. Evidence gate validation

The evidence gate triggered when the deterministic EvidenceDecisionEngine result did not support the stronger reviewer outcome. These cases were returned as manual_review_required rather than being accepted automatically.

For each gated claim:

- both Fact reviewers were available;
- both responses parsed successfully;
- no additional model call was made;
- the original reviewer outputs remained in the reconciliation record;
- manual_review_reasons contained evidence_gate_blocked_upgrade;
- review_priority was high.

This confirms that v0.3.1 applies evidence constraints after independent Fact A/B execution without changing reviewer isolation.

## 6. Cost and workflow validation

Compared with the v0.3 baseline:

- Total model calls remained 8.
- Fact A/B remained 4 calls each.
- Evidence/retrieval network calls remained 0.
- No per-claim calls were introduced.
- No retry calls were introduced.
- The four-agent workflow and Dual Fact batch plan were unchanged.

## 7. Conclusion

The current v0.3.1 live validation completed successfully. Both Fact providers returned fully parseable results for all 19 claims, and the new local Reconciliation layer produced structured manual-review routing and blocked 3 evidence-insufficient upgrades.

The benchmark remains within the established cost boundary of 8 model calls and 0 evidence network calls. The only runtime warning concerned LiteLLM's remote cost-map lookup and was handled by its local fallback.
