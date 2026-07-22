# Claim Ranking v0.5.1 Evaluation — Rancher Case

## 1. Scope

This offline evaluation compares the v0.5.0 Claim Ranking MVP with the v0.5.1
first enhancement phase. Both versions are evaluated against the same 149
candidate Claims and the same manually selected 30-Claim benchmark.

Inputs:

- Candidate Claims: `cases/rancher-security-review-v1/output/claims.json`
- Manual benchmark Claims: `cases/rancher-security-review-live-v1/output/claims.json`
- Ranking implementation: `src/agent_network/claim/ranking.py`

The evaluation does not call a model, access the network, or execute the
Verification pipeline. Ranking remains sidecar metadata and does not modify
Claim schema or downstream Fact/Security/Logic/Merge contracts.

## 2. v0.5.1 changes

Only three deterministic enhancements were added:

- Claim type weighting;
- Section salience weighting from `section`, `heading_path`, and
  `source_location`;
- Refined security-sensitive and architecture-core signals.

The existing base priority and external-evidence factors remain unchanged.
Ties still use stable ascending `claim_id` ordering after all score factors
are applied.

## 3. Recall and precision comparison

| Metric | v0.5.0 | v0.5.1 | Change |
|---|---:|---:|---:|
| Recall@10 | 6.7% (2/30) | 23.3% (7/30) | +16.6 pp |
| Precision@10 | 20.0% (2/10) | 70.0% (7/10) | +50.0 pp |
| Recall@30 | 30.0% (9/30) | 60.0% (18/30) | +30.0 pp |
| Precision@30 | 30.0% (9/30) | 60.0% (18/30) | +30.0 pp |
| Recall@50 | 43.3% (13/30) | 76.7% (23/30) | +33.4 pp |
| Precision@50 | 26.0% (13/50) | 46.0% (23/50) | +20.0 pp |

The benchmark set is fully contained in the 149 candidate Claims, so overlap is
computed by exact `claim_id` matching.

## 4. High-value Claim coverage

Under the refined predicates, the candidate population contains:

- 96 security-sensitive Claims;
- 32 architecture-core Claims;
- 123 Claims in the security/architecture union.

| Ranked set | Security-sensitive | Architecture-core | High-value union |
|---:|---:|---:|---:|
| Top 10 | 9 | 3 | 10 |
| Top 30 | 21 | 11 | 30 |
| Top 50 | 39 | 13 | 50 |

The high-value union is a routing category, not a factual accuracy label. The
increase from the v0.5.0 counts reflects refined signal detection and should
not be interpreted as newly discovered security facts.

## 5. Tie-rate comparison

The primary tie metric is:

```text
score-value tie rate = 1 - unique score values / candidate count
```

| Metric | v0.5.0 | v0.5.1 |
|---|---:|---:|
| Unique score values | 3 | 23 |
| Score-value tie rate | 98.0% | 84.6% |
| Largest same-score group | 113 Claims | 19 Claims |

The tie rate remains material, but the largest tie group is substantially
smaller and Top-K no longer depends primarily on the original three broad
score buckets.

## 6. Low-value filtering regression

The previous low-value proxy is retained: a Claim is low value when it is
neither security-sensitive nor architecture-core.

| Set | v0.5.0 | v0.5.1 |
|---|---:|---:|
| Candidate low-value population | 31/149 (20.8%) | 26/149 (17.4%) |
| Top 10 low-value rate | 0.0% | 0.0% |
| Top 30 low-value rate | 0.0% | 0.0% |
| Top 50 low-value rate | 0.0% | 0.0% |

The first-phase enhancement preserves the MVP's low-value filtering behavior.
The lower full-population count is caused by refined security signal matching,
not by modifying any Claim record.

## 7. Assessment

v0.5.1 materially improves recovery of the fixed manual benchmark:

- Recall@10 rises from 6.7% to 23.3%;
- Recall@30 rises from 30.0% to 60.0%;
- Recall@50 rises from 43.3% to 76.7%;
- score-value tie rate falls from 98.0% to 84.6%.

This is a meaningful Ranking enhancement, but not a human-priority replacement.
The candidate dataset still has `priority=medium` for all 149 Claims, so a
residual tie problem remains. Section salience is also case-informed and must
be versioned if reused for other reports.

## 8. Conclusion

Recommended status: **v0.5.1 first-phase ranking enhancement accepted for
offline evaluation and controlled pre-filter use**.

The next phase should evaluate cross-case generalization and add further
sidecar-only signals only with a fixed benchmark and explicit ablation
measurements. No Claim schema change or additional model call is justified by
this result.

