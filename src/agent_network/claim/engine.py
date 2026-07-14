"""Pure-offline, conservative Claim verification over the local official cache."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_network.claim.claim import Claim
from agent_network.claim.policy import VerificationMode, status_for
from agent_network.claim.query import cached_request_for_query, query_for_claim
from agent_network.claim.registry import ClaimRegistry
from agent_network.claim.verification import (
    EvidenceLink,
    EvidenceRelation,
    VerificationResult,
    VerificationStatus,
)
from agent_network.evidence.cached_official_evidence import (
    CachedDocumentLoadError,
    CachedEvidenceIndexBuilder,
)


class ClaimVerificationFailure(BaseModel):
    claim_id: str
    code: str
    safe_message: str


class ClaimVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: Claim
    cache_directory: str | None = None
    document_ids: tuple[str, ...] | None = None
    document_type: str | None = None
    max_documents: int = Field(default=3, gt=0)
    top_k: int = Field(default=5, gt=0)
    max_chunks_per_document: int = Field(default=0, ge=0)
    min_documents_in_results: int = Field(default=1, gt=0)
    min_score: float = Field(default=0.0, ge=0.0)
    min_matched_terms: int = Field(default=1, gt=0)
    exclude_navigation_like: bool = False
    verification_mode: VerificationMode = VerificationMode.CANDIDATE_ONLY


class ClaimVerificationBatchRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    registry: ClaimRegistry
    cache_directory: str | None = None
    document_ids: tuple[str, ...] | None = None
    document_type: str | None = None
    max_documents: int = Field(default=3, gt=0)
    top_k: int = Field(default=5, gt=0)
    max_chunks_per_document: int = Field(default=0, ge=0)
    min_documents_in_results: int = Field(default=1, gt=0)
    min_score: float = Field(default=0.0, ge=0.0)
    min_matched_terms: int = Field(default=1, gt=0)
    exclude_navigation_like: bool = False
    verification_mode: VerificationMode = VerificationMode.CANDIDATE_ONLY


class ClaimVerificationEngineResult(BaseModel):
    verification: VerificationResult
    candidate_evidences: list[dict[str, Any]] = Field(default_factory=list)
    failure: ClaimVerificationFailure | None = None

    @property
    def claim_id(self) -> str:
        return self.verification.claim_id

    @property
    def verification_status(self):
        return self.verification.verification_status


class ClaimVerificationBatchResult(BaseModel):
    total_claim_count: int
    completed_claim_count: int
    failed_claim_count: int
    status_distribution: dict[str, int]
    relation_distribution: dict[str, int]
    evidence_coverage_count: int
    zero_evidence_count: int
    model_call_count: int = 0
    network_request_count: int = 0
    results: list[ClaimVerificationEngineResult]
    failures: list[ClaimVerificationFailure]


class ClaimVerificationEngine:
    """Adapt Claims to cached retrieval and return non-semantic verification results."""

    def __init__(self, index_builder: CachedEvidenceIndexBuilder) -> None:
        self.index_builder = index_builder
        self.model_call_count = 0
        self.network_request_count = 0

    def verify(self, request: ClaimVerificationRequest) -> ClaimVerificationEngineResult:
        started_at = datetime.now(UTC)
        query = query_for_claim(
            request.claim,
            document_ids=request.document_ids,
            document_type=request.document_type,
        )
        try:
            retrieved = self.index_builder.retrieve(
                cached_request_for_query(
                    query,
                    cache_directory=request.cache_directory,
                    max_documents=request.max_documents,
                    top_k=request.top_k,
                    max_chunks_per_document=request.max_chunks_per_document,
                    min_documents_in_results=request.min_documents_in_results,
                    min_score=request.min_score,
                    min_matched_terms=request.min_matched_terms,
                    exclude_navigation_like=request.exclude_navigation_like,
                )
            )
            if retrieved.discovered_document_count == 0:
                return self._unavailable(
                    request,
                    query.to_dict(),
                    started_at,
                    "cache_not_found",
                    "No controlled local official-document cache was found.",
                )
            if (
                retrieved.loaded_document_count == 0
                and not retrieved.cache_failures
                and retrieved.discovered_document_count > 0
            ):
                status = VerificationStatus.NOT_MENTIONED
                relation = EvidenceRelation.ABSENCE_OF_SUPPORT
                limitations = ["No locally cached document matched the Claim metadata filters."]
            else:
                status, relation, limitations = status_for(
                    request.claim,
                    candidate_count=retrieved.returned_evidence_count,
                    loaded_document_count=retrieved.loaded_document_count,
                    failed_document_count=retrieved.failed_document_count,
                )
            limitations = _deduplicate(
                [*limitations, *(_cache_limitations(retrieved.cache_failures))]
            )
            links = [
                _evidence_link(request.claim.claim_id, evidence, relation, limitations)
                for evidence in retrieved.evidences
            ]
            verification = VerificationResult(
                claim_id=request.claim.claim_id,
                claim_text=request.claim.text,
                normalized_text=request.claim.normalized_text,
                claim_type=request.claim.claim_type.value,
                verification_status=status,
                evidence_relation=relation,
                evidence_links=links,
                evidence_limitations=limitations,
                limitations=limitations,
                explanation=_explanation(status.value),
                requires_human_review=True,
                query_text=query.query_text,
                applied_filters=query.to_dict(),
                candidate_evidence_count=retrieved.candidate_evidence_count,
                returned_document_count=retrieved.returned_document_count,
                loaded_document_count=retrieved.loaded_document_count,
                failed_document_count=retrieved.failed_document_count,
                cache_failures=[failure.to_dict() for failure in retrieved.cache_failures],
                verification_mode=request.verification_mode.value,
                model_call_count=0,
                network_request_count=0,
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
            failure = None
            if retrieved.loaded_document_count == 0 and retrieved.cache_failures:
                failure = ClaimVerificationFailure(
                    claim_id=request.claim.claim_id,
                    code="all_cache_failed",
                    safe_message="All selected local official-document cache entries failed to load.",
                )
            return ClaimVerificationEngineResult(
                verification=verification,
                candidate_evidences=[
                    _candidate_evidence(evidence) for evidence in retrieved.evidences
                ],
                failure=failure,
            )
        except CachedDocumentLoadError as exc:
            code = "invalid_cache_directory" if exc.code == "cache_read_error" else exc.code
            return self._unavailable(request, query.to_dict(), started_at, code, str(exc))
        except Exception:
            return self._unavailable(
                request,
                query.to_dict(),
                started_at,
                "verification_error",
                "Claim verification could not complete.",
            )

    def verify_batch(self, request: ClaimVerificationBatchRequest) -> ClaimVerificationBatchResult:
        results: list[ClaimVerificationEngineResult] = []
        failures: list[ClaimVerificationFailure] = []
        for claim in request.registry:
            result = self.verify(
                ClaimVerificationRequest(
                    claim=claim,
                    cache_directory=request.cache_directory,
                    document_ids=request.document_ids,
                    document_type=request.document_type,
                    max_documents=request.max_documents,
                    top_k=request.top_k,
                    max_chunks_per_document=request.max_chunks_per_document,
                    min_documents_in_results=request.min_documents_in_results,
                    min_score=request.min_score,
                    min_matched_terms=request.min_matched_terms,
                    exclude_navigation_like=request.exclude_navigation_like,
                    verification_mode=request.verification_mode,
                )
            )
            results.append(result)
            if result.failure is not None:
                failures.append(result.failure)
        status_distribution = Counter(
            item.verification.verification_status.value for item in results
        )
        relation_distribution = Counter(
            item.verification.evidence_relation.value for item in results
        )
        evidence_coverage = sum(bool(item.verification.evidence_links) for item in results)
        return ClaimVerificationBatchResult(
            total_claim_count=len(request.registry),
            completed_claim_count=len(results) - len(failures),
            failed_claim_count=len(failures),
            status_distribution=dict(status_distribution),
            relation_distribution=dict(relation_distribution),
            evidence_coverage_count=evidence_coverage,
            zero_evidence_count=len(results) - evidence_coverage,
            results=results,
            failures=failures,
        )

    def _unavailable(
        self,
        request: ClaimVerificationRequest,
        filters: dict[str, str | list[str] | None],
        started_at: datetime,
        code: str,
        safe_message: str,
    ) -> ClaimVerificationEngineResult:
        failure = ClaimVerificationFailure(
            claim_id=request.claim.claim_id,
            code=code,
            safe_message=safe_message,
        )
        verification = VerificationResult(
            claim_id=request.claim.claim_id,
            claim_text=request.claim.text,
            normalized_text=request.claim.normalized_text,
            claim_type=request.claim.claim_type.value,
            verification_status="unavailable",
            evidence_relation="unavailable",
            evidence_limitations=[safe_message],
            limitations=[safe_message],
            explanation="Local official-document evidence was unavailable.",
            requires_human_review=True,
            query_text=filters["query_text"] if isinstance(filters["query_text"], str) else None,
            applied_filters=filters,
            verification_mode=request.verification_mode.value,
            model_call_count=0,
            network_request_count=0,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        return ClaimVerificationEngineResult(verification=verification, failure=failure)


def _evidence_link(claim_id: str, evidence, relation, limitations: list[str]) -> EvidenceLink:
    digest = sha256(f"{claim_id}\x1f{evidence.chunk_id}".encode("utf-8")).hexdigest()[:16]
    return EvidenceLink(
        evidence_id=f"evidence-{digest}",
        claim_id=claim_id,
        chunk_id=evidence.chunk_id,
        document_id=evidence.document_id,
        canonical_url=evidence.canonical_url,
        rank=evidence.rank,
        relation=relation,
        matched_terms=evidence.matched_terms,
        score=evidence.score,
        limitations=limitations,
    )


def _candidate_evidence(evidence: Any) -> dict[str, Any]:
    """Keep only retrieved Chunk fields that may be safely bounded for Fact context."""

    return {
        "rank": evidence.rank,
        "score": evidence.score,
        "matched_terms": list(evidence.matched_terms),
        "chunk_id": evidence.chunk_id,
        "document_id": evidence.document_id,
        "canonical_url": evidence.canonical_url,
        "product": evidence.product,
        "component": evidence.component,
        "document_type": evidence.document_type,
        "document_title": evidence.document_title,
        "section_heading": evidence.section_heading,
        "text": evidence.text,
        "source_fetched_at": evidence.source_fetched_at.isoformat(),
    }


def _cache_limitations(failures: list[Any]) -> list[str]:
    return (
        ["Some local official-document cache entries could not be processed."] if failures else []
    )


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _explanation(status: str) -> str:
    return {
        "insufficient_evidence": "Relevant local official evidence was retrieved, but it has not received semantic verification.",
        "not_mentioned": "No positive-scoring local official evidence was retrieved for this claim.",
        "needs_external_verification": "This time-sensitive claim requires external verification beyond the local cache.",
        "unavailable": "Local official-document evidence was unavailable.",
        "extraction_failed": "Claim extraction failed; verification was not attempted.",
    }[status]
