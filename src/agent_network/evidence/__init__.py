"""Offline evidence verification primitives."""

from agent_network.evidence.matcher import DeterministicEvidenceMatcher, EvidenceMatch
from agent_network.evidence.github_advisory import GitHubAdvisoryEvidenceSource
from agent_network.evidence.http import EvidenceHttpClient
from agent_network.evidence.nvd import NvdEvidenceSource
from agent_network.evidence.schemas import (
    Claim,
    ClaimType,
    DocumentCatalog,
    Evidence,
    EvidenceStrength,
    VerificationResult,
    VerificationStatus,
)
from agent_network.evidence.sources import (
    DocumentCatalogFixture,
    EvidenceFixture,
    FakeEvidenceSource,
    FixtureOfficialDocumentEvidenceSource,
    OfficialDocumentEvidenceSource,
)
from agent_network.evidence.verifier import OfflineEvidenceVerifier, VerificationReport

__all__ = [
    "Claim",
    "ClaimType",
    "DeterministicEvidenceMatcher",
    "DocumentCatalog",
    "DocumentCatalogFixture",
    "Evidence",
    "EvidenceFixture",
    "EvidenceHttpClient",
    "EvidenceMatch",
    "EvidenceStrength",
    "FakeEvidenceSource",
    "FixtureOfficialDocumentEvidenceSource",
    "GitHubAdvisoryEvidenceSource",
    "NvdEvidenceSource",
    "OfflineEvidenceVerifier",
    "OfficialDocumentEvidenceSource",
    "VerificationReport",
    "VerificationResult",
    "VerificationStatus",
]
