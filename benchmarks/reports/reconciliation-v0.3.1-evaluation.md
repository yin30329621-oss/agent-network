# Reconciliation v0.3.1 Evaluation Report

**Scope:** Rancher Report Dual Fact Benchmark v1 reconciliation behavior  
**Baseline:** v0.3 checkpoint 1217d65  
**Enhancement:** v0.3.1 checkpoint f989675  
**Evaluation mode:** Existing artifacts and deterministic tests only; no live benchmark was rerun.

## 1. Previous v0.3 behavior

The v0.3 reconciliation layer ran after independent Fact A and Fact B batch reviews. It preserved both reviewer results and selected one top-level status using:

- citation validation against supplied chunk_id values;
- reviewer availability;
- exact string equality of recommended_status;
- comparison with the deterministic EvidenceDecisionEngine status.

The existing Rancher live artifact contains 19 claims in four batches [5, 5, 5, 4]. Its recorded reconciliation distribution is:

| v0.3 status | Claims |
| --- | ---: |
| consensus | 1 |
| reviewer_disagreement | 13 |
| single_reviewer_available | 5 |
| invalid_citation | 0 |
| manual_review_required | 0 |
| **Total** | **19** |

In v0.3, disagreement was represented as a status, but it did not carry structured routing metadata indicating whether or why a human should review it.

## 2. v0.3.1 changes

The v0.3.1 enhancement keeps the Dual Fact architecture unchanged:

- Fact A and Fact B still receive identical independent inputs.
- Reconciliation remains local and deterministic.
- No additional agents, model calls, retries, or network calls were added.

The changes are:

1. **Canonical status normalization**

   Reviewer strings such as active and verified_candidate normalize to supported. Similar aliases are grouped into partially_supported, unsupported, insufficient_evidence, or manual_review. Original reviewer fields remain unchanged; the normalized value is added for comparison and serialization.

2. **Evidence gating**

   A reviewer cannot automatically upgrade an EvidenceDecisionEngine result that is unsupported, insufficient_evidence, manual_review_required, or partially_supported when the reviewer claims a stronger result. Such cases become manual_review_required with an evidence-gating reason.

3. **Structured manual review routing**

   Each reconciliation can now expose:

   - needs_manual_review
   - manual_review_reasons
   - review_priority

4. **Compatibility serialization**

   FactReconciliation.to_dict() includes the new fields, while from_dict() defaults them for legacy JSON that does not contain them. The benchmark live serializer now uses this additive representation.

## 3. Status distribution comparison

No new live 19-claim run was performed, so a post-change 19-claim distribution is intentionally not asserted.

The available behavioral comparison is:

| Scenario | v0.3 behavior | v0.3.1 behavior |
| --- | --- | --- |
| Equivalent reviewer labels, e.g. active vs verified_candidate | False disagreement possible | Compared as canonical supported; can reach consensus |
| Genuine reviewer disagreement | reviewer_disagreement | Same status, plus manual-review metadata |
| Invalid citation | invalid_citation | Same status, escalated to high-priority manual review |
| One reviewer unavailable | single_reviewer_available | Same status, escalated to high-priority manual review |
| Both reviewers unavailable | manual_review_required | Same status, explicit unavailable-reviewer reason |
| Evidence engine says insufficient evidence, reviewers claim support | Could be consensus or engine challenge depending on exact strings | Blocked as manual_review_required |
| Legacy JSON without new fields | Existing fields only | Loads with safe default metadata |

The v0.3 artifact therefore remains the historical baseline, while v0.3.1 improves classification and routing semantics without changing the benchmark input or call plan.

## 4. Manual review routing changes

v0.3.1 makes manual review an explicit decision separate from the top-level reconciliation status.

| Trigger | needs_manual_review | Priority | Reason |
| --- | --- | --- | --- |
| Invalid citation | true | High | invalid_citation |
| Both reviewers unavailable | true | High | both_reviewers_unavailable |
| Only one reviewer available | true | High | single_reviewer_available |
| Reviewer status disagreement | true | Normal | reviewer_status_disagreement |
| Reviewer attempts unsupported evidence upgrade | true | High | evidence_gate_blocked_upgrade |
| Valid consensus | false | Normal | No manual-review reason |

This preserves existing status values for downstream compatibility while making review queues actionable.

## 5. Evidence gating examples

### Insufficient evidence

Given an EvidenceDecisionEngine status of insufficient_evidence, if both reviewers return verified_candidate or active, v0.3.1 produces:

    {
      "status": "manual_review_required",
      "needs_manual_review": true,
      "manual_review_reasons": ["evidence_gate_blocked_upgrade"],
      "review_priority": "high"
    }

The reviewer explanations and citations remain available, but the local engine prevents automatic acceptance.

### Invalid citation

If a reviewer cites a chunk outside the supplied evidence set, the existing citation rejection remains in force. v0.3.1 additionally routes the result explicitly:

    {
      "status": "invalid_citation",
      "needs_manual_review": true,
      "manual_review_reasons": ["invalid_citation"],
      "review_priority": "high"
    }

No model-generated URL or unknown chunk_id is accepted.

### Equivalent status labels

If Fact A returns active and Fact B returns verified_candidate, both normalize to supported. This removes a string-label-only disagreement while preserving both original reviewer outputs.

## 6. Model and network call cost comparison

| Metric | v0.3 | v0.3.1 |
| --- | ---: | ---: |
| Claims | 19 | 19 |
| Batches | 4 | 4 |
| Fact A model calls | 4 | 4 |
| Fact B model calls | 4 | 4 |
| Total model calls | 8 | 8 |
| Evidence/retrieval network calls | 0 | 0 |
| Per-claim model calls | 0 | 0 |
| Additional reconciliation model calls | 0 | 0 |
| Additional retries | 0 | 0 |

The v0.3.1 changes are deterministic local post-processing only. The existing live artifact records 8 explicitly confirmed provider calls and 0 evidence/retrieval network calls; those costs remain unchanged.

## 7. Conclusion

v0.3.1 preserves the stable v0.3 Dual Fact execution model and benchmark cost profile. Its main improvement is decision quality at the reconciliation boundary:

- equivalent reviewer labels no longer create avoidable disagreements;
- insufficient evidence prevents unsupported automatic upgrades;
- invalid citations and reviewer failures become explicit review-queue entries;
- legacy result JSON remains readable;
- Fact A/B isolation, batching, workflow, and call count remain unchanged.

The existing v0.3 live distribution should continue to be used as the historical comparison point. A future live rerun may measure the exact post-change 19-claim distribution, but it is not required to validate the deterministic behavior and was intentionally not performed for this report.
