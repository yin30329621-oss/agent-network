import json

import pytest
from pydantic import ValidationError

from agent_network.claim import (
    EvidenceLink,
    EvidenceRelation,
    VerificationResult,
    VerificationStatus,
)


def link(relation: EvidenceRelation = EvidenceRelation.DIRECT_SUPPORT) -> EvidenceLink:
    return EvidenceLink(
        evidence_id="evidence-001",
        claim_id="claim-001",
        chunk_id="chunk-001",
        document_id="doc-001",
        canonical_url="https://docs.example.test/document",
        relation=relation,
        matched_terms=["cluster", "cluster"],
        score=2.5,
    )


def test_supported_result_requires_verified_direct_evidence() -> None:
    result = VerificationResult(
        claim_id="claim-001",
        verification_status=VerificationStatus.VERIFIED_SUPPORTED,
        evidence_links=[link()],
        explanation="The official chunk directly states the relationship.",
    )

    payload = json.loads(result.to_json())
    assert payload["verification_status"] == "verified_supported"
    assert payload["evidence_links"][0]["matched_terms"] == ["cluster"]
    assert VerificationResult.from_json(result.to_json()) == result


def test_result_rejects_cross_claim_and_unreferenced_direct_contradiction() -> None:
    with pytest.raises(ValidationError, match="all evidence links"):
        VerificationResult(
            claim_id="claim-001",
            verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            evidence_links=[link().model_copy(update={"claim_id": "claim-002"})],
            explanation="The evidence is incomplete.",
        )

    with pytest.raises(ValidationError, match="contradiction evidence"):
        VerificationResult(
            claim_id="claim-001",
            verification_status=VerificationStatus.VERIFIED_CONTRADICTED,
            explanation="Contradicted.",
        )


def test_unavailable_result_can_be_serialized_without_evidence() -> None:
    result = VerificationResult(
        claim_id="claim-001",
        verification_status=VerificationStatus.UNAVAILABLE,
        evidence_limitations=["cache unavailable", "cache unavailable"],
        explanation="No official evidence was available.",
    )

    assert result.evidence_limitations == ["cache unavailable"]
    assert json.loads(result.to_json())["evidence_links"] == []


def test_evidence_link_rejects_empty_identifiers() -> None:
    with pytest.raises(ValidationError):
        EvidenceLink(**(link().model_dump() | {"chunk_id": ""}))
