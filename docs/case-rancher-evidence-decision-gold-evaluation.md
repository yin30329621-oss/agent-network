# Rancher EvidenceDecision Gold Evaluation Plan

## 1. Current limitation

The case currently has successful BM25 retrieval, multi-source evidence,
refined claims, and bundle replay. Nevertheless, the pipeline produces no
`verified_supported` result. This does not by itself prove that the evidence
is insufficient. It may indicate that the deterministic exact-text rule is
more conservative than the human evidence standard, that claims still contain
implicit inference, or that the selected excerpts do not form a sufficiently
direct citation bundle.

The evaluation must separate these possibilities before changing any rule.
No production status, Claim schema, retrieval behavior, or EvidenceDecision
Engine behavior is changed by this plan.

## 2. Human gold labels

Two reviewers independently label each sampled refined claim using only the
claim text and the cited local evidence chunks. Reviewers must not use model
output, search results, or uncited external knowledge. A third adjudicator
resolves disagreements and records the reason.

Each gold record should contain:

```json
{
  "claim_id": "refined-...",
  "gold_status": "supported|partial|insufficient",
  "supporting_chunk_ids": [],
  "source_types_used": [],
  "implicit_inference": false,
  "version_scope_clear": true,
  "rationale": "Short human-written rationale.",
  "reviewer_agreement": true
}
```

The rationale must identify the proposition actually supported and distinguish
direct wording from reasonable but unstated inference.

## 3. Gold status standards

### Supported

Use `supported` only when the cited chunks directly establish the complete
atomic claim, including material qualifiers such as actor, direction,
protocol, resource, and version scope. The reviewer must be able to point to
one chunk or a coherent bundle of chunks without adding an unstated premise.

Multiple sources are acceptable when they jointly establish separate parts of
the same atomic claim and their scope is consistent.

### Partial

Use `partial` when the evidence confirms only part of the claim, supports the
general mechanism but not a material qualifier, or requires a limited
inference. A claim that combines two facts should remain `partial` until it is
split or every part is directly evidenced.

### Insufficient

Use `insufficient` when no cited chunk directly addresses the proposition,
the sources are only tangentially related, the evidence conflicts without a
resolvable authoritative source, or the required version/scope cannot be
established.

An empty retrieval result is insufficient, but a non-empty BM25 result is not
automatically partial or supported.

## 4. Thirty-claim sampling strategy

Select 30 refined claims with a fixed, reproducible seed and publish the
selected IDs before labeling. Use stratified sampling rather than taking the
first 30 records:

- 10 `reverse_tunnel` claims;
- 10 `serviceaccount_token` claims;
- 10 `kubernetes_rbac` claims.

Within each type, sample across:

- single-source and multi-source bundles;
- claims that the Engine classified as `partially_supported`,
  `candidate_only`, and `insufficient_evidence`;
- short and long atomic statements;
- cases with and without `rancher_source` evidence.

If a stratum has fewer items than its allocation, record the shortage and
allocate the remainder to the next deterministic stratum. The sample should
include at least five cases with source-code evidence and at least five cases
where the bundle contains more than one source type.

## 5. Human versus Engine metrics

Compare the final adjudicated gold label with the Engine's mapped three-state
result and its raw status.

Required metrics:

- confusion matrix for `supported`, `partial`, and `insufficient`;
- supported recall: gold supported predicted supported;
- supported precision: predicted supported that is gold supported;
- partial recall and insufficient recall;
- false-negative rate for gold-supported claims;
- abstention rate: Engine results routed to manual review;
- exact-text miss rate among gold-supported claims;
- source-diversity agreement between human supporting chunks and bundle
  source types;
- inter-reviewer agreement, using Cohen's kappa or simple agreement with the
  adjudicated disagreement count.

The key diagnostic comparison is:

```text
gold supported + engine non-supported
```

If this group is large and its evidence contains direct wording, the rule may
be too strict. If the group depends on unstated joins, qualifiers, or version
assumptions, the Claim remains insufficiently atomic or the evidence bundle is
not adequate. If human labels are mostly partial or insufficient, the zero
verified result is likely an accurate conservative outcome.

## 6. Decision criteria

Do not change the Engine based on a single false negative. First inspect the
failure reasons by claim type and evidence source combination. A rule-change
proposal should require repeated evidence that:

1. reviewers agree on supported labels;
2. the supporting chunks are traceable and scope-consistent;
3. the support does not rely on implicit inference;
4. the same failure pattern appears across more than one claim type; and
5. the proposed change will not turn BM25 relevance into factual support.

Possible conclusions are:

- Engine rule is too strict: gold-supported claims repeatedly fail only the
  exact-text check despite direct, complete evidence.
- Claim refinement is incomplete: gold partial labels reveal bundled facts or
  hidden qualifiers.
- Evidence standard needs clarification: reviewers disagree about whether a
  multi-source bundle is sufficient or whether version scope is material.
- Current behavior is correct: gold labels confirm that retrieved evidence is
  related but not directly sufficient.

## 7. Constraints and auditability

The evaluation uses existing local artifacts only. It adds no model calls,
network requests, retrieval, or production code changes. Gold labels and
adjudication notes should be stored as a separate case artifact, preserving
the original decisions for before/after comparison.
