"""Claim-aware, deterministic BM25 selection over offline document chunks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import ceil
from urllib.parse import urlparse

from agent_network.evidence.document_bm25 import (
    Bm25SearchQuery,
    OfficialDocumentBm25Index,
    tokenize,
)
from agent_network.evidence.document_chunker import DocumentChunk
from agent_network.evidence.vocabulary import (
    normalize_component,
    normalize_product,
    source_priority_for_domain,
)


@dataclass(frozen=True, slots=True)
class EvidenceSelectionConfig:
    max_evidence_per_claim: int = 3
    max_excerpt_chars_per_evidence: int = 1500
    max_total_evidence_chars_per_claim: int = 3000
    max_total_selected_chunks: int = 100
    min_relevance_score: float = 0.0

    def __post_init__(self) -> None:
        if (
            self.max_evidence_per_claim <= 0
            or self.max_excerpt_chars_per_evidence <= 0
            or self.max_total_evidence_chars_per_claim <= 0
            or self.max_total_selected_chunks <= 0
            or self.min_relevance_score < 0
        ):
            raise ValueError("Evidence selection limits must be positive")


@dataclass(frozen=True, slots=True)
class ClaimQuery:
    claim_id: str
    query_terms: tuple[str, ...]
    boosted_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]
    product_filter: str | None
    component_filter: str | None
    version_filter: str | None
    document_type_filter: str | None = None

    @property
    def query_text(self) -> str:
        return " ".join((*self.query_terms, *self.boosted_terms))


@dataclass(slots=True)
class SelectedEvidence:
    chunk_id: str
    document_id: str
    canonical_url: str
    heading_path: list[str]
    text_excerpt: str
    bm25_score: float
    final_score: float
    matched_terms: list[str]
    product_match: bool
    component_match: bool | None
    version_match: bool | None
    document_type: str
    source_priority: int
    selection_reason: str
    evidence_limitations: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalResult:
    claim_id: str
    query_terms: list[str]
    candidate_count: int
    filtered_candidate_count: int
    selected_count: int
    top_k: int
    results: list[SelectedEvidence]
    no_match_reason: str | None = None
    version_fallback_used: bool = False
    retrieval_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(slots=True)
class RetrievalBatchAudit:
    total_claims: int
    deduplicated_claims: int
    total_chunks: int
    total_candidates: int
    total_selected: int
    average_selected_per_claim: float
    estimated_context_chars: int
    estimated_context_tokens: int
    network_request_count: int = 0
    model_call_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FactBatchBudgetConfig:
    max_claims: int = 100
    claims_per_batch: int = 10
    max_fact_batches: int = 10
    max_total_evidence_chars: int = 30_000
    max_estimated_total_tokens: int = 12_000


@dataclass(slots=True)
class FactBatchBudgetEstimate:
    estimated_fact_batches: int
    estimated_model_calls: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    budget_exceeded: bool
    excluded_no_evidence_claims: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_claim_query(claim) -> ClaimQuery:
    """Build a stable query without treating all raw claim text as a prompt."""

    normalized = getattr(claim, "normalized_claim", None) or getattr(claim, "normalized_text", "")
    terms = tuple(dict.fromkeys(tokenize(normalized)))
    product = _controlled_value(getattr(claim, "product", None), normalize_product)
    component = _controlled_value(getattr(claim, "component", None), normalize_component)
    entities = getattr(claim, "entities", []) or []
    entity_text = " ".join(str(getattr(entity, "value", entity)) for entity in entities)
    boosted = tuple(dict.fromkeys(tokenize(entity_text)))
    if product:
        boosted = tuple(dict.fromkeys((*boosted, *tokenize(product.replace("_", " ")))))
    if component:
        boosted = tuple(dict.fromkeys((*boosted, *tokenize(component.replace("_", " ")))))
    scope = getattr(claim, "version_scope", None)
    version = getattr(scope, "exact", None) if scope is not None else None
    return ClaimQuery(
        claim_id=str(getattr(claim, "claim_id", "")),
        query_terms=terms,
        boosted_terms=boosted,
        excluded_terms=(),
        product_filter=getattr(claim, "product", None),
        component_filter=getattr(claim, "component", None),
        version_filter=version,
    )


class OfflineBm25EvidenceRetriever:
    """Offline-only selector; it never fetches, calls models, or infers support."""

    def __init__(
        self, chunks: list[DocumentChunk], config: EvidenceSelectionConfig | None = None
    ) -> None:
        self.chunks = tuple(chunks)
        self.config = config or EvidenceSelectionConfig()
        self.index = OfficialDocumentBm25Index(list(self.chunks)) if self.chunks else None
        self.network_request_count = 0
        self.model_call_count = 0

    def retrieve(self, claim, *, top_k: int | None = None) -> RetrievalResult:
        query = build_claim_query(claim)
        limit = min(top_k or self.config.max_evidence_per_claim, self.config.max_evidence_per_claim)
        if not query.query_terms or self.index is None:
            return RetrievalResult(
                claim_id=query.claim_id,
                query_terms=list(query.query_terms),
                candidate_count=0,
                filtered_candidate_count=0,
                selected_count=0,
                top_k=limit,
                results=[],
                no_match_reason="empty_query" if not query.query_terms else "no_indexed_chunks",
            )
        results = self.index.search(
            Bm25SearchQuery(
                query_text=query.query_text,
                top_k=len(self.chunks),
                product=query.product_filter,
                component=query.component_filter,
                document_type=query.document_type_filter,
            )
        )
        candidates = list(results)
        relevant_candidates = [
            item for item in candidates if set(item.matched_terms).intersection(query.query_terms)
        ]
        version_matches = [
            item
            for item in relevant_candidates
            if _version_matches(item.chunk, query.version_filter)
        ]
        use_fallback = bool(query.version_filter and not version_matches and relevant_candidates)
        eligible = (
            version_matches if query.version_filter and version_matches else relevant_candidates
        )
        selected: list[SelectedEvidence] = []
        total_chars = 0
        warnings: list[str] = []
        for item in eligible:
            final_score = _final_score(item.score, item.chunk)
            if final_score < self.config.min_relevance_score:
                continue
            excerpt, truncated = _excerpt(
                item.chunk.text, self.config.max_excerpt_chars_per_evidence
            )
            if total_chars + len(excerpt) > self.config.max_total_evidence_chars_per_claim:
                remaining = self.config.max_total_evidence_chars_per_claim - total_chars
                if remaining <= 0:
                    warnings.append("evidence_budget_exhausted")
                    break
                excerpt, clipped = _excerpt(excerpt, remaining)
                truncated = truncated or clipped
            limitations: list[str] = ["BM25 relevance is not direct factual support."]
            version_match = (
                _version_matches(item.chunk, query.version_filter) if query.version_filter else None
            )
            if use_fallback:
                limitations.append(
                    "Requested version was not found; this is a version-mismatch fallback."
                )
            if truncated:
                limitations.append("Evidence excerpt was truncated to the configured budget.")
                warnings.append("evidence_excerpt_truncated")
            selected.append(
                SelectedEvidence(
                    chunk_id=item.chunk.chunk_id,
                    document_id=item.chunk.document_id,
                    canonical_url=item.chunk.canonical_url,
                    heading_path=list(item.chunk.heading_path) or [item.chunk.section_heading],
                    text_excerpt=excerpt,
                    bm25_score=item.score,
                    final_score=final_score,
                    matched_terms=list(item.matched_terms),
                    product_match=True,
                    component_match=True if query.component_filter else None,
                    version_match=version_match,
                    document_type=item.chunk.document_type,
                    source_priority=_source_priority(item.chunk.canonical_url),
                    selection_reason="bm25_ranked_candidate"
                    if not use_fallback
                    else "version_fallback",
                    evidence_limitations=limitations,
                )
            )
            total_chars += len(excerpt)
            if len(selected) >= limit:
                break
        if not selected and eligible:
            reason = "below_min_relevance_score"
        elif not selected:
            reason = "no_matching_chunk"
        else:
            reason = None
        return RetrievalResult(
            claim_id=query.claim_id,
            query_terms=list(query.query_terms),
            candidate_count=len(candidates),
            filtered_candidate_count=len(eligible),
            selected_count=len(selected),
            top_k=limit,
            results=selected,
            no_match_reason=reason,
            version_fallback_used=use_fallback,
            retrieval_warnings=list(dict.fromkeys(warnings)),
        )

    def retrieve_batch(
        self, claims: list, *, top_k: int | None = None
    ) -> tuple[list[RetrievalResult], RetrievalBatchAudit]:
        unique = []
        seen: set[tuple[str, str]] = set()
        for claim in claims:
            query = build_claim_query(claim)
            key = (query.claim_id, " ".join(query.query_terms))
            if key not in seen:
                seen.add(key)
                unique.append(claim)
        results = [self.retrieve(claim, top_k=top_k) for claim in unique]
        remaining = self.config.max_total_selected_chunks
        for result in results:
            if result.selected_count <= remaining:
                remaining -= result.selected_count
                continue
            result.results = result.results[: max(0, remaining)]
            result.selected_count = len(result.results)
            result.retrieval_warnings = list(
                dict.fromkeys([*result.retrieval_warnings, "batch_selected_chunk_budget_exhausted"])
            )
            remaining = 0
        selected = sum(result.selected_count for result in results)
        chars = sum(len(item.text_excerpt) for result in results for item in result.results)
        return results, RetrievalBatchAudit(
            total_claims=len(claims),
            deduplicated_claims=len(unique),
            total_chunks=len(self.chunks),
            total_candidates=sum(result.candidate_count for result in results),
            total_selected=selected,
            average_selected_per_claim=selected / len(unique) if unique else 0.0,
            estimated_context_chars=chars,
            estimated_context_tokens=ceil(chars / 4),
        )


def estimate_fact_batch_budget(
    retrieval_results: list[RetrievalResult], config: FactBatchBudgetConfig | None = None
) -> FactBatchBudgetEstimate:
    config = config or FactBatchBudgetConfig()
    evidence_results = [result for result in retrieval_results if result.results]
    chars = sum(len(item.text_excerpt) for result in evidence_results for item in result.results)
    batches = ceil(len(evidence_results) / config.claims_per_batch) if evidence_results else 0
    input_tokens = ceil(chars / 4)
    output_tokens = batches * 500
    total_tokens = input_tokens + output_tokens
    exceeded = (
        len(retrieval_results) > config.max_claims
        or batches > config.max_fact_batches
        or chars > config.max_total_evidence_chars
        or total_tokens > config.max_estimated_total_tokens
    )
    return FactBatchBudgetEstimate(
        estimated_fact_batches=batches,
        estimated_model_calls=batches,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
        estimated_total_tokens=total_tokens,
        budget_exceeded=exceeded,
        excluded_no_evidence_claims=len(retrieval_results) - len(evidence_results),
    )


def _controlled_value(value: str | None, normalizer) -> str | None:
    if not value:
        return None
    try:
        return normalizer(value)
    except ValueError:
        return None


def _version_matches(chunk: DocumentChunk, requested: str | None) -> bool:
    return requested is None or chunk.product_version == requested


def _source_priority(url: str) -> int:
    try:
        return source_priority_for_domain(urlparse(url).hostname or "")
    except ValueError:
        return 50


def _final_score(score: float, chunk: DocumentChunk) -> float:
    return score * (1 + _source_priority(chunk.canonical_url) / 1000)


def _excerpt(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip(), True
