# Rancher Security Review Live Validation

This case is intended for Agent Network v0.4 Real Live Validation. It starts from the original Rancher security report and is kept separate from the development case.

## Difference from the development case

- The input is copied from the original report.
- Claims and verification outputs must be generated in this case directory.
- Historical claims, canonical claims, decisions, reports, and revision suggestions are not reused.
- The fixed evidence library may be reused as an evidence source, but generated artifacts are new.

## Intended workflow

1. Claim Extraction
2. Evidence Retrieval
3. Fact Agent A/B independent verification
4. Security Agent Review
5. Logic Agent Review
6. Merge Agent aggregation
7. Final Review Report

The run must record model calls, evidence network requests, runtime, provider/model metadata, and failure slots.
