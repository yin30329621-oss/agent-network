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
from agent_network.evidence.document_chunker import (
    DocumentChunk,
    DocumentChunkingConfig,
    DocumentChunkingError,
    OfficialDocumentChunker,
)
from agent_network.evidence.document_bm25 import (
    Bm25Config,
    Bm25Error,
    Bm25SearchQuery,
    Bm25SearchResult,
    OfficialDocumentBm25Index,
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
    "Bm25Config",
    "Bm25Error",
    "Bm25SearchQuery",
    "Bm25SearchResult",
    "CleanedOfficialDocument",
    "DeterministicEvidenceMatcher",
    "DocumentCatalog",
    "DocumentCatalogFixture",
    "DocumentCatalogQuery",
    "DocumentCatalogRepository",
    "DocumentChunk",
    "DocumentChunkingConfig",
    "DocumentChunkingError",
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
    "OfficialDocumentBm25Index",
    "OfficialDocumentChunker",
    "OfficialDocumentEvidenceSource",
    "VerificationReport",
    "VerificationResult",
    "VerificationStatus",
]
