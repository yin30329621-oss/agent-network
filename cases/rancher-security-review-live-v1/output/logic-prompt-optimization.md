# Logic Prompt Optimization Design

## Scope

This document proposes a prompt-only optimization for the Logic Agent. It does not change the Logic role, output schema, model configuration, provider adapter, or source code.

## 1. Current Prompt Composition

The current case-local runner sends a shared review context to Security and Logic. The Logic request contains:

| Component | Estimated tokens | Status | Impact |
|---|---:|---|---|
| Logic system prompt | 469 | Must keep, but prose can be shortened | Defines logical-review scope and JSON contract |
| Claims | 2,423 | Must keep | Required premises and claim-to-finding locations |
| Evidence references and excerpts | 8,087 | Optional/conditional | Largest component; useful only when a claim is disputed |
| Fact A/B structured results | 2,136 | Must keep | Primary factual premises for logic checks |
| Instruction/source metadata | 36 | Keep minimally | JSON-only instruction and source identity |

The actual observed provider prompt was 21,408 tokens. The character-based estimates are directional because provider tokenization differs.

## 2. Required and Optional Context

Must retain:

- Claim identity and claim text
- Verification Engine final status and limitations
- Fact A final conclusion
- Fact B final conclusion
- Security final conclusion
- Claim-to-result alignment
- Cited chunk IDs when a finding depends on evidence

Optional or conditionally retained:

- Full evidence excerpts
- Full limitations arrays
- Long reasoning summaries
- Repeated citations and URLs
- Repeated document metadata
- Duplicate claim headings
- Evidence for claims where Fact A/B and Security agree

Important current-runner gap: the Logic request currently reuses the Security input request and does not append a separate Security Agent result. The optimization should add only a compact Security conclusion, not the full Security prompt or evidence context.

## 3. Component-Level Reduction

### Claims

Keep one compact record per claim:

- claim_id
- claim text
- claim type or heading only when needed for location

Remove duplicate source metadata and repeated full heading paths where the claim ID already identifies the record.

### Verification Engine

Keep:

- decision status
- evidence decision status
- limitations only when non-empty

Remove full retrieval records and duplicate decision evidence text.

### Fact A and Fact B

Keep one compact result per claim:

- claim_id
- decision or recommended status
- cited_chunk_ids
- short reasoning_summary
- non-empty limitations only

Do not repeat the claim text or evidence excerpts inside each reviewer result.

### Security

Add only the final structured conclusion per claim:

- claim_id
- status or finding relation
- short reason
- cited references only when present

Do not pass the full Security prompt, repeated evidence, or complete finding prose.

### Evidence

Use conditional evidence:

- Include chunk_id and source_type for traceability.
- Include a short excerpt only for claims marked disputed, unsupported, or requiring external verification.
- Omit evidence excerpts for claims where all reviewers agree and no evidence gap is raised.

### Metadata

Retain only source_name, language, and artifact version if needed. Remove provider names, model names, timestamps, and duplicated telemetry from the Logic prompt; these belong in run metadata.

## 4. Minimal Prompt Shape

A compact Logic input should be structurally similar to:

- claims: claim_id, claim_text, verification_status
- fact_a: claim_id, status, short_reason, cited_chunk_ids
- fact_b: claim_id, status, short_reason, cited_chunk_ids
- security: claim_id, status, short_reason
- evidence: only disputed-claim chunk_id, source_type, short excerpt
- policy: review logical consistency only; output the existing JSON schema

The system prompt should keep the existing schema and role boundary, but shorten explanatory paragraphs and explicitly require:

- JSON only
- bounded findings count
- concise fields
- no evidence repetition
- no reasoning chain
- no new factual claims

## 5. Recommended Reduction Order

1. Remove full evidence excerpts from undisputed claims.
2. Replace Fact A/B reasoning summaries with bounded short reasons.
3. Add compact Security conclusions instead of reusing the Security context.
4. Remove duplicate metadata and URLs.
5. Shorten the Logic system prompt while preserving the exact output schema.
6. Re-measure prompt tokens before changing batching or retry behavior.

The highest-value reduction is evidence context: the current evidence component is approximately 8,087 estimated tokens, about 62% of the character-based user-context estimate.

## 6. Compatibility and Quality Constraints

- Preserve the existing Logic Agent JSON schema exactly.
- Preserve claim_id alignment through every compact record.
- Preserve cited_chunk_ids for audit traceability.
- Do not allow the Logic Agent to upgrade evidence or invent citations.
- Do not change Fact A/B isolation.
- Do not change Security, Merge, Claim schema, or EvidenceDecision rules.
- Keep full evidence and telemetry in artifacts, not in the Logic prompt.

## 7. Expected Impact

This design should substantially reduce input repetition while preserving the premises required for logical review. It also corrects the current missing Security-result handoff with a small structured field rather than another full context copy.

The expected result is lower prompt pressure and a lower probability of output truncation without changing the Logic model or output contract. A dry-run token measurement should precede implementation.
