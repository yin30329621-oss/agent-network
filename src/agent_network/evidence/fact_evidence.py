"""Bounded, auditable Fact Agent context derived from official retrieval results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_network.evidence.official_evidence_retriever import OfficialEvidenceRetrievalResult
from agent_network.language import is_chinese_language
from agent_network.schemas import EvidenceRelation


_RELATIONS = frozenset(item.value for item in EvidenceRelation)


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
    result: OfficialEvidenceRetrievalResult, limits: FactEvidenceLimits, *, language: str = "en"
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
    limitations = _limitations(result, selected, language)
    return {
        "claim_id": None,
        "claim_text": result.query_text,
        "retrieval_status": result.status,
        "language": language,
        "evidence_status": _evidence_status(result.status, bool(selected)),
        "evidence_count": len(selected),
        "evidence_relation": _fallback_relation(result.status, bool(selected), bool(selected)),
        "official_evidences": selected,
        "document_failures": [failure.to_dict() for failure in result.document_failures],
        "network_request_count": result.network_request_count,
        "evidence_limitations": limitations,
    }


def unavailable_fact_evidence_context(error_code: str, *, language: str = "en") -> dict[str, Any]:
    """Create a safe degraded context when retrieval cannot run."""

    return {
        "claim_id": None,
        "claim_text": "",
        "retrieval_status": "retrieval_error",
        "language": language,
        "evidence_status": "official_evidence_unavailable",
        "evidence_count": 0,
        "evidence_relation": EvidenceRelation.UNAVAILABLE.value,
        "official_evidences": [],
        "document_failures": [],
        "network_request_count": 0,
        "evidence_limitations": _stable_unique(
            [f"retrieval_error:{error_code}", _limitation("retrieval_error", language)]
        ),
    }


def validate_fact_evidence_citations(
    requested_chunk_ids: object,
    context: dict[str, Any],
    *,
    requested_relation: object = None,
    requested_limitations: object = None,
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
    relation, relation_warning = _validated_relation(
        requested_relation,
        retrieval_status=str(context.get("retrieval_status") or ""),
        evidence_count=int(context.get("evidence_count") or 0),
        has_verified_citation=bool(accepted),
    )
    if relation_warning:
        warnings.append(relation_warning)
    model_limitations = (
        [str(value).strip() for value in requested_limitations if str(value).strip()]
        if isinstance(requested_limitations, list)
        else []
    )
    relation_limitations = (
        [_limitation(relation, str(context.get("language") or "en"))]
        if relation
        in {
            EvidenceRelation.ABSENCE_OF_SUPPORT.value,
            EvidenceRelation.INDIRECT_EVIDENCE.value,
        }
        else []
    )
    return {
        "evidence_status": context.get("evidence_status"),
        "evidence_used": bool(accepted),
        "evidence_chunk_ids": accepted,
        "evidence_document_ids": _stable_unique(str(item["document_id"]) for item in cited),
        "evidence_urls": _stable_unique(str(item["canonical_url"]) for item in cited),
        "evidence_relation": relation,
        "evidence_limitations": _stable_unique(
            [
                *(context.get("evidence_limitations") or []),
                *relation_limitations,
                *model_limitations,
            ]
        ),
        "retrieval_status": context.get("retrieval_status"),
        "evidence_warnings": warnings,
        "evidence_network_request_count": int(context.get("network_request_count") or 0),
    }


def _limitations(
    result: OfficialEvidenceRetrievalResult, selected: list[dict[str, Any]], language: str
) -> list[str]:
    limitations: list[str] = []
    if result.status not in {"success", "partial_success"}:
        limitations.append(f"retrieval_status:{result.status}")
    if result.status == "no_catalog_match":
        limitations.append(_limitation("no_catalog_match", language))
    elif result.status == "no_chunk_match":
        limitations.append(_limitation("no_chunk_match", language))
    elif result.status == "all_documents_failed":
        limitations.append(_limitation("all_documents_failed", language))
    if result.document_failures:
        limitations.append("document_processing_failures_present")
        limitations.append(_limitation("partial_success", language))
    if any(item["text_truncated"] for item in selected):
        limitations.append("evidence_text_truncated")
    if not selected:
        limitations.append("no_official_evidence_chunks")
    return _stable_unique(limitations)


def _evidence_status(retrieval_status: str, has_evidence: bool) -> str:
    if has_evidence and retrieval_status == "success":
        return "official_evidence_available"
    if has_evidence and retrieval_status == "partial_success":
        return "official_evidence_partial"
    if retrieval_status == "no_chunk_match":
        return "insufficient_official_evidence"
    return "official_evidence_unavailable"


def _validated_relation(
    requested_relation: object,
    *,
    retrieval_status: str,
    evidence_count: int,
    has_verified_citation: bool,
) -> tuple[str, str | None]:
    fallback = _fallback_relation(retrieval_status, evidence_count > 0, has_verified_citation)
    if requested_relation is None or not str(requested_relation).strip():
        return fallback, None
    relation = str(requested_relation).strip().lower()
    if relation not in _RELATIONS:
        return fallback, f"invalid_evidence_relation:{relation}"
    if retrieval_status in {"no_catalog_match", "all_documents_failed", "retrieval_error"}:
        return EvidenceRelation.UNAVAILABLE.value, None
    if retrieval_status == "no_chunk_match":
        return EvidenceRelation.ABSENCE_OF_SUPPORT.value, None
    if relation in {
        EvidenceRelation.DIRECT_SUPPORT.value,
        EvidenceRelation.DIRECT_CONTRADICTION.value,
    } and (evidence_count == 0 or not has_verified_citation):
        return fallback, "evidence_relation_requires_verified_chunk"
    return relation, None


def _fallback_relation(
    retrieval_status: str, has_evidence: bool, has_verified_citation: bool
) -> str:
    if retrieval_status in {"no_catalog_match", "all_documents_failed", "retrieval_error"}:
        return EvidenceRelation.UNAVAILABLE.value
    if retrieval_status == "no_chunk_match" or not has_evidence:
        return EvidenceRelation.ABSENCE_OF_SUPPORT.value
    if not has_verified_citation:
        return EvidenceRelation.INDIRECT_EVIDENCE.value
    return EvidenceRelation.INDIRECT_EVIDENCE.value


def _limitation(kind: str, language: str) -> str:
    chinese = is_chinese_language(language)
    messages = {
        "absence_of_support": (
            "提供的官方证据未陈述或保证该项主张。"
            if chinese
            else "Provided official evidence does not state or guarantee this claim."
        ),
        "indirect_evidence": (
            "提供的证据与该主张相关，但不能直接证明该主张。"
            if chinese
            else "Provided evidence is related but does not directly establish the claim."
        ),
        "partial_success": (
            "部分官方文档处理失败。"
            if chinese
            else "Some official documents could not be processed."
        ),
        "no_catalog_match": "未找到匹配的官方文档。"
        if chinese
        else "No matching official document was found.",
        "no_chunk_match": (
            "候选官方文档中未找到相关正文片段。"
            if chinese
            else "Candidate official documents contained no relevant evidence chunk."
        ),
        "all_documents_failed": "官方证据处理失败。"
        if chinese
        else "Official evidence processing failed.",
        "retrieval_error": "官方证据检索失败。"
        if chinese
        else "Official evidence retrieval failed.",
    }
    return messages[kind]


def _stable_unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
