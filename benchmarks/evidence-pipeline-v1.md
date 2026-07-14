# Evidence Pipeline Benchmark v1

This benchmark uses only synthetic `FIXTURE ONLY` catalog records with `.invalid` URLs. It measures catalog candidate selection, deterministic matcher/verifier status handling, product/component isolation, version mismatch handling, and deterministic reporting. It does not measure real official-document retrieval quality.

Metrics are deterministic: Top-1, Recall@3, and Precision@3 are averaged over cases with expected documents; forbidden-hit rate is the fraction of all cases returning a forbidden document; isolation, version, not-found, and status accuracy use exact case expectations.
