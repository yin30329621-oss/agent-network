"""Claim verification contract models."""

from agent_network.claim.claim import Claim, ClaimStatus, ClaimType
from agent_network.claim.registry import ClaimRegistry
from agent_network.claim.extractor import (
    ClaimExtractionConfig,
    ClaimExtractionFailure,
    ClaimExtractionRequest,
    ClaimExtractionResult,
    DeterministicClaimExtractor,
)
from agent_network.claim.verification import (
    EvidenceLink,
    EvidenceRelation,
    VerificationResult,
    VerificationStatus,
)

__all__ = [
    "Claim",
    "ClaimRegistry",
    "ClaimStatus",
    "ClaimType",
    "ClaimExtractionConfig",
    "ClaimExtractionFailure",
    "ClaimExtractionRequest",
    "ClaimExtractionResult",
    "DeterministicClaimExtractor",
    "EvidenceLink",
    "EvidenceRelation",
    "VerificationResult",
    "VerificationStatus",
]
