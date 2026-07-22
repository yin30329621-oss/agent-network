#!/usr/bin/env python3
"""Case-local preflight runner for the Rancher live validation.

This runner intentionally supports only the deterministic preflight path for
now.  It never creates an LLM client and never executes reviewer agents.
The eventual live path can reuse the plan emitted here without changing the
core Agent Network workflow.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_network.claim import ClaimExtractionRequest, DeterministicClaimExtractor
from agent_network.evidence.document_chunker import DocumentChunk
from agent_network.evidence.offline_retrieval import OfflineBm25EvidenceRetriever


LIVE_CASE = Path(__file__).resolve().parent
SOURCE_CASE = ROOT / "cases" / "rancher-security-review-v1"
INPUT_PATH = LIVE_CASE / "input.md"
CHUNKS_PATH = SOURCE_CASE / "evidence" / "chunks.json"

TARGET_TYPES = (
    "cluster_agent",
    "reverse_tunnel",
    "serviceaccount_token",
    "kubernetes_rbac",
    "cloud_credential",
    "cve_security",
)

KEYWORDS: dict[str, tuple[str, ...]] = {
    "cluster_agent": ("cluster agent", "cattle-cluster-agent", "cluster-agent"),
    "reverse_tunnel": ("reverse tunnel", "remotedialer", "websocket", "tunnel"),
    "serviceaccount_token": ("serviceaccount", "service account", "serviceaccount token"),
    "kubernetes_rbac": ("rbac", "rolebinding", "clusterrole", "authorization"),
    "cloud_credential": ("cloud credential", "cloud credentials", "credential"),
    "cve_security": ("cve-", "security vulnerability", "security advisory"),
}


def _claim_types(claim: Any) -> list[str]:
    text = " ".join(
        str(value or "")
        for value in (
            getattr(claim, "text", ""),
            getattr(claim, "normalized_text", ""),
            getattr(claim, "section", ""),
        )
    ).lower()
    matches = [
        claim_type
        for claim_type, words in KEYWORDS.items()
        if any(word in text for word in words)
    ]
    normalized_type = str(getattr(claim, "claim_type", "")).lower()
    aliases = {
        "architecture_behavior": "cluster_agent",
        "communication_flow": "reverse_tunnel",
        "authentication": "serviceaccount_token",
        "authorization": "kubernetes_rbac",
        "credential_storage": "cloud_credential",
        "token_lifecycle": "serviceaccount_token",
        "cve_existence": "cve_security",
        "cve_affected_version": "cve_security",
        "cve_fixed_version": "cve_security",
        "cvss": "cve_security",
    }
    alias = aliases.get(normalized_type)
    if alias and alias not in matches:
        matches.append(alias)
    return matches


def _select_claims(claims: list[Any], limit: int = 30) -> list[Any]:
    """Select high-value claims deterministically, preserving extraction order."""
    ranked: list[tuple[int, int, Any]] = []
    for index, claim in enumerate(claims):
        types = _claim_types(claim)
        if not types:
            continue
        priority = 0 if getattr(claim, "priority", "medium") in {"critical", "high"} else 1
        ranked.append((priority, index, claim))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected: list[Any] = []
    selected_ids: set[str] = set()
    for target_type in TARGET_TYPES:
        for _, _, claim in ranked:
            if claim.claim_id in selected_ids:
                continue
            if target_type in _claim_types(claim):
                selected.append(claim)
                selected_ids.add(claim.claim_id)
                break
    for _, _, claim in ranked:
        if len(selected) >= limit:
            break
        if claim.claim_id not in selected_ids:
            selected.append(claim)
            selected_ids.add(claim.claim_id)
    return sorted(selected, key=lambda claim: claims.index(claim))


def _load_chunks(path: Path) -> list[DocumentChunk]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_chunks = payload.get("chunks", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_chunks, list):
        raise ValueError("chunks.json must contain a list or a {chunks: [...]} object")
    now = datetime.now(UTC)
    chunks: list[DocumentChunk] = []
    for raw in raw_chunks:
        if not isinstance(raw, dict):
            raise ValueError("each evidence chunk must be an object")
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        chunks.append(
            DocumentChunk(
                chunk_id=str(raw["chunk_id"]),
                document_id=str(raw.get("document_id") or raw["document_path"]),
                canonical_url=str(raw.get("canonical_url", "https://example.invalid")),
                final_url=str(raw.get("canonical_url", "https://example.invalid")),
                product="rancher",
                component=str(raw.get("section") or "evidence"),
                document_type="reference",
                document_title=str(raw.get("title") or raw.get("document_id") or ""),
                section_heading=str(raw.get("section") or ""),
                section_heading_level=1,
                section_order=0,
                chunk_order=0,
                text=text,
                character_count=len(text),
                source_fetched_at=now,
                heading_path=list(raw.get("heading_path", [])),
            )
        )
    return chunks


def build_preflight(*, batch_size: int = 5, claim_limit: int = 30) -> dict[str, Any]:
    extraction = DeterministicClaimExtractor().extract(
        ClaimExtractionRequest(
            document_text=INPUT_PATH.read_text(encoding="utf-8"),
            source_name=INPUT_PATH.name,
        )
    )
    selected = _select_claims(extraction.claims, limit=claim_limit)
    chunks = _load_chunks(CHUNKS_PATH)
    retriever = OfflineBm25EvidenceRetriever(chunks)
    retrieval_hits = [retriever.retrieve(claim, top_k=5) for claim in selected]
    reviewer_batches = math.ceil(len(selected) / batch_size) if selected else 0
    model_names = {
        "fact_a": "configured at live execution time",
        "fact_b": "configured at live execution time",
        "security": "configured at live execution time",
        "logic": "configured at live execution time",
        "merge": "configured at live execution time",
    }
    return {
        "mode": "dry_run",
        "generated_at": datetime.now(UTC).isoformat(),
        "input_file": str(INPUT_PATH),
        "evidence_file": str(CHUNKS_PATH),
        "extraction": {
            "candidate_count": extraction.candidate_count,
            "extracted_count": len(extraction.claims),
            "selected_count": len(selected),
            "target_claim_types": list(TARGET_TYPES),
            "selected_claim_ids": [claim.claim_id for claim in selected],
        },
        "evidence": {
            "chunk_count": len(chunks),
            "retrieval_claim_count": len(retrieval_hits),
            "claims_with_hits": sum(bool(result.results) for result in retrieval_hits),
            "top_k": 5,
            "network_request_count": retriever.network_request_count,
            "model_call_count": retriever.model_call_count,
        },
        "budget": {
            "batch_size": batch_size,
            "fact_a_calls": reviewer_batches,
            "fact_b_calls": reviewer_batches,
            "security_calls": 1 if selected else 0,
            "logic_calls": 1 if selected else 0,
            "merge_calls": 1 if selected else 0,
            "estimated_total_model_calls": reviewer_batches * 2 + (3 if selected else 0),
        },
        "models": model_names,
        "claim_type_distribution": {
            claim_type: sum(claim_type in _claim_types(claim) for claim in selected)
            for claim_type in TARGET_TYPES
        },
        "artifacts": [
            "claims.json",
            "evidence-retrieval.json",
            "fact-review.json",
            "security-review.json",
            "logic-review.json",
            "merge-result.json",
            "final-review-report.md",
            "run-metadata.json",
        ],
        "live_execution": {
            "executed": False,
            "reason": "Preflight only; reviewer agents are not invoked by this runner yet.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--claim-limit", type=int, default=30)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run deterministic extraction/retrieval preflight only (default).",
    )
    args = parser.parse_args()
    if args.batch_size < 1 or args.claim_limit < 1:
        parser.error("--batch-size and --claim-limit must be positive")
    if not args.dry_run:
        parser.error("only --dry-run is supported; live reviewer execution is disabled")
    print(json.dumps(build_preflight(batch_size=args.batch_size, claim_limit=args.claim_limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
