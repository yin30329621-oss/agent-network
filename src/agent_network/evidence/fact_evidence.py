"""Bounded, auditable Fact Agent context derived from official retrieval results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_network.evidence.official_evidence_retriever import OfficialEvidenceRetrievalResult


@dataclass(frozen=True, slots=True)
class FactEvidenceLimits:
    top_k: int = 5
    max_chars_per_evidence: int = 1600
    max_total_evidence_chars: int = 6000

    def __post_init__(self) -> None:
        if (
            self.top_k <= 0
            or self.max_chars_per_evidence <= 0
            or self.max_total_evidence_chars <= 0
        ):
            raise ValueError("Fact evidence limits must be positive")


def build_fact_evidence_context(
    result: OfficialEvidenceRetrievalResult, limits: FactEvidenceLimits
) -> dict[str, Any]:
    """Serialize ordered retrieval evidence with deterministic character budgets."""

    selected: list[dict[str, Any]] = []
    seen_chunk_ids: set[str] = set()
    remaining = limits.max_total_evidence_chars
    for evidence in result.evidences:
        if len(selected) >= limits.top_k or evidence.chunk_id in seen_chunk_ids or remaining <= 0:
            continue
        seen_chunk_ids.add(evidence.chunk_id)
        text_limit = min(limits.max_chars_per_evidence, remaining)
        text = evidence.text[:text_limit]
        selected.append(
            {
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
                "text": text,
                "text_truncated": len(text) < len(evidence.text),
                "source_fetched_at": evidence.source_fetched_at.isoformat(),
            }
        )
        remaining -= len(text)
    limitations = _limitations(result, selected)
    return {
        "claim_id": None,
        "claim_text": result.query_text,
        "retrieval_status": result.status,
        "evidence_status": _evidence_status(result.status, bool(selected)),
        "evidence_count": len(selected),
        "official_evidences": selected,
        "document_failures": [failure.to_dict() for failure in result.document_failures],
        "network_request_count": result.network_request_count,
        "evidence_limitations": limitations,
    }


def unavailable_fact_evidence_context(error_code: str) -> dict[str, Any]:
    """Create a safe degraded context when retrieval cannot run."""

    return {
        "claim_id": None,
        "claim_text": "",
        "retrieval_status": "retrieval_error",
        "evidence_status": "official_evidence_unavailable",
        "evidence_count": 0,
        "official_evidences": [],
        "document_failures": [],
        "network_request_count": 0,
        "evidence_limitations": [f"retrieval_error:{error_code}"],
    }


def validate_fact_evidence_citations(
    requested_chunk_ids: object, context: dict[str, Any]
) -> dict[str, Any]:
    """Accept only supplied chunk IDs, then derive document and URL citations locally."""

    evidence_by_chunk = {
        str(item["chunk_id"]): item
        for item in context.get("official_evidences", [])
        if isinstance(item, dict) and item.get("chunk_id")
    }
    raw_ids = requested_chunk_ids if isinstance(requested_chunk_ids, list) else []
    accepted: list[str] = []
    warnings: list[str] = []
    for value in raw_ids:
        chunk_id = str(value).strip()
        if not chunk_id:
            continue
        if chunk_id not in evidence_by_chunk:
            warnings.append(f"unknown_evidence_chunk_id:{chunk_id}")
            continue
        if chunk_id not in accepted:
            accepted.append(chunk_id)
    cited = [evidence_by_chunk[chunk_id] for chunk_id in accepted]
    return {
        "evidence_status": context.get("evidence_status"),
        "evidence_used": bool(accepted),
        "evidence_chunk_ids": accepted,
        "evidence_document_ids": _stable_unique(str(item["document_id"]) for item in cited),
        "evidence_urls": _stable_unique(str(item["canonical_url"]) for item in cited),
        "evidence_limitations": list(context.get("evidence_limitations") or []),
        "retrieval_status": context.get("retrieval_status"),
        "evidence_warnings": warnings,
        "evidence_network_request_count": int(context.get("network_request_count") or 0),
    }


def _limitations(
    result: OfficialEvidenceRetrievalResult, selected: list[dict[str, Any]]
) -> list[str]:
    limitations: list[str] = []
    if result.status not in {"success", "partial_success"}:
        limitations.append(f"retrieval_status:{result.status}")
    if result.document_failures:
        limitations.append("document_processing_failures_present")
    if any(item["text_truncated"] for item in selected):
        limitations.append("evidence_text_truncated")
    if not selected:
        limitations.append("no_official_evidence_chunks")
    return limitations


def _evidence_status(retrieval_status: str, has_evidence: bool) -> str:
    if has_evidence and retrieval_status == "success":
        return "official_evidence_available"
    if has_evidence and retrieval_status == "partial_success":
        return "official_evidence_partial"
    if retrieval_status == "no_chunk_match":
        return "insufficient_official_evidence"
    return "official_evidence_unavailable"


def _stable_unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
