# Known Limitations: v0.3.0

## Evidence Coverage

The official-document catalog is curated and intentionally small. v0.3 does not
claim complete Rancher, Kubernetes, SUSE, or CVE coverage. A missing document or
BM25 result means only that the configured sources did not supply usable evidence.
It does not establish that a claim is false.

## Retrieval And Verification

Retrieval is deterministic lexical BM25, not semantic or vector search. It has no
embedding index, automatic claim extraction, query rewrite, LLM rerank, evidence
fusion, or automatic web search. BM25 relevance is not proof of factual support;
the Fact Agent and a human reviewer must preserve evidence boundaries.

## Fact Judgement

Evidence relations distinguish direct support, direct contradiction, absence of
support, indirect evidence, and unavailable evidence. They do not replace human
technical or security judgement. A provider/model may return natural-language
verdict prose without a stable verdict enum. In that case live A/B verdict
accuracy is intentionally unavailable rather than inferred by keyword matching.

## Network And Cache Operations

The Fetcher accepts configured official HTTPS domains only. Synchronization is a
manual, opt-in operation; no automatic crawl, scheduled refresh, conditional HTTP
revalidation, or cache repair is implemented. `local_cache` is forced offline;
missing or invalid cache data degrades evidence availability rather than fetching.

## Workflow

Evidence grounding currently applies only to Fact. Security, Logic, and Merge do
not consume official evidence in v0.3. The existing workflow may skip Merge when
no specialist findings are usable; this is a failure-safe execution outcome, not
an evidence-driven extra model call.

## Evaluation

Fixture and local-cache acceptance suites are deterministic but are not a
large-scale accuracy study. Live A/B evaluation is manually gated, uses a small
case set, and requires explicit cost, model, timeout, and output confirmations.
