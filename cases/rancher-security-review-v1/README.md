# Rancher Security Review Case

## 1. Case background

This case reviews a Rancher security technology report. The objective is to
check whether technical descriptions are consistent with authoritative Rancher
documentation, Rancher source code, and Kubernetes official documentation.

The report itself is treated as the claim source, not as evidence.

## 2. Workflow

```text
Report
  ↓
Claim Extraction
  ↓
Canonical Claim
  ↓
Evidence Retrieval
  ↓
Evidence Decision
  ↓
Revision Suggestions
```

## 3. Evidence sources

The evidence library currently includes:

- Rancher Official Documentation
- Rancher Source Code
- Kubernetes Official Documentation

Evidence chunks retain source type, source path, canonical URL, and stable
chunk IDs for traceability.

## 4. Key statistics

| Metric | Result |
|---|---:|
| Extracted claims | 149 |
| Canonical claims | 53 |
| Evidence chunks | 6,420 |
| Retrieval coverage | 53/53 claims |
| Revision suggestions | 53 claims; 25 broad-claim candidates |

The current EvidenceDecision v2 result is conservative: no claim reached
`verified_supported`; all canonical claims remain subject to review.

## 5. Output files

- `output/claims.json` — extracted claim records
- `output/canonical-claims.json` — canonicalized claim set
- `output/evidence-decisions-v2.json` — deterministic evidence decisions
- `output/final-review-report.md` — final technical review report
- `output/revision-suggestions.md` — claim revision recommendations

Additional retrieval, refinement, bundle, and analysis artifacts are retained
under `output/` for audit and reproducibility.

## 6. Current limitations

- EvidenceDecision is intentionally conservative and does not treat retrieval
  relevance as factual support.
- Some security semantics, scope, version applicability, and implicit
  inference require human confirmation.
- This case does not replace a formal security audit, penetration test, or
  product security assessment.

