# Agent Network v0.3.1 Release Summary

**Release scope:** Reconciliation enhancement for the evidence verification milestone  
**Feature checkpoint:** f989675  
**Documentation checkpoints:** 0d6ba50, 0011717  
**Branch:** main

## 1. Version goal

v0.3.1 improves the local deterministic Reconciliation layer while preserving the stable v0.3 execution model.

The release goal is to make Dual Fact results more consistent, evidence-aware, and actionable for human review without adding agents, model calls, network evidence retrieval, or changes to the existing four-agent workflow.

## 2. Main changes from v0.3 to v0.3.1

| Area | v0.3 | v0.3.1 |
| --- | --- | --- |
| Reviewer comparison | Exact reviewer status string comparison | Canonical status normalization |
| Evidence constraints | Evidence status used for challenge comparison | Evidence gating prevents unsupported upgrades |
| Manual review | Mostly represented by top-level status | Structured routing metadata and priority |
| Result serialization | Original reconciliation fields | Additive metadata with legacy JSON defaults |
| Dual Fact isolation | Independent Fact A/B | Unchanged |
| Batch and call plan | 19 claims, 4 batches, 8 calls | Unchanged |

The standard workflow remains:

Fact -> Security -> Logic -> Merge

Dual Fact remains an independent Fact-stage verification module and does not add another agent to this workflow.

## 3. Current system architecture

The system has two related paths.

### Standard technical report workflow

Fact -> Security -> Logic -> Merge

The four agents continue to perform factual, security, logic, and synthesis review.

### Evidence verification path

Document Catalog
  -> Fetcher
  -> Cleaner
  -> Deterministic Chunker
  -> Offline BM25 Retriever
  -> Evidence Injection
  -> Fact / Dual Fact
  -> Local Reconciliation

The evidence path prioritizes official documents and offline evidence fixtures. Evidence is bounded, chunk-based, and citation-validated. Fact A and Fact B receive the same Claim, Evidence, and Verification Engine input, but never see each other's output.

## 4. Reconciliation enhancement

### Canonical status normalization

Reviewer status strings are preserved as received, while an additional canonical status is used for comparison. Examples include:

- active and verified_candidate -> supported
- candidate_only and partially_supported -> partially_supported
- unsupported, not_supported, and withdrawn -> unsupported
- unverifiable -> insufficient_evidence
- needs_review and manual_review_required -> manual_review

This avoids false disagreement caused only by different labels. It does not merge semantically different outcomes such as supported and partially_supported.

### Evidence gating

The EvidenceDecisionEngine provides deterministic gating constraints for evidence sufficiency.

When a reviewer attempts to upgrade an evidence result that is unsupported, insufficient_evidence, manual_review_required, or partially_supported, Reconciliation does not accept the stronger result automatically. It returns manual_review_required with the reason evidence_gate_blocked_upgrade.

This gate is local and deterministic. It does not re-prompt either reviewer or create any additional model call.

### Manual review routing

Reconciliation now exposes:

- needs_manual_review
- manual_review_reasons
- review_priority

Typical routing outcomes are:

| Condition | Priority | Reason |
| --- | --- | --- |
| Invalid citation | High | invalid_citation |
| Both reviewers unavailable | High | both_reviewers_unavailable |
| One reviewer available | High | single_reviewer_available |
| Evidence upgrade blocked | High | evidence_gate_blocked_upgrade |
| Reviewer disagreement | Normal | reviewer_status_disagreement |
| Valid consensus | Normal | No manual review required |

Existing top-level status values and reviewer results remain available for backward compatibility.

## 5. Benchmark and live validation results

### Regression validation

Current test and lint status:

- pytest: 361 passed
- Ruff: passed

### Rancher Report Dual Fact Benchmark v1

The existing benchmark uses:

- 19 claims
- 4 batches: [5, 5, 5, 4]
- 4 Fact A calls
- 4 Fact B calls
- 8 total model calls
- 0 evidence retrieval network calls
- 0 per-claim model calls
- 0 retries

### v0.3.1 live validation

The live validation completed successfully:

- Fact A: 19/19 available and parsed
- Fact B: 19/19 available and parsed
- Fact A and Fact B finish_reason: stop for all 19 results
- Citation audit warnings: 0
- Runtime: 306.41 seconds
- Reconciliation:
  - consensus: 3
  - engine_challenged: 1
  - reviewer_disagreement: 12
  - manual_review_required: 3
- Manual review routing: 15/19 claims
- Evidence gate triggered: 3 claims
  - rr-012
  - rr-014
  - rr-015

The validation report is recorded in:

benchmarks/reports/reconciliation-v0.3.1-live-validation.md

The runtime included a LiteLLM remote model-cost map timeout followed by local fallback. This did not add evidence retrieval calls or change the planned model call count.

## 6. Cost and call constraints

v0.3.1 maintains the established operating limits:

- No additional agents.
- No additional LLM calls.
- No per-claim model calls.
- No additional retry calls.
- No evidence network requests.
- No change to Fact A/B independence.
- No change to the four-agent workflow.
- No change to the 4-batch benchmark plan.

All new behavior is deterministic local post-processing after Fact A/B results are available.

## 7. Current limitations and follow-up planning

Current limitations:

- Reviewer disagreement remains common and still requires human interpretation.
- Evidence gating identifies an unsupported upgrade but does not resolve the underlying claim.
- Manual review metadata provides routing reasons, not a complete reviewer work queue or UI.
- Status normalization is alias-based and may need extension as providers introduce new labels.
- The current benchmark is based on fixed fixtures and a single live validation snapshot.
- The provider cost-map warning shows that auxiliary provider metadata lookup can still affect runtime even when evidence retrieval is offline.
- Evidence gating currently blocks upgrades for specific evidence statuses; independent manual-review escalation strategies are not yet defined for all conflicting_evidence and version_mismatch cases.

Planned follow-up:

1. Add a stable manual-review export or queue contract.
2. Add claim-level reconciliation explanations based only on existing evidence and reviewer outputs.
3. Track review resolution outcomes for future benchmark evaluation.
4. Expand status normalization fixtures for provider-specific response vocabulary.
5. Separate provider auxiliary metadata latency from benchmark runtime reporting.
6. Re-run live validation only when a new behavior or provider configuration requires measurement.

## 8. Release conclusion

v0.3.1 is a backward-compatible refinement of the v0.3 evidence verification milestone. It improves reconciliation consistency and review routing while keeping the architecture, isolation guarantees, batch plan, model cost, and evidence network budget unchanged.
