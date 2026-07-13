# Agent Network v0.3.0 Release Candidate

## Summary

v0.3.0 is the foundation release for technical fact verification grounded in
official evidence. It retains the existing Multi-LLM Technical Report Reviewer
and adds an opt-in, deterministic evidence pipeline for Fact Agent context.

## What Changed Since v0.2.0

- Added an official document catalog and deterministic catalog repository.
- Added HTTPS-only official document fetching, HTML cleaning, chunking, and
  offline BM25 retrieval.
- Added synchronized local document cache and cached multi-document retrieval.
- Added optional Fact Evidence grounding through `fixture` and `local_cache`
  providers, plus programmatic citation validation.
- Added `evidence_relation` and `evidence_limitations` for explicit evidence
  boundaries.
- Added offline Evidence OFF / ON acceptance suites and an opt-in live A/B
  harness with confirmation, timeout, and output-safety gates.

## Evidence Pipeline

`Catalog -> Repository -> Fetcher -> Cleaner -> Chunker -> BM25 -> Retriever`
supports controlled official-document processing. The synchronizer persists raw
HTML, cleaned documents, and metadata in a local cache. The `local_cache`
provider reads that cache offline, applies the existing quality filters, and
injects only selected evidence chunks into the Fact Agent prompt.

Evidence is external data, not instructions. Fact citations are accepted only
when their chunk ID, document ID, and canonical URL belong to the evidence
provided for that request.

## Workflow Compatibility

The standard workflow remains Fact, Security, Logic, and Merge. A normal full
review with valid specialist findings makes four business model calls. Evidence
grounding does not add agents or model calls. Evidence is disabled by default;
the default provider remains `fixture` when evidence is explicitly enabled.
`local_cache` is forced offline and never falls back to document fetching.

## Verification Baseline

Normal unit tests use fixtures, stubs, mock transports, and stub LLMs. Their
real-network request count and real-model-call count are both zero. Controlled
live A/B evaluation is not part of ordinary test execution: it requires explicit
model selection and multiple call-count confirmations. See
[baseline-v0.3.md](baseline-v0.3.md) and [runbook-v0.3.md](runbook-v0.3.md).

## Upgrade Notes

- Upgrade package and CLI version metadata to `0.3.0`.
- Existing review commands remain compatible. Evidence must be enabled explicitly
  in configuration before Fact grounding is used.
- Local-cache evidence requires a pre-existing controlled cache; it does not
  synchronize or access the network during review.
- Existing v0.2 output and review workflows are unchanged when evidence is off.

## Known Limitations

- This is not a production search engine and does not index all Rancher,
  Kubernetes, or SUSE documentation.
- It has no vector retrieval, automatic claim extraction, query rewriting, or
  LLM reranking.
- A BM25 match is not itself proof that a claim is supported.
- When a model provides only natural-language verdict text, verdict accuracy
  cannot be automatically scored; human review remains required.
- Live-model and real-network validation require explicit operator opt-in.

## Release Decision

v0.3.0 is suitable for release-candidate review once the documented local test
baseline passes. Production use should treat evidence retrieval as an auditable
assistive capability, not an autonomous source of final security conclusions.

## Next Direction

v0.4 should prioritize broader, controlled official sources and evidence quality
evaluation before expanding Agent responsibilities or adopting semantic search.
