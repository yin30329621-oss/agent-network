"""Read-only acceptance entry for evidence retrieval from official document cache."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json

from agent_network.evidence.cached_official_evidence import (
    CachedEvidenceIndexBuilder,
    CachedEvidenceRetrievalRequest,
)


@dataclass(frozen=True, slots=True)
class CacheRetrievalPlan:
    selected_cache_directory: str | None
    discovered_document_ids: list[str]
    selected_document_ids: list[str]
    selected_document_count: int
    query_text: str
    top_chunks: int
    min_score: float
    min_matched_terms: int
    exclude_navigation_like: bool
    network_request_count: int
    run_enabled: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_plan(
    builder: CachedEvidenceIndexBuilder, request: CachedEvidenceRetrievalRequest, *, run: bool
) -> CacheRetrievalPlan:
    loaded = builder.load(request)
    return CacheRetrievalPlan(
        selected_cache_directory=request.cache_directory,
        discovered_document_ids=loaded.discovered_document_ids,
        selected_document_ids=loaded.selected_document_ids,
        selected_document_count=len(loaded.selected_document_ids),
        query_text=request.query_text,
        top_chunks=request.top_chunks,
        min_score=request.min_score,
        min_matched_terms=request.min_matched_terms,
        exclude_navigation_like=request.exclude_navigation_like,
        network_request_count=0,
        run_enabled=run,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only official cache evidence retrieval")
    parser.add_argument("--plan", action="store_true", help="Print cache plan (default).")
    parser.add_argument(
        "--run", action="store_true", help="Build Chunk/BM25 from local cache only."
    )
    parser.add_argument("--cache-directory")
    parser.add_argument("--document-id")
    parser.add_argument("--product")
    parser.add_argument("--component")
    parser.add_argument("--document-type")
    parser.add_argument("--query", default="")
    parser.add_argument("--top-chunks", type=int, default=5)
    parser.add_argument("--max-documents", type=int, default=1)
    parser.add_argument("--min-score", type=float, default=1.0)
    parser.add_argument("--min-matched-terms", type=int, default=2)
    parser.add_argument(
        "--exclude-navigation-like",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exclude clearly marked table-of-contents chunks (default: enabled).",
    )
    parser.add_argument(
        "--include-filtered-summary",
        action="store_true",
        help="Include aggregate quality-filter reasons in run output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = CachedEvidenceRetrievalRequest(
        cache_directory=args.cache_directory,
        document_id=args.document_id,
        product=args.product,
        component=args.component,
        document_type=args.document_type,
        max_documents=args.max_documents,
        query_text=args.query,
        top_chunks=args.top_chunks,
        min_score=args.min_score,
        min_matched_terms=args.min_matched_terms,
        exclude_navigation_like=args.exclude_navigation_like,
    )
    builder = CachedEvidenceIndexBuilder()
    plan = build_plan(builder, request, run=args.run)
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    if not args.run:
        return 0
    result = builder.retrieve(request).to_dict()
    if not args.include_filtered_summary:
        result.pop("filtered_evidence_count", None)
        result.pop("filtered_reasons_summary", None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
