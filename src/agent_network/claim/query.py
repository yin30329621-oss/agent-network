"""Deterministic adaptation from Claim metadata to cache retrieval requests."""

from __future__ import annotations

from dataclasses import dataclass

from agent_network.claim.claim import Claim
from agent_network.evidence.cached_official_evidence import CachedEvidenceRetrievalRequest


@dataclass(frozen=True, slots=True)
class ClaimRetrievalQuery:
    """Auditable query and exact filters derived from an existing Claim only."""

    query_text: str
    product: str | None
    component: str | None
    document_type: str | None
    document_ids: tuple[str, ...] | None

    def to_dict(self) -> dict[str, str | list[str] | None]:
        return {
            "query_text": self.query_text,
            "product": self.product,
            "component": self.component,
            "document_type": self.document_type,
            "document_ids": list(self.document_ids) if self.document_ids else None,
        }


def query_for_claim(
    claim: Claim,
    *,
    document_ids: tuple[str, ...] | None = None,
    document_type: str | None = None,
) -> ClaimRetrievalQuery:
    """Build a stable query without adding facts or rewriting the Claim."""

    return ClaimRetrievalQuery(
        query_text=claim.normalized_text or claim.text,
        product=claim.product,
        component=claim.component,
        document_type=document_type,
        document_ids=tuple(dict.fromkeys(document_ids)) if document_ids else None,
    )


def cached_request_for_query(
    query: ClaimRetrievalQuery,
    *,
    cache_directory: str | None,
    max_documents: int,
    top_k: int,
    max_chunks_per_document: int,
    min_documents_in_results: int,
    min_score: float,
    min_matched_terms: int,
    exclude_navigation_like: bool,
) -> CachedEvidenceRetrievalRequest:
    """Map a Claim query to the existing read-only cached retriever request."""

    return CachedEvidenceRetrievalRequest(
        cache_directory=cache_directory,
        document_ids=query.document_ids,
        product=query.product,
        component=query.component,
        document_type=query.document_type,
        max_documents=max_documents,
        query_text=query.query_text,
        top_chunks=top_k,
        max_chunks_per_document=max_chunks_per_document,
        min_documents_in_results=min_documents_in_results,
        min_score=min_score,
        min_matched_terms=min_matched_terms,
        exclude_navigation_like=exclude_navigation_like,
    )
