"""Offline evidence verification primitives."""

from agent_network.evidence.matcher import DeterministicEvidenceMatcher, EvidenceMatch
from agent_network.evidence.catalog import DocumentCatalogQuery, DocumentCatalogRepository
from agent_network.evidence.document_fetcher import (
    HttpOfficialDocumentFetcher,
    OfficialDocumentFetchError,
    OfficialDocumentFetchResult,
)
from agent_network.evidence.document_cleaner import (
    CleanedOfficialDocument,
    DocumentCleaningError,
    DocumentSection,
    OfficialDocumentCleaner,
)
from agent_network.evidence.github_advisory import GitHubAdvisoryEvidenceSource
from agent_network.evidence.http import EvidenceHttpClient
from agent_network.evidence.nvd import NvdEvidenceSource
from agent_network.evidence.schemas import (
    Claim,
    ClaimType,
    DocumentCatalog,
    DocumentType,
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
    "CleanedOfficialDocument",
    "DeterministicEvidenceMatcher",
    "DocumentCatalog",
    "DocumentCatalogFixture",
    "DocumentCatalogQuery",
    "DocumentCatalogRepository",
    "DocumentCleaningError",
    "DocumentSection",
    "DocumentType",
    "Evidence",
    "EvidenceFixture",
    "EvidenceHttpClient",
    "EvidenceMatch",
    "EvidenceStrength",
    "FakeEvidenceSource",
    "FixtureOfficialDocumentEvidenceSource",
    "GitHubAdvisoryEvidenceSource",
    "HttpOfficialDocumentFetcher",
    "NvdEvidenceSource",
    "OfflineEvidenceVerifier",
    "OfficialDocumentFetchError",
    "OfficialDocumentFetchResult",
    "OfficialDocumentCleaner",
    "OfficialDocumentEvidenceSource",
    "VerificationReport",
    "VerificationResult",
    "VerificationStatus",
]
