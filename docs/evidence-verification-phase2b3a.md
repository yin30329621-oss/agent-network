# Phase 2B-3A: Official Document Fetch, Clean and Chunk

`HttpOfficialDocumentFetcher.fetch(DocumentCatalog)` is catalog-bound. It accepts only HTTPS URLs whose exact host is in the configured official-domain allowlist. It rejects credentials, localhost, IP hosts, unsafe schemes, unsafe redirects, non-HTML responses, oversize bodies, and excessive redirects. `FetchAudit` records only safe request metadata; it never stores request credentials or headers.

`OfficialDocumentCleaner` deterministically selects `main`, `article`, `role=main`, then `body`. It removes scripts, styles, navigation, headers, footers, sidebars, forms, embedded content, comments, and explicit table-of-contents blocks. It retains headings, paragraphs, lists, table rows, code blocks, link text, and normalized plain text. Page text remains untrusted: local prompt-injection patterns are flagged with deterministic positions, never executed or treated as instructions.

`OfficialDocumentChunker` preserves section boundaries first, then paragraph, list, table, code, sentence, and character boundaries. Chunk IDs and SHA-256 hashes are deterministic. Chunks carry catalog product/version metadata, heading paths, offsets, code/table flags, and inherited prompt-injection flags. Oversized code-bearing sections are retained with an explicit warning when within the separate code-block limit.

This phase has no retrieval, BM25, embedding, CLI, model, or real-network behavior. Phase 2B-3B can add local BM25 retrieval over these deterministic chunks.
