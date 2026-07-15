# Agent Network v0.3 Baseline

**Baseline date:** 2026-07-15
**Scope:** v0.2/v0.3 evidence verification milestone
**Repository:** `/home/yin/agent-network`

## 1. Development environment

- WSL Ubuntu
- Python 3.12.3
- `uv` 0.11.28 for environment and dependency management
- Test and lint commands:
  - `uv run pytest`
  - `uv run ruff check .`
- GitHub remote uses SSH.
- API credentials are loaded from local environment variables or `.env`; secrets are not recorded in this baseline.

## 2. Architecture and workflow

The standard review workflow remains unchanged:

```text
Fact -> Security -> Logic -> Merge
```

- Fact reviews factual claims, evidence needs, citations, and technical accuracy.
- Security reviews cloud-native security risks and unsafe defaults.
- Logic reviews assumptions, contradictions, reasoning flow, and conclusion strength.
- Merge deduplicates and synthesizes completed specialist results.

Evidence verification is an optional Fact-stage capability. It does not add agents,
change the four-agent workflow, or add model calls to ordinary reviews.

## 3. Dual Fact verification design

Dual Fact is an independent fact-verification module, separate from the standard
four-agent workflow.

- Fact A and Fact B run independently.
- Both receive the same Claim, selected Evidence, and Verification Engine input.
- Neither reviewer sees the other reviewers output.
- Reconciliation is performed locally after both results are available.
- Calls are batch-oriented rather than one model call per claim.
- The current Rancher benchmark uses 19 claims in four batches: 5, 5, 5, and 4.
- The stable live checkpoint completed 8 model calls: 4 Fact A and 4 Fact B.
- Citations are accepted only when their `chunk_id` belongs to the supplied evidence.

## 4. Evidence verification pipeline

```text
Document Catalog
  -> Fetcher
  -> Cleaner
  -> Deterministic Chunker
  -> Offline BM25 Retriever
  -> Evidence Injection
  -> Fact verification
```

- **Document Catalog:** validates official document records, domains, versions,
  canonical URLs, and stable ordering.
- **Fetcher:** accepts catalog-registered HTTPS official domains, revalidates
  redirects, applies size/redirect/time limits, and records safe fetch metadata.
- **Cleaner:** selects the main document content, removes navigation and irrelevant
  HTML, preserves headings, paragraphs, lists, tables, code, and link text, and
  flags prompt-injection patterns as untrusted data.
- **Chunker:** creates deterministic section-aware chunks with stable chunk IDs,
  hashes, document/version metadata, heading paths, and offsets.
- **BM25 Retriever:** performs deterministic lexical retrieval with product,
  component, version, quality, Top-K, excerpt-size, and total-evidence bounds.
- **Evidence Injection:** passes only selected bounded chunks and validated metadata
  to Fact. Raw HTML and full documents are never injected. Unknown citations are
  rejected programmatically.

The `local_cache` provider is offline-only. Evidence is disabled by default and
must be explicitly enabled.

## 5. Benchmark verification results

Stable Dual Fact live checkpoint:

- Benchmark: Rancher Report Dual Fact v1
- Claims: 19
- Batches: 4 (`[5, 5, 5, 4]`)
- Model calls: 8 total
  - Fact A: 4
  - Fact B: 4
- Evidence/retrieval network calls: 0
- Fact A results: 19/19 parsed
- Fact B results: 19/19 parsed
- Reconciliation: completed without unresolved parse failures
- `uv run pytest`: 356 passed
- `uv run ruff check .`: passed

The zero network count refers to the offline fixture/evidence path; the eight
provider model calls are the explicitly confirmed live requests.

## 6. Git checkpoint

- Commit: `1217d65`
- Message: `feat: stabilize dual fact benchmark verification pipeline`
- Branch: `main`
- Remote: GitHub over SSH

This document is a concise engineering baseline. It does not contain API keys,
raw model responses, private reports, or local evidence-cache contents.
