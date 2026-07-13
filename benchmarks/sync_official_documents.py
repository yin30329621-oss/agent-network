"""Explicit opt-in, small-scale acceptance entry for official document sync."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

from agent_network.evidence.catalog import DocumentCatalogQuery, DocumentCatalogRepository
from agent_network.evidence.document_cleaner import OfficialDocumentCleaner
from agent_network.evidence.document_fetcher import HttpOfficialDocumentFetcher
from agent_network.evidence.official_document_synchronizer import (
    DEFAULT_CACHE_DIRECTORY,
    DocumentSyncError,
    OfficialDocumentCache,
    OfficialDocumentSynchronizer,
    OfficialDocumentSyncRequest,
)
from agent_network.evidence.schemas import DocumentCatalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_CATALOG_PATH = (
    PROJECT_ROOT / "benchmarks" / "fixtures" / "document-sync-live-v1" / "catalog.json"
)
MAX_ACCEPTANCE_DOCUMENTS = 2
MAX_FETCHER_REDIRECTS = 3


class SyncBenchmarkSafetyError(RuntimeError):
    """Raised before an unconfirmed benchmark sync can access the network."""


@dataclass(frozen=True, slots=True)
class SyncBenchmarkPlan:
    selected_document_ids: list[str]
    selected_document_count: int
    canonical_urls: list[str]
    documents: list[dict[str, str | list[str]]]
    allow_network: bool
    force_refresh: bool
    cache_directory: str | None
    planned_max_network_requests: int
    live_sync_enabled: bool
    confirmed_document_count: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def load_live_catalog(path: Path = LIVE_CATALOG_PATH) -> DocumentCatalogRepository:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Live sync catalog could not be loaded") from exc
    if not isinstance(records, list):
        raise ValueError("Live sync catalog must be a JSON list")
    documents = [DocumentCatalog.model_validate(record) for record in records]
    return DocumentCatalogRepository(
        documents, allowed_domains={item.official_domain for item in documents}
    )


def build_plan(
    repository: DocumentCatalogRepository,
    request: OfficialDocumentSyncRequest,
    *,
    live_sync_enabled: bool,
    confirmed_document_count: int | None = None,
) -> SyncBenchmarkPlan:
    if request.max_documents <= 0 or request.max_documents > MAX_ACCEPTANCE_DOCUMENTS:
        raise SyncBenchmarkSafetyError("max_documents must be between 1 and 2")
    _validate_cache_directory(request.cache_directory)
    candidates = repository.query(
        DocumentCatalogQuery(
            product=request.product,
            component=request.component,
            official_domain=request.official_domain,
        )
    )
    if request.document_id is not None:
        candidates = [item for item in candidates if item.document_id == request.document_id]
        if not candidates:
            raise SyncBenchmarkSafetyError("document_id is not registered in the live sync catalog")
    selected = candidates[: request.max_documents]
    return SyncBenchmarkPlan(
        selected_document_ids=[item.document_id for item in selected],
        selected_document_count=len(selected),
        canonical_urls=[item.canonical_url for item in selected],
        documents=[
            {
                "document_id": item.document_id,
                "product": item.product,
                "component": list(item.components),
            }
            for item in selected
        ],
        allow_network=request.allow_network,
        force_refresh=request.force_refresh,
        cache_directory=_display_cache_directory(request.cache_directory),
        planned_max_network_requests=len(selected) * (MAX_FETCHER_REDIRECTS + 1),
        live_sync_enabled=live_sync_enabled,
        confirmed_document_count=confirmed_document_count,
    )


def inspect_cache(
    cache_directory: str, document_ids: list[str], *, cache_root: Path = DEFAULT_CACHE_DIRECTORY
) -> list[dict[str, object]]:
    """Read and validate cache artifacts without exposing their document bodies."""
    cache = OfficialDocumentCache(cache_root / cache_directory)
    checks: list[dict[str, object]] = []
    for document_id in document_ids:
        document_dir = cache.documents_root / document_id
        raw_path = document_dir / "raw.html"
        cleaned_path = document_dir / "cleaned.json"
        try:
            metadata = cache.metadata(document_id)
            cleaned = json.loads(cleaned_path.read_text(encoding="utf-8"))
            valid = bool(
                metadata
                and raw_path.is_file()
                and raw_path.stat().st_size > 0
                and isinstance(cleaned, dict)
                and metadata.get("document_id") == document_id
                and metadata.get("canonical_url")
                and len(str(metadata.get("raw_content_sha256") or "")) == 64
                and len(str(metadata.get("cleaned_content_sha256") or "")) == 64
            )
            checks.append(
                {
                    "document_id": document_id,
                    "cache_valid": valid,
                    "final_url": metadata.get("final_url") if metadata else None,
                }
            )
        except (DocumentSyncError, OSError, json.JSONDecodeError):
            checks.append({"document_id": document_id, "cache_valid": False, "final_url": None})
    return checks


def run_live_sync(
    synchronizer: OfficialDocumentSynchronizer,
    request: OfficialDocumentSyncRequest,
    plan: SyncBenchmarkPlan,
) -> dict[str, object]:
    _require_live_confirmation(request, plan)
    result = synchronizer.sync(request)
    output = result.to_dict()
    checks = inspect_cache(
        request.cache_directory or "",
        plan.selected_document_ids,
        cache_root=synchronizer.cache_root,
    )
    final_urls = {item["document_id"]: item["final_url"] for item in checks}
    output["records"] = [
        {
            "document_id": record.document_id,
            "sync_status": record.sync_status,
            "canonical_url": record.canonical_url,
            "final_url": final_urls.get(record.document_id),
            "error_stage": record.error_stage,
            "error_code": record.error_code,
            "safe_message": record.safe_message,
        }
        for record in result.records
    ]
    output["cache_checks"] = checks
    return output


def _request_from_args(args: argparse.Namespace) -> OfficialDocumentSyncRequest:
    return OfficialDocumentSyncRequest(
        product=args.product,
        component=args.component,
        document_id=args.document_id,
        official_domain=args.official_domain,
        max_documents=args.max_documents,
        force_refresh=args.force_refresh,
        allow_network=args.allow_network,
        cache_directory=args.cache_directory,
    )


def _require_live_confirmation(
    request: OfficialDocumentSyncRequest, plan: SyncBenchmarkPlan
) -> None:
    if not request.allow_network:
        raise SyncBenchmarkSafetyError("Live sync requires --allow-network")
    if request.cache_directory is None:
        raise SyncBenchmarkSafetyError("Live sync requires an explicit --cache-directory")
    if not plan.live_sync_enabled:
        raise SyncBenchmarkSafetyError("Live sync requires --run-live")
    if plan.confirmed_document_count != plan.selected_document_count:
        raise SyncBenchmarkSafetyError("Planned document count was not explicitly confirmed")


def _validate_cache_directory(value: str | None) -> None:
    if value is None:
        return
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise SyncBenchmarkSafetyError(
            "cache-directory must stay below data/official-evidence-cache"
        )


def _display_cache_directory(value: str | None) -> str | None:
    if value is None:
        return None
    return str(DEFAULT_CACHE_DIRECTORY / value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safe, opt-in official document sync acceptance benchmark"
    )
    parser.add_argument("--plan", action="store_true", help="Print the offline plan (default).")
    parser.add_argument(
        "--run-live", action="store_true", help="Run the explicitly confirmed sync."
    )
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--confirm-planned-document-count", type=int)
    parser.add_argument("--document-id")
    parser.add_argument("--product")
    parser.add_argument("--component")
    parser.add_argument("--official-domain")
    parser.add_argument("--max-documents", type=int, default=1)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--cache-directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    request = _request_from_args(args)
    repository = load_live_catalog()
    plan = build_plan(
        repository,
        request,
        live_sync_enabled=args.run_live,
        confirmed_document_count=args.confirm_planned_document_count,
    )
    plan_payload = plan.to_dict()
    plan_payload["confirmed_document_count"] = args.confirm_planned_document_count
    print(json.dumps(plan_payload, ensure_ascii=False, indent=2))
    if not args.run_live:
        return 0
    _require_live_confirmation(request, plan)
    fetcher = HttpOfficialDocumentFetcher(
        allowed_domains={item.official_domain for item in repository.query()}
    )
    synchronizer = OfficialDocumentSynchronizer(repository, fetcher, OfficialDocumentCleaner())
    print(json.dumps(run_live_sync(synchronizer, request, plan), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
