"""Conservative deterministic verification policy."""

from __future__ import annotations

import re
from enum import StrEnum

from agent_network.claim.claim import Claim, ClaimStatus, ClaimType
from agent_network.claim.verification import EvidenceRelation, VerificationStatus


class VerificationMode(StrEnum):
    CANDIDATE_ONLY = "candidate_only"
    RULE_BASED = "rule_based"


_TEMPORAL_TERMS = re.compile(
    r"\b(cve[- ]?\d{4}-\d+|latest|current|patch|release|advisory|affected|fixed|version)\b",
    re.IGNORECASE,
)


def is_temporal_claim(claim: Claim) -> bool:
    return claim.claim_type in {
        ClaimType.VERSION_SUPPORT,
        ClaimType.CITATION_OR_PROVENANCE,
    } or bool(_TEMPORAL_TERMS.search(claim.normalized_text or claim.text))


def status_for(
    claim: Claim,
    *,
    candidate_count: int,
    loaded_document_count: int,
    failed_document_count: int,
) -> tuple[VerificationStatus, EvidenceRelation, list[str]]:
    """Map retrieval facts to a conservative, non-semantic outcome."""

    if claim.status == ClaimStatus.EXTRACTION_FAILED:
        return (
            VerificationStatus.EXTRACTION_FAILED,
            EvidenceRelation.UNAVAILABLE,
            ["Claim extraction failed; verification was not attempted."],
        )
    if loaded_document_count == 0:
        return (
            VerificationStatus.UNAVAILABLE,
            EvidenceRelation.UNAVAILABLE,
            ["No usable local official-document cache was available."],
        )
    if is_temporal_claim(claim):
        relation = (
            EvidenceRelation.INDIRECT_EVIDENCE
            if candidate_count
            else EvidenceRelation.ABSENCE_OF_SUPPORT
        )
        return (
            VerificationStatus.NEEDS_EXTERNAL_VERIFICATION,
            relation,
            ["Local official-document cache may be stale for time-sensitive facts."],
        )
    if candidate_count:
        limitations = [
            "Retrieved evidence is lexically related and has not received semantic verification."
        ]
        if failed_document_count:
            limitations.append("Some local official-document cache entries could not be processed.")
        return (
            VerificationStatus.INSUFFICIENT_EVIDENCE,
            EvidenceRelation.INDIRECT_EVIDENCE,
            limitations,
        )
    return (
        VerificationStatus.NOT_MENTIONED,
        EvidenceRelation.ABSENCE_OF_SUPPORT,
        ["No positive-scoring local official-document evidence was returned for this claim."],
    )
