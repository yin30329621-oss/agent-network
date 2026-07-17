# Agent Network v0.4 Evaluation

## 1. v0.3.1"È›y¯ßy“ v0.4 evolution

v0.3.1 established evidence-constrained Dual Fact reconciliation for a
predefined Claim set:

```
Claim
∫w^~)ﬁv EvidenceßuÁ‚ùÁR Dual FactßuÁ‚ùÁR Reconciliation
```

v0.4 adds a report-level entry point while preserving the existing Claim,
EvidenceDecision, Dual Fact, and Reconciliation contracts:

```
Markdown report
È›y¯ßy“ Claim ExtractionßuÁ‚ùÁR ClaimRegistry
∫w^~)ﬁv Evidence PipelineßuÁ‚ùÁR Dual Fact Review
∫w^~)ﬁv ReconciliationßuÁ‚ùÁR Artifact
```

The v0.3.1 benchmark and four-agent workflow remain unchanged.

## 2. M1: Markdown Claim Extraction

M1 introduced deterministic Markdown report extraction through:

```bash
agent-network extract-claims report.md
```

The extraction output preserves:

- `claim_id`
- source file and source location
- heading path
- line range
- extraction confidence
- extraction method
- extraction statistics

The output Claim contract is the existing Claim schema. M1 does not perform
fact verification and does not call a model or network service.

## 3. M2: Evidence and Dual Fact integration

M2 connected extracted Claims to the existing evidence and review components:

```
ClaimRegistryßuÁ‚ùÁR Evidence Adapter
∫w^~)ﬁv EvidenceDecision
È›y¯ßy“ FactReviewInput
È›y¯ßy“ DualFactReviewCoordinatorßuÁ‚ùÁR Reconciliation
```

The integration preserves:

- Claim ID alignment
- evidence and citation context
- retrieval and decision failure slots
- independent Fact A/B inputs
- deep-copy isolation of mutable nested input data
- batch reviewer calls
- budget preflight

The existing EvidenceDecisionEngine, DualFactReviewCoordinator, and
Reconciliation rules were reused rather than replaced.

## 4. M3: Report Verification Workflow

M3 added report-level orchestration and the `verify-report` CLI:

```bash
agent-network verify-report report.md
```

The current workflow supports:

- `--offline`
- `--enable-dual-fact`
- `--batch-size`
- `--confirm-live-model-calls`
- `--confirm-planned-call-count`
- `--output`
- `--dry-run`

The artifact schema contains:

- `metadata`
- `claims`
- `evidence`
- `fact_review`
- `reconciliation`
- `statistics`

Live reviewer execution requires explicit confirmation and a matching planned
call count. Evidence retrieval remains offline for the validated workflow.

## 5. Offline E2E benchmark

The v0.4 baseline fixture is:

`benchmarks/fixtures/report-verification-v0.4-baseline-v1/`

It contains a Markdown report that deterministically produces 19 Claims.

With `batch_size=5`:

- Fact A planned calls: 4
- Fact B planned calls: 4
- Total planned calls: 8
- Evidence network requests: 0

The offline E2E benchmark uses deterministic fixture retrieval and
FakeFactReviewer. It validates orchestration, artifact completeness, Claim ID
alignment, batch planning, failure preservation, and zero network cost.

This benchmark does not measure provider quality or real model behavior.

## 6. Real Live Validation

The final real validation used the same 19-Claim Markdown fixture and:

- Fact A: 4 real reviewer batch calls
- Fact B: 4 real reviewer batch calls
- Total reviewer calls: 8
- Evidence network requests: 0
- Reconciliation entries: 19
- Runtime: approximately 282 seconds

Artifact:

`benchmarks/results-local/report-verification-v0.4-baseline-v1/live-artifact-real.json`

Reconciliation distribution:

- `single_reviewer_available`: 5
- `reviewer_disagreement`: 14

The command completed successfully with the required live-call and planned-call
confirmations.

## 7. Cost control

v0.4 retains the following constraints:

- no additional agents
- no per-Claim model calls
- batch reviewer execution
- explicit planned-call preflight
- Fact A/B calls remain independent
- no duplicate retrieval or EvidenceDecision execution
- offline evidence policy for this validation
- zero evidence network requests

For the baseline fixture, 19 Claims are processed in four batches per reviewer,
resulting in eight total reviewer calls.

## 8. Current limitations

- Markdown Claim Extraction is deterministic and does not guarantee that every
  meaningful statement in an arbitrary report becomes a Claim.
- Claim extraction is not fact verification.
- Evidence quality depends on the available offline evidence index.
- The validated workflow does not establish broad provider accuracy from one
  report run.
- Reconciliation disagreement still routes claims for review; it does not
  automatically establish correctness.
- The current artifact reports `actual_reviewer_calls=8`, but
  `coordinator_model_call_count=0` and `adapter_model_call_count=0`.
  Existing coordinator telemetry does not increment provider-backed reviewer
  counters, so these fields must not be interpreted as proof of zero provider
  calls.
- The real validation confirms execution and artifact generation, not factual
  correctness for all 19 Claims.
