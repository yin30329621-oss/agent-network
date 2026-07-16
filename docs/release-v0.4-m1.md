# Agent Network v0.4 M1 Release Summary

**Release:** v0.4 Milestone 1  
**Feature checkpoint:** 8aa2f8b  
**Scope:** Markdown Report to Claim Extraction

## 1. Background and goal

Agent Network v0.3.1 completed the evidence-constrained Reconciliation milestone, including independent Dual Fact verification, evidence gating, and structured manual-review routing.

v0.4 M1 begins the next capability: accepting a Markdown technical report and producing auditable Claim candidates that can be passed to the existing Claim Verification Pipeline.

The M1 goal is deliberately narrow:

- provide a stable Markdown extraction entry point;
- reuse the existing deterministic Claim extractor;
- produce canonical Claim objects and machine-readable output;
- preserve source provenance and extraction statistics;
- perform zero model calls and zero network calls.

## 2. Evolution from v0.3.1 to v0.4 M1

| Area | v0.3.1 | v0.4 M1 |
| --- | --- | --- |
| Primary input | Existing Claim or benchmark fixture | Markdown technical report |
| Claim creation | Claims supplied by caller or fixture adapter | Deterministic Markdown extraction |
| Evidence verification | Available through existing pipeline | Not executed by extract-claims |
| Dual Fact | Stable independent Fact A/B module | Not included in M1 |
| Reconciliation | Local deterministic result routing | Unchanged |
| New model calls | None beyond existing workflows | None |
| New network calls | No evidence network calls in offline path | None |

The existing four-agent workflow remains:

Fact -> Security -> Logic -> Merge

M1 adds an extraction command without changing that workflow.

## 3. Markdown to ClaimRegistry data flow

The M1 data flow is:

Markdown file
  -> UTF-8 read
  -> ClaimExtractionRequest
  -> Markdown segmentation
  -> candidate filtering and normalization
  -> Claim validation
  -> ClaimRegistry
  -> ClaimExtractionResult JSON

The extractor handles Markdown structure including:

- headings and heading paths;
- paragraphs;
- list items;
- table rows;
- fenced code exclusion;
- URL and command exclusion;
- duplicate Claim detection.

Each accepted Claim retains its source file, source location, heading path, line range, type, extraction confidence, and extraction method.

## 4. extract-claims CLI

Basic usage:

agent-network extract-claims report.md

The command writes ClaimExtractionResult JSON to stdout.

Save the result to a file:

agent-network extract-claims report.md --output claims.json

Override the stable source identity:

agent-network extract-claims report.md --source-name architecture-report.md

The default source_name is the input file basename. The command is deterministic and does not load model providers or evidence network clients.

The JSON output includes:

- claims;
- failures;
- candidate_count;
- extracted_count;
- duplicate_count;
- failure_count;
- selected_count;
- truncated_count.

For M1, selected_count equals extracted_count and truncated_count is zero because the extraction CLI does not truncate Claims.

## 5. Canonical Claim contract

M1 uses the existing Claim model from src/agent_network/claim/claim.py.

Important fields include:

- claim_id;
- text;
- normalized_text;
- source_file;
- source_location;
- section;
- heading_path;
- line_start;
- line_end;
- product;
- component;
- claim_type;
- extraction_confidence;
- extraction_method;
- status.

Claim IDs are stable hashes derived from source identity, heading context, and normalized Claim text.

M1 does not introduce a report-specific Claim schema and does not modify the existing Claim contract.

## 6. Extraction Benchmark results

The dedicated fixture is:

benchmarks/fixtures/report-claim-extraction-v1/

The benchmark tests extraction only. It does not run Evidence Verification, Fact A/B, or Reconciliation.

Results:

| Metric | Result |
| --- | ---: |
| candidate_count | 10 |
| extracted_count | 3 |
| duplicate_count | 1 |
| failure_count | 0 |
| model calls | 0 |
| network calls | 0 |

The benchmark also verifies:

- expected Claim IDs;
- expected heading paths;
- deterministic repeatability;
- fixture contract stability.

Current repository validation:

- pytest: 365 passed;
- Ruff: passed.

## 7. Current limitations

v0.4 M1 is an extraction milestone only.

- It does not run Evidence Verification.
- It does not invoke the Dual Fact adapter.
- It does not invoke Fact A or Fact B.
- It does not perform Reconciliation.
- Claim extraction does not equal factual verification.
- Extraction rules may miss implicit claims or combine multiple facts in one paragraph.
- Claim IDs depend on stable source_name, heading context, and normalized text.
- Long-report Claim selection and verification limits remain separate concerns.
- Claim extraction confidence describes extraction heuristics, not truth confidence.

## 8. Follow-up direction

The next integration step is to pass ClaimRegistry into the existing Claim Verification Pipeline:

ClaimRegistry
  -> local or controlled Evidence retrieval
  -> EvidenceDecisionEngine
  -> FactReviewInput

A later milestone may add the explicit ClaimRegistry to FactReviewInput adapter for Dual Fact. That work must preserve Fact A/B isolation, batch planning, citation validation, and the existing model and network cost constraints.

v0.4 M1 provides the stable input contract for that future work without changing the v0.3.1 verification architecture.
