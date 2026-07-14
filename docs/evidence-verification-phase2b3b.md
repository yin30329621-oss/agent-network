# Phase 2B-3B: Offline BM25 Retrieval

This phase builds a deterministic in-memory BM25 index over `DocumentChunk`. The query builder normalizes claim terms and controlled product/component aliases, while product and component filters run before selection. A requested version prefers matching chunks; a non-matching fallback is explicitly marked and is never direct support.

Selection is bounded by Top-K, per-evidence excerpt size, total evidence characters, and a minimum relevance score. Batch retrieval deduplicates claims and reports zero network/model calls. The local budget estimator groups only claims with selected evidence and reports a hard budget-exceeded flag rather than silently increasing future Fact calls.

`benchmarks/fixtures/retrieval-v1` is an offline, fixture-only regression benchmark. It measures ranking, isolation, version handling, no-match behavior, and budget compliance. This is not a real-document accuracy claim. Phase 2C may validate the same interfaces against a controlled official-document cache.
