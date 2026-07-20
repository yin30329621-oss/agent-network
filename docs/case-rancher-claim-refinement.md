# Rancher Case Claim Refinement

## 1. Current granularity problem

The case contains 53 canonical claims. EvidenceDecision v2 classified all 53 as
`partially_supported`; deterministic analysis marked 25 claims as potentially
too broad. The main issue is not retrieval coverage: BM25 returned evidence for
every claim. The issue is that one claim often combines several subjects,
mechanisms, credentials, or security conclusions, while a single evidence
chunk proves only part of that statement.

A refinement step must therefore reduce semantic scope before evidence
decisions are made. It must not convert retrieval relevance into factual
support.

## 2. Atomic claim definition

An atomic claim expresses one independently verifiable proposition:

- one subject;
- one predicate or behavior;
- one relevant scope, product, component, and version when known;
- one evidence target;
- no bundled security conclusion.

For example, “Cluster Agent initiates a connection to Rancher Server” is a
candidate atomic claim. “Cluster Agent initiates a connection, uses a reverse
tunnel, and improves platform security” contains multiple propositions and
should be split.

An atomic claim may retain necessary qualifiers such as direction, protocol,
resource, or deployment scope. Removing a qualifier merely to make matching
easier is not refinement; it changes the claim.

## 3. Broad-claim splitting rules

Refinement should apply deterministic review rules first:

1. Split coordinated predicates joined by “and”, “or”, “as well as”, or their
   Chinese equivalents when each predicate can be evidenced independently.
2. Split claims that name multiple actors or components with separate
   responsibilities.
3. Split a mechanism claim from its security-impact conclusion.
4. Split authentication, authorization, credential storage, and transport
   claims when they require different authoritative sources.
5. Split claims containing multiple protocol or token types.
6. Preserve version, product, and deployment qualifiers on every child claim.
7. Reject text that is only a heading, background statement, recommendation,
   marketing assertion, or unbounded “improves security” conclusion.
8. If splitting would require inventing a missing predicate or qualifier,
   retain the parent for manual review instead of guessing.

Each proposed child must pass an independent verification question: “Could a
reviewer accept or reject this proposition using one coherent evidence target?”

## 4. Parent-child preservation

Refinement must preserve the original Claim ID and provenance without
changing the existing Claim schema. Refinement metadata should live in a
separate artifact or sidecar document.

Recommended relationship:

```text
original claim_id
        |
        +-- refined claim_id A
        +-- refined claim_id B
```

The parent remains the provenance anchor. Each child records
`parent_claim_id` equal to the original ID, while its own stable ID is derived
from the parent ID and deterministic child ordinal or canonical text hash.
Child ordering must be stable, and a refinement run must be reproducible from
the same input and rules.

If a parent is retained without splitting, its refinement record should state
`relation: retained` and explain why it is already atomic or why manual review
is required.

## 5. Proposed refined-claim sidecar schema

This is a proposal for a new refinement artifact, not a change to the current
Claim schema:

```json
{
  "refined_claim_id": "claim-...-r01",
  "parent_claim_id": "claim-...",
  "canonical_text": "One independently verifiable proposition.",
  "claim_type": "cluster_agent",
  "verification_target": "Cluster Agent connection direction",
  "evidence_required": ["official_document", "source_code"],
  "priority": "P0",
  "relation": "split",
  "atomicity": "atomic",
  "decision_reason": "Separated transport behavior from security impact."
}
```

The sidecar should also record the refinement rule, reviewer, timestamp, and
source text hash when implementation begins. It must not overwrite the
original `canonical-claims.json`. A parent with no valid children must remain
available for manual review rather than becoming an empty slot.

## 6. Relationship to EvidenceDecision

Refinement occurs before retrieval and EvidenceDecision:

```text
canonical Claim
  -> refinement sidecar
  -> refined Claim inputs
  -> BM25 retrieval
  -> EvidenceDecisionEngine
  -> manual review or Fact Review
```

Each refined claim receives independent retrieval, evidence citations, and
decision status. Evidence must cite chunks selected for that child claim; a
parent citation must not be copied to every child without checking relevance.
The parent may be summarized from child outcomes for reporting, but a positive
child decision must not automatically upgrade the parent.

Refinement does not alter EvidenceDecisionEngine rules, add model calls, or
change Dual Fact isolation. It may increase the number of claims and therefore
the planned reviewer batches, so the existing budget preflight must run after
refinement. Duplicate retrieval and duplicate child IDs must be rejected.

The first implementation should remain human- or rule-approved, emit an
auditable sidecar, and compare parent/child counts before any Dual Fact live
run.
