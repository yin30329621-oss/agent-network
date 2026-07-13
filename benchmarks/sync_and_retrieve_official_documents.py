"""Explicit opt-in acceptance flow for multi-document official evidence retrieval."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from agent_network.evidence.cached_official_evidence import (
    CachedEvidenceIndexBuilder,
    CachedEvidenceRetrievalRequest,
)
from agent_network.evidence.catalog import DocumentCatalogQuery, DocumentCatalogRepository
from agent_network.evidence.document_cleaner import OfficialDocumentCleaner
from agent_network.evidence.document_fetcher import HttpOfficialDocumentFetcher
from agent_network.evidence.official_document_synchronizer import (
    DEFAULT_CACHE_DIRECTORY,
    OfficialDocumentSynchronizer,
    OfficialDocumentSyncRequest,
)
from agent_network.evidence.schemas import DocumentCatalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_CATALOG_PATH = (
    PROJECT_ROOT / "benchmarks" / "fixtures" / "document-sync-retrieve-live-v1" / "catalog.json"
)
MAX_ACCEPTANCE_DOCUMENTS = 4
MAX_FETCHER_REDIRECTS = 3


class SyncRetrieveSafetyError(RuntimeError):
    """Raised before an unconfirmed benchmark action can access the network."""


@dataclass(frozen=True, slots=True)
class SyncRetrievePlan:
    selected_document_ids: list[str]
    selected_document_count: int
    canonical_urls: list[str]
    products: list[str]
    components: list[list[str]]
    cache_directory: str | None
    force_refresh: bool
    allow_network: bool
    planned_max_network_requests: int
    query_text: str
    top_chunks: int
    max_chunks_per_document: int
    min_documents_in_results: int
    live_sync_enabled: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_sync_retrieve_catalog(path: Path = LIVE_CATALOG_PATH) -> DocumentCatalogRepository:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Sync/retrieve catalog could not be loaded") from exc
    if not isinstance(records, list):
        raise ValueError("Sync/retrieve catalog must be a JSON list")
    documents = [DocumentCatalog.model_validate(record) for record in records]
    return DocumentCatalogRepository(
        documents, allowed_domains={document.official_domain for document in documents}
    )


def build_plan(
    repository: DocumentCatalogRepository,
    *,
    document_ids: tuple[str, ...] | None,
    product: str | None,
    component: str | None,
    max_documents: int,
    cache_directory: str | None,
    force_refresh: bool,
    allow_network: bool,
    query_text: str,
    top_chunks: int,
    max_chunks_per_document: int,
    min_documents_in_results: int,
    live_sync_enabled: bool,
) -> SyncRetrievePlan:
    if max_documents <= 0 or max_documents > MAX_ACCEPTANCE_DOCUMENTS:
        raise SyncRetrieveSafetyError("max_documents must be between 1 and 4")
    if top_chunks <= 0 or max_chunks_per_document < 0 or min_documents_in_results <= 0:
        raise SyncRetrieveSafetyError("Retrieval limits are invalid")
    _validate_cache_directory(cache_directory)
    candidates = repository.query(DocumentCatalogQuery(product=product, component=component))
    selected = _select_documents(candidates, document_ids, max_documents)
    return SyncRetrievePlan(
        selected_document_ids=[document.document_id for document in selected],
        selected_document_count=len(selected),
        canonical_urls=[document.canonical_url for document in selected],
        products=[document.product for document in selected],
        components=[list(document.components) for document in selected],
        cache_directory=_display_cache_directory(cache_directory),
        force_refresh=force_refresh,
        allow_network=allow_network,
        planned_max_network_requests=len(selected) * (MAX_FETCHER_REDIRECTS + 1),
        query_text=query_text,
        top_chunks=top_chunks,
        max_chunks_per_document=max_chunks_per_document,
        min_documents_in_results=min_documents_in_results,
        live_sync_enabled=live_sync_enabled,
    )


def run_live_sync_and_retrieve(
    synchronizer: OfficialDocumentSynchronizer,
    plan: SyncRetrievePlan,
    *,
    confirmed_document_count: int | None,
    min_score: float,
    min_matched_terms: int,
    exclude_navigation_like: bool,
) -> dict[str, object]:
    _require_live_confirmation(plan, confirmed_document_count)
    _prepare_cache_directory(synchronizer.cache_root, plan.cache_directory)
    sync_results = []
    for document_id in plan.selected_document_ids:
        sync_results.append(
            synchronizer.sync(
                OfficialDocumentSyncRequest(
                    document_id=document_id,
                    max_documents=1,
                    force_refresh=plan.force_refresh,
                    allow_network=True,
                    cache_directory=_relative_cache_directory(plan.cache_directory),
                )
            )
        )
    sync_summary = _sync_summary(sync_results, plan)
    retrieval = CachedEvidenceIndexBuilder(cache_root=synchronizer.cache_root).retrieve(
        CachedEvidenceRetrievalRequest(
            cache_directory=_relative_cache_directory(plan.cache_directory),
            document_ids=tuple(plan.selected_document_ids),
            max_documents=plan.selected_document_count,
            query_text=plan.query_text,
            top_chunks=plan.top_chunks,
            min_score=min_score,
            min_matched_terms=min_matched_terms,
            exclude_navigation_like=exclude_navigation_like,
            max_chunks_per_document=plan.max_chunks_per_document,
            min_documents_in_results=plan.min_documents_in_results,
        )
    )
    retrieval_summary = retrieval.to_dict()
    safe_errors = _safe_errors(sync_summary["records"], retrieval_summary["cache_failures"])
    return {
        "sync_summary": sync_summary,
        "retrieval_summary": retrieval_summary,
        "overall": {
            "total_network_request_count": sync_summary["network_request_count"],
            "model_call_count": 0,
            "completed": True,
            "safe_errors": safe_errors,
        },
    }


def _select_documents(
    candidates: list[DocumentCatalog], document_ids: tuple[str, ...] | None, max_documents: int
) -> list[DocumentCatalog]:
    if document_ids is None:
        return candidates[:max_documents]
    by_id = {document.document_id: document for document in candidates}
    selected: list[DocumentCatalog] = []
    for document_id in dict.fromkeys(document_ids):
        document = by_id.get(document_id)
        if document is None:
            raise SyncRetrieveSafetyError(
                "document_id is not registered in the sync/retrieve catalog"
            )
        selected.append(document)
        if len(selected) == max_documents:
            break
    return selected


def _sync_summary(results: list[Any], plan: SyncRetrievePlan) -> dict[str, object]:
    records = [record for result in results for record in result.records]
    return {
        "catalog_match_count": plan.selected_document_count,
        "selected_document_count": plan.selected_document_count,
        "fetched_count": sum(record.sync_status == "fetched" for record in records),
        "unchanged_count": sum(record.sync_status == "unchanged" for record in records),
        "skipped_count": sum(record.sync_status == "skipped" for record in records),
        "failed_count": sum(record.sync_status == "failed" for record in records),
        "network_request_count": sum(record.network_request_count for record in records),
        "records": [record.to_dict() for record in records],
    }


def _safe_errors(
    records: list[Any], cache_failures: list[dict[str, object]]
) -> list[dict[str, str]]:
    errors = [
        {
            "document_id": record["document_id"],
            "stage": str(record.get("error_stage") or "sync"),
            "error_code": str(record.get("error_code") or "sync_failed"),
            "safe_message": str(record.get("safe_message") or "Document sync failed"),
        }
        for record in records
        if record.get("error_code")
    ]
    errors.extend(
        {
            "document_id": str(failure["document_id"]),
            "stage": str(failure.get("stage") or "load"),
            "error_code": str(failure["error_code"]),
            "safe_message": str(failure["safe_message"]),
        }
        for failure in cache_failures
    )
    return errors


def _require_live_confirmation(
    plan: SyncRetrievePlan, confirmed_document_count: int | None
) -> None:
    if not plan.live_sync_enabled:
        raise SyncRetrieveSafetyError("Live sync requires --run-live")
    if not plan.allow_network:
        raise SyncRetrieveSafetyError("Live sync requires --allow-network")
    if plan.cache_directory is None:
        raise SyncRetrieveSafetyError("Live sync requires an explicit --cache-directory")
    if not plan.query_text.strip():
        raise SyncRetrieveSafetyError("Live sync/retrieve requires --query")
    if confirmed_document_count != plan.selected_document_count:
        raise SyncRetrieveSafetyError("Planned document count was not explicitly confirmed")


def _validate_cache_directory(value: str | None) -> None:
    if value is None:
        return
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise SyncRetrieveSafetyError(
            "cache-directory must stay below data/official-evidence-cache"
        )


def _display_cache_directory(value: str | None) -> str | None:
    return None if value is None else str(DEFAULT_CACHE_DIRECTORY / value)


def _relative_cache_directory(value: str | None) -> str | None:
    if value is None:
        return None
    return str(Path(value).relative_to(DEFAULT_CACHE_DIRECTORY))


def _prepare_cache_directory(cache_root: Path, value: str | None) -> None:
    relative = _relative_cache_directory(value)
    if relative is None:
        raise SyncRetrieveSafetyError("Live sync requires an explicit --cache-directory")
    target = (cache_root / relative).resolve()
    try:
        target.relative_to(cache_root.resolve())
    except ValueError as exc:
        raise SyncRetrieveSafetyError("cache-directory escapes the configured cache root") from exc
    target.mkdir(parents=True, exist_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe opt-in multi-document sync and retrieval")
    parser.add_argument("--plan", action="store_true", help="Print the offline plan (default).")
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--confirm-planned-document-count", type=int)
    parser.add_argument("--document-id", action="append")
    parser.add_argument("--product")
    parser.add_argument("--component")
    parser.add_argument("--max-documents", type=int, default=1)
    parser.add_argument("--cache-directory")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--query", default="")
    parser.add_argument("--top-chunks", type=int, default=6)
    parser.add_argument("--max-chunks-per-document", type=int, default=2)
    parser.add_argument("--min-documents-in-results", type=int, default=2)
    parser.add_argument("--min-score", type=float, default=1.0)
    parser.add_argument("--min-matched-terms", type=int, default=2)
    parser.add_argument(
        "--exclude-navigation-like", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--include-filtered-summary", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repository = load_sync_retrieve_catalog()
    plan = build_plan(
        repository,
        document_ids=tuple(args.document_id) if args.document_id else None,
        product=args.product,
        component=args.component,
        max_documents=args.max_documents,
        cache_directory=args.cache_directory,
        force_refresh=args.force_refresh,
        allow_network=args.allow_network,
        query_text=args.query,
        top_chunks=args.top_chunks,
        max_chunks_per_document=args.max_chunks_per_document,
        min_documents_in_results=args.min_documents_in_results,
        live_sync_enabled=args.run_live,
    )
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    if not args.run_live:
        return 0
    _require_live_confirmation(plan, args.confirm_planned_document_count)
    fetcher = HttpOfficialDocumentFetcher(
        allowed_domains={document.official_domain for document in repository.query()}
    )
    synchronizer = OfficialDocumentSynchronizer(repository, fetcher, OfficialDocumentCleaner())
    result = run_live_sync_and_retrieve(
        synchronizer,
        plan,
        confirmed_document_count=args.confirm_planned_document_count,
        min_score=args.min_score,
        min_matched_terms=args.min_matched_terms,
        exclude_navigation_like=args.exclude_navigation_like,
    )
    if not args.include_filtered_summary:
        result["retrieval_summary"].pop("filtered_evidence_count", None)
        result["retrieval_summary"].pop("filtered_reasons_summary", None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
