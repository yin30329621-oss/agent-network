# v0.4 Design: Markdown Report to Claim Extraction

**Status:** Design only  
**Scope:** v0.4 Milestone 1  
**Baseline:** Agent Network v0.3.1  
**Current release checkpoint:** e56b25c

## 1. v0.3.1 current architecture

The current system has two connected but distinct review paths.

### Standard report review

Fact -> Security -> Logic -> Merge

The four-agent workflow remains unchanged. Markdown reports are read by the existing review entry point and passed to the workflow as ReviewRequest.markdown.

### Evidence verification path

Markdown report
  -> Claim extraction
  -> ClaimRegistry
  -> Evidence retrieval
  -> Claim Verification Engine
  -> bounded Fact context

The v0.3.1 evidence path uses official-document metadata, local cached evidence, bounded evidence injection, and deterministic local reconciliation for Dual Fact results.

Existing relevant modules:

- src/agent_network/claim/claim.py: canonical Claim model
- src/agent_network/claim/segmentation.py: Markdown structural segmentation
- src/agent_network/claim/normalization.py: text normalization and stable Claim IDs
- src/agent_network/claim/extractor.py: deterministic Markdown Claim extraction
- src/agent_network/claim/registry.py: validated Claim storage and deduplication
- src/agent_network/claim/query.py: Claim-to-evidence query mapping
- src/agent_network/claim/engine.py: local cached evidence verification
- src/agent_network/claim/fact_integration.py: bounded Fact context construction
- src/agent_network/workflow/review.py: existing workflow integration

The repository already contains most of the extraction implementation. v0.4 M1 should expose and stabilize it rather than introduce a second Report Parser abstraction.

## 2. v0.4 M1 goal

Provide a stable, deterministic Markdown report entry point:

agent-network extract-claims report.md

The command should:

- read a Markdown report as UTF-8;
- extract candidate factual Claims using existing deterministic rules;
- preserve source locations and heading context;
- deduplicate Claims;
- validate every Claim against the canonical Claim model;
- output a machine-readable extraction result;
- perform zero model calls and zero network calls.

M1 is an extraction and contract milestone. It does not change the four-agent workflow or automatically add Dual Fact calls to ordinary reviews.

## 3. Markdown to ClaimRegistry data flow

The proposed flow is:

Markdown path
  -> UTF-8 document text
  -> ClaimExtractionRequest
  -> segment_markdown
  -> candidate filtering and normalization
  -> Claim construction and validation
  -> ClaimRegistry
  -> ClaimExtractionResult
  -> optional JSON output

Detailed stages:

1. The CLI validates that the input path exists and is readable.
2. The file is read as UTF-8 and passed with a stable source_name.
3. segmentation.py identifies headings, paragraphs, list items, table rows, and blockquotes while ignoring fenced code.
4. extractor.py filters URLs, commands, navigation text, quotes, and non-statement candidates.
5. normalization.py cleans Markdown wrappers, creates normalized text, and derives a stable claim_id.
6. Claim is validated and enriched with source_file, source_location, heading_path, line range, type, and extraction metadata.
7. ClaimRegistry rejects duplicate IDs and preserves stable insertion order.
8. ClaimExtractionResult records Claims, failures, candidate count, and duplicate count.

The extractor must not invent facts, citations, URLs, or evidence. It only converts report text into auditable Claim candidates.

## 4. Canonical Claim contract

The canonical contract is Claim in src/agent_network/claim/claim.py.

Required identity fields:

- claim_id
- text

Recommended provenance fields:

- normalized_text
- source_file
- source_location
- section
- heading_path
- line_start
- line_end

Verification routing fields:

- product
- component
- claim_type
- priority
- requires_external_evidence

Extraction audit fields:

- extraction_confidence
- extraction_method
- status

The v0.4 path must continue using this model. It must not create a parallel report-specific Claim class or extend the legacy Claim model in evidence/schemas.py.

Claim IDs are derived from source_name, heading path, and normalized text. The CLI and benchmark must use a stable source_name if reproducible IDs are required.

## 5. CLI design

Proposed command:

agent-network extract-claims report.md

Recommended options:

- --output, -o: output JSON path; stdout when omitted
- --source-name: stable source identity; defaults to input filename
- --product: default product metadata
- --component: default component metadata
- --min-chars: minimum candidate length
- --max-chars: maximum candidate length
- --include-headings
- --exclude-list-items
- --exclude-table-rows
- --format: json or markdown summary

M1 should expose only deterministic extraction options. It should not accept model provider, retry, or network options.

The existing review command remains unchanged. Claim verification remains opt-in through the existing claim_verification configuration and should not become an implicit side effect of extract-claims.

## 6. Claim Extraction output format

The primary output should reuse ClaimExtractionResult.to_dict():

{
  "claims": [
    {
      "claim_id": "claim-...",
      "text": "...",
      "normalized_text": "...",
      "source_file": "report.md",
      "source_location": "report.md#architecture:paragraph-1:L3-L3",
      "heading_path": ["Architecture"],
      "line_start": 3,
      "line_end": 3,
      "claim_type": "architecture",
      "extraction_confidence": 0.9,
      "extraction_method": "deterministic",
      "status": "pending"
    }
  ],
  "failures": [],
  "candidate_count": 10,
  "duplicate_count": 1
}

The exact serialized fields should follow Claim.to_dict() and ClaimExtractionResult.to_dict(). A new schema is not required for M1.

The output must distinguish:

- candidate_count: structural candidates seen;
- claims: validated, deduplicated Claims;
- duplicate_count: candidates removed as duplicates;
- failures: candidates rejected with safe code, message, and source location.

## 7. Existing Verification Pipeline integration

The first integration path is already present in ReviewWorkflow:

ReviewRequest.markdown
  -> DeterministicClaimExtractor
  -> ClaimRegistry
  -> ClaimVerificationBatchRequest
  -> ClaimVerificationEngine
  -> local official evidence cache
  -> build_claim_verification_fact_context
  -> Fact Agent

M1 should reuse this path without changing its contracts.

Integration requirements:

- ClaimRegistry is the boundary between extraction and verification.
- ClaimVerificationEngine receives Claim objects through ClaimVerificationBatchRequest.
- Evidence queries are derived by query_for_claim().
- Evidence remains bounded and citation-safe.
- Local cache mode remains offline-only.
- claim_verification.enabled remains false by default.
- max_claims truncation must be explicit in output or diagnostics.

A report with more Claims than max_claims must not be presented as fully verified. The system should expose candidate count, extracted count, selected count, and truncated count.

The existing benchmark fixture format remains compatible. Benchmark adapters may convert fixture claims into Claim-compatible objects, but existing benchmark files should not be rewritten in M1.

## 8. Dual Fact adapter follow-up design

The current Claim Verification Engine and Dual Fact Coordinator use different input contracts.

Claim Verification Engine produces VerificationResult and bounded Fact context. Dual Fact requires FactReviewInput objects generated from:

- Claim;
- selected Evidence;
- EvidenceDecisionEngine output;
- retrieval metadata.

The future adapter should therefore be:

ClaimRegistry
  -> offline retrieval
  -> EvidenceDecisionEngine.decide_batch
  -> FactReviewInput list
  -> DualFactReviewCoordinator
  -> FactReconciliation list

The adapter must:

- run locally;
- keep Fact A and Fact B inputs identical;
- prevent either reviewer from seeing the other output;
- preserve valid chunk_id citation checks;
- retain batch planning and budget estimation;
- add zero per-Claim calls;
- add no network calls when using local evidence.

This adapter is deliberately separate from the M1 extraction command. It should be introduced only after the Claim-to-Evidence contract is tested independently.

## 9. Modules not modified in M1

M1 should not modify:

- src/agent_network/claim/claim.py
- src/agent_network/claim/engine.py
- src/agent_network/claim/fact_review.py
- src/agent_network/claim/fact_model_adapter.py
- src/agent_network/evidence/
- src/agent_network/workflow/review.py, except for a narrowly scoped public entry refactor if required
- the four-agent workflow
- Fact A/B prompts or provider configuration
- existing Dual Fact benchmark batch size or call plan
- existing benchmark fixture contracts
- tests unrelated to extraction or CLI

No new agent, LLM prompt, retry policy, provider, or network source is part of M1.

## 10. Acceptance criteria

### Functional

- A Markdown file can be parsed through extract-claims.
- Valid paragraph, list, table, and optional heading Claims are emitted.
- Code fences, URLs, commands, and excluded quotes do not become Claims.
- Duplicate Claims are removed deterministically.
- Every output Claim validates against the canonical Claim model.
- Source file, heading path, and line ranges are retained.
- Extraction failures are structured and non-secret.

### Pipeline compatibility

- The output can be loaded into ClaimRegistry.
- Claims can be passed to ClaimVerificationBatchRequest without conversion to a second Claim schema.
- Existing local-cache Claim Verification continues to work.
- Existing four-agent review behavior remains unchanged when claim verification is disabled.
- Existing Dual Fact benchmark inputs and call counts remain unchanged.

### Cost and safety

- extract-claims performs zero model calls.
- extract-claims performs zero network calls.
- No raw model response, secret, or generated URL is persisted.
- Extraction does not claim that a Claim is true; it only marks it as a candidate.
- Long reports expose truncation or selection limits.

### Validation

- Unit tests cover Markdown segment types, filtering, normalization, duplicate handling, and stable IDs.
- CLI tests cover input errors, JSON output, and deterministic repeatability.
- An extraction fixture benchmark records candidate count, extracted count, duplicate count, failure count, and runtime.
- pytest and Ruff pass.
- The pre-existing v0.3.1 benchmark and live-validation artifacts remain reproducible without modification.

## Recommended M1 implementation boundary

Implement only:

1. a public extract-claims CLI entry point;
2. JSON/summary output around the existing ClaimExtractionResult;
3. extraction fixture and benchmark;
4. focused CLI and extraction regression tests.

Do not implement the Dual Fact adapter in the same change. First stabilize Markdown to canonical ClaimRegistry; then add the separate ClaimRegistry to FactReviewInput adapter as the next v0.4 milestone.
