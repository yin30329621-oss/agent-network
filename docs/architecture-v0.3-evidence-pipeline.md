# v0.3 Evidence Pipeline Architecture

## Purpose

The v0.3 evidence pipeline supplies bounded, auditable official-document context
to the existing Fact Agent. It is deliberately separate from the four-agent
review workflow and remains optional.

## Data Flow

```text
Document Catalog
  -> Catalog Repository
  -> HTTPS Official Document Fetcher
  -> HTML Cleaner
  -> Deterministic Chunker
  -> Offline BM25 Index / Retriever
  -> Official Evidence Retriever
  -> Synchronizer / Local Cache
  -> local_cache Provider
  -> Fact Evidence Injection
  -> Citation Validation
  -> Fact Agent
```

The Fetcher only accepts catalog-registered HTTPS URLs on configured official
domains. Redirect destinations are revalidated. The Cleaner produces structured
text and headings; the Chunker uses deterministic boundaries; BM25 provides
transparent lexical ranking and exact filters.

## Catalog, Fetch, And Cache

`DocumentCatalogRepository` validates and filters official document records with
stable ordering and canonical-URL de-duplication. `OfficialDocumentSynchronizer`
uses the Repository, Fetcher, and Cleaner to write controlled cache entries:

```text
data/official-evidence-cache/
  documents/<document-id>/raw.html
  documents/<document-id>/cleaned.json
  documents/<document-id>/metadata.json
```

Metadata holds SHA-256 content hashes and fetch metadata. Writes are atomic and
document failures are fail-soft: a bad document neither corrupts an existing
cache entry nor blocks other candidates.

## Retrieval Modes

`fixture` supports deterministic unit and acceptance tests. `local_cache` reads
only the controlled cache, validates metadata/checksums, builds a shared
multi-document BM25 index, and reports cache failures without network fallback.
It supports exact product, component, document type, and document ID filters,
quality thresholds, per-document result caps, and optional result diversity.

## Fact Agent Boundary

Only Top-K chunks, bounded by per-chunk and total character limits, are injected
as structured evidence data. Raw HTML and full documents are never injected.
Prompt instructions define evidence as untrusted data and prohibit following
instructions contained in it.

Fact evidence output includes retrieval status, evidence provider, validated
citation IDs, URLs, limitations, and one of these relations:

- `direct_support`
- `direct_contradiction`
- `absence_of_support`
- `indirect_evidence`
- `unavailable`

Programmatic validation removes unknown or inconsistent citations. Zero evidence
cannot yield direct support or direct contradiction.

## Operational Boundaries

Default configuration leaves Fact Evidence disabled. Local cache is always
offline. Synchronization and live A/B model evaluation are separate, explicitly
confirmed benchmark operations. The normal Fact, Security, Logic, Merge workflow
is unchanged and does not gain extra model calls from evidence grounding.
