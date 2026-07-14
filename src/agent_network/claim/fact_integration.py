"""Bounded Claim Verification context for one Fact Agent call."""

from __future__ import annotations

from typing import Any

from agent_network.claim.engine import ClaimVerificationBatchResult
from agent_network.evidence.fact_evidence import FactEvidenceLimits
from agent_network.language import is_chinese_language


def build_claim_verification_fact_context(
    result: ClaimVerificationBatchResult,
    limits: FactEvidenceLimits,
    *,
    cache_directory: str | None,
    language: str = "en",
) -> dict[str, Any]:
    """Build one bounded, citation-safe Fact context from ordered claim results."""

    evidences = _bounded_evidences(result, limits)
    failures = [failure.model_dump() for failure in result.failures]
    bundle = []
    for item in result.results:
        verification = item.verification
        bundle.append(
            {
                "claim_id": verification.claim_id,
                "claim_text": verification.claim_text,
                "normalized_text": verification.normalized_text,
                "claim_type": verification.claim_type,
                "verification_status": verification.verification_status.value,
                "evidence_relation": verification.evidence_relation.value,
                "evidence_link_ids": [link.evidence_id for link in verification.evidence_links],
                "evidence_chunk_ids": [link.chunk_id for link in verification.evidence_links],
                "evidence_links": [
                    {
                        "evidence_id": link.evidence_id,
                        "chunk_id": link.chunk_id,
                        "document_id": link.document_id,
                        "canonical_url": link.canonical_url,
                        "relation": link.relation.value,
                    }
                    for link in verification.evidence_links
                ],
                "evidence_limitations": list(verification.evidence_limitations),
                "limitations": list(verification.limitations),
                "query_text": verification.query_text,
                "applied_filters": dict(verification.applied_filters),
            }
        )
    status_distribution = dict(result.status_distribution)
    limitations = _stable_unique(
        limitation for item in result.results for limitation in item.verification.limitations
    )
    if result.failed_claim_count:
        limitations.append(
            "部分 Claim 核验失败。"
            if is_chinese_language(language)
            else "Some Claim verifications failed."
        )
    return {
        "claim_id": None,
        "claim_text": "",
        "retrieval_status": "claim_verification",
        "language": language,
        "evidence_status": "official_evidence_available"
        if evidences
        else "insufficient_official_evidence",
        "evidence_count": len(evidences),
        "evidence_relation": "indirect_evidence" if evidences else "absence_of_support",
        "official_evidences": evidences,
        "document_failures": failures,
        "network_request_count": 0,
        "evidence_limitations": _stable_unique(limitations),
        "evidence_provider": "local_cache",
        "cache_directory": _safe_cache_directory(cache_directory),
        "selected_document_ids": _stable_unique(
            document_id
            for item in result.results
            for document_id in item.verification.applied_filters.get("document_ids") or []
        ),
        "loaded_document_count": sum(
            item.verification.loaded_document_count for item in result.results
        ),
        "failed_document_count": sum(
            item.verification.failed_document_count for item in result.results
        ),
        "returned_document_count": len({item["document_id"] for item in evidences}),
        "returned_evidence_count": len(evidences),
        "cache_failures": failures,
        "claim_verification_bundle": bundle,
        "claim_verification_mode": "candidate_only",
        "claim_verification_claim_count": result.total_claim_count,
        "claim_verification_completed_count": result.completed_claim_count,
        "claim_verification_failed_count": result.failed_claim_count,
        "claim_verification_status_distribution": status_distribution,
        "claim_verification_relation_distribution": dict(result.relation_distribution),
        "claim_verification_evidence_coverage_count": result.evidence_coverage_count,
        "claim_verification_unavailable_count": status_distribution.get("unavailable", 0),
        "claim_verification_insufficient_evidence_count": status_distribution.get(
            "insufficient_evidence", 0
        ),
        "claim_verification_extraction_failed_count": status_distribution.get(
            "extraction_failed", 0
        ),
        "claim_verification_model_call_count": result.model_call_count,
        "claim_verification_network_request_count": result.network_request_count,
    }


def _bounded_evidences(
    result: ClaimVerificationBatchResult, limits: FactEvidenceLimits
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    remaining = limits.max_total_evidence_chars
    for item in result.results:
        for evidence in item.candidate_evidences:
            chunk_id = str(evidence["chunk_id"])
            if len(selected) >= limits.top_k or chunk_id in seen or remaining <= 0:
                continue
            seen.add(chunk_id)
            text = str(evidence["text"])
            limit = min(limits.max_chars_per_evidence, remaining)
            truncated = text[:limit]
            selected.append(
                {
                    **evidence,
                    "text": truncated,
                    "text_truncated": len(truncated) < len(text),
                }
            )
            remaining -= len(truncated)
    return selected


def _safe_cache_directory(value: str | None) -> str | None:
    return value.replace("\\", "/") if value else None


def _stable_unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result
