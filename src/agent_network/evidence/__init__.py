"""Offline evidence verification primitives."""

from agent_network.evidence.matcher import DeterministicEvidenceMatcher, EvidenceMatch
from agent_network.evidence.catalog import DocumentCatalogQuery, DocumentCatalogRepository
from agent_network.evidence.document_fetcher import (
    FetchAudit,
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
from agent_network.evidence.official_evidence_retriever import (
    FixtureOfficialDocumentContentProvider,
    OfficialEvidenceRetrievalError,
    OfficialEvidenceRetrievalRequest,
    OfficialEvidenceRetrievalResult,
    OfficialEvidenceRetriever,
    RetrievedOfficialEvidence,
)
from agent_network.evidence.github_advisory import GitHubAdvisoryEvidenceSource
from agent_network.evidence.http import EvidenceHttpClient
from agent_network.evidence.nvd import NvdEvidenceSource
from agent_network.evidence.pipeline_benchmark import (
    EvidencePipelineBenchmarkCase,
    EvidencePipelineBenchmarkFixture,
    EvidencePipelineBenchmarkResult,
    EvidencePipelineCaseResult,
    EvidencePipelineMetrics,
    run_evidence_pipeline_benchmark,
    write_evidence_pipeline_benchmark,
)
from agent_network.evidence.offline_retrieval import (
    ClaimQuery,
    EvidenceSelectionConfig,
    FactBatchBudgetConfig,
    FactBatchBudgetEstimate,
    OfflineBm25EvidenceRetriever,
    RetrievalBatchAudit,
    RetrievalResult,
    SelectedEvidence,
    build_claim_query,
    estimate_fact_batch_budget,
)
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
    OfficialDocumentDomainConfig,
    OfficialDocumentEvidenceSource,
    load_official_document_domain_config,
)
from agent_network.evidence.verifier import OfflineEvidenceVerifier, VerificationReport

__all__ = [
    "Claim",
    "ClaimQuery",
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
    "EvidenceSelectionConfig",
    "EvidenceFixture",
    "EvidenceHttpClient",
    "EvidenceMatch",
    "EvidencePipelineBenchmarkCase",
    "EvidencePipelineBenchmarkFixture",
    "EvidencePipelineBenchmarkResult",
    "EvidencePipelineCaseResult",
    "EvidencePipelineMetrics",
    "EvidenceStrength",
    "FakeEvidenceSource",
    "FactBatchBudgetConfig",
    "FactBatchBudgetEstimate",
    "FetchAudit",
    "FixtureOfficialDocumentEvidenceSource",
    "FixtureOfficialDocumentContentProvider",
    "GitHubAdvisoryEvidenceSource",
    "HttpOfficialDocumentFetcher",
    "NvdEvidenceSource",
    "OfflineEvidenceVerifier",
    "OfflineBm25EvidenceRetriever",
    "OfficialDocumentFetchError",
    "OfficialDocumentFetchResult",
    "OfficialDocumentCleaner",
    "OfficialDocumentBm25Index",
    "OfficialDocumentChunker",
    "OfficialDocumentEvidenceSource",
    "OfficialDocumentDomainConfig",
    "OfficialEvidenceRetrievalError",
    "OfficialEvidenceRetrievalRequest",
    "OfficialEvidenceRetrievalResult",
    "OfficialEvidenceRetriever",
    "RetrievedOfficialEvidence",
    "RetrievalBatchAudit",
    "RetrievalResult",
    "SelectedEvidence",
    "VerificationReport",
    "VerificationResult",
    "VerificationStatus",
    "load_official_document_domain_config",
    "run_evidence_pipeline_benchmark",
    "build_claim_query",
    "estimate_fact_batch_budget",
    "write_evidence_pipeline_benchmark",
]
