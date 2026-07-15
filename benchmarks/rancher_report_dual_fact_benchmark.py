"""Controlled Dual Fact Benchmark v1; dry-run is the safe default."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from math import ceil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_network.claim.claim import ClaimStatus, ClaimType
from agent_network.claim.evidence_decision import EvidenceDecisionEngine
from agent_network.evidence.document_chunker import DocumentChunk
from agent_network.evidence.offline_retrieval import (
    EvidenceSelectionConfig,
    OfflineBm25EvidenceRetriever,
    RetrievalResult,
)


DEFAULT_FIXTURE = Path("benchmarks/fixtures/rancher-report-v1")
DEFAULT_OUTPUT = Path("benchmarks/results-local/rancher-report-dual-fact-v1")


class _BenchmarkClaim(SimpleNamespace):
    """Small adapter for the existing Claim-aware Retriever and Decision Engine."""

    def to_dict(self) -> dict[str, Any]:
        data = dict(vars(self))
        data["claim_type"] = self.claim_type.value
        data["status"] = self.status.value
        if self.version_scope.exact is None:
            data.pop("version_scope", None)
        else:
            data["version_scope"] = {"exact": self.version_scope.exact}
        return data


def load_claims(fixture_directory: str | Path = DEFAULT_FIXTURE) -> list[dict[str, Any]]:
    payload = _load_json(Path(fixture_directory) / "claims.json")
    claims = payload["claims"]
    ids = [claim["claim_id"] for claim in claims]
    if len(ids) != len(set(ids)):
        raise ValueError("claims.json contains duplicate claim_id values")
    return claims


def build_review_inputs(
    fixture_directory: str | Path = DEFAULT_FIXTURE,
) -> list[Any]:
    fixture_dir = Path(fixture_directory)
    claims = load_claims(fixture_dir)
    chunks = _load_chunks(fixture_dir.parent / "retrieval-v1" / "chunks.json")
    retriever = OfflineBm25EvidenceRetriever(
        chunks,
        EvidenceSelectionConfig(
            max_evidence_per_claim=3,
            max_excerpt_chars_per_evidence=1500,
            max_total_evidence_chars_per_claim=3000,
        ),
    )
    pairs = []
    for data in claims:
        claim = _claim_adapter(data)
        if "extraction_failed" in data.get("tags", []) or "unavailable" in data.get("tags", []):
            retrieval = RetrievalResult(
                claim_id=claim.claim_id,
                query_terms=[],
                candidate_count=0,
                filtered_candidate_count=0,
                selected_count=0,
                top_k=3,
                results=[],
                no_match_reason="extraction_failed"
                if "extraction_failed" in data.get("tags", [])
                else "cache_unavailable",
            )
        else:
            retrieval = retriever.retrieve(claim, top_k=3)
        pairs.append((claim, retrieval))
    return EvidenceDecisionEngine().decide_batch(pairs).review_inputs


def build_plan(
    inputs: list[Any],
    *,
    batch_size: int = 5,
    fixture_directory: str | Path = DEFAULT_FIXTURE,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    batches = [inputs[index : index + batch_size] for index in range(0, len(inputs), batch_size)]
    batch_records = []
    for index, batch in enumerate(batches, start=1):
        payload = [item.to_dict() for item in batch]
        digest = _sha256_json(payload)
        batch_records.append(
            {
                "batch_id": f"batch-{index:03d}",
                "claim_ids": [item.claim["claim_id"] for item in batch],
                "claim_count": len(batch),
                "fact_a_input_sha256": digest,
                "fact_b_input_sha256": digest,
                "input_hashes_match": True,
            }
        )
    call_count = len(batches)
    return {
        "benchmark_version": "rancher-report-dual-fact-v1",
        "fixture": "FIXTURE ONLY",
        "mode": "dry_run",
        "fixture_directory": str(fixture_directory).replace("\\", "/"),
        "claim_count": len(inputs),
        "deduplicated_claim_count": len(inputs),
        "batch_size": batch_size,
        "batch_count": call_count,
        "batches": batch_records,
        "planned_fact_a_calls": call_count,
        "planned_fact_b_calls": call_count,
        "planned_total_model_calls": call_count * 2,
        "estimated_network_request_count": 0,
        "per_claim_model_calls": 0,
        "retry_count": 0,
        "live_run_enabled": False,
    }


def write_dry_run(plan: dict[str, Any], output_directory: str | Path) -> None:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / "benchmark-input.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    evaluation = {
        "mode": "dry_run",
        "model_results_available": False,
        "model_call_count": 0,
        "network_request_count": 0,
        "plan": plan,
    }
    (output / "evaluation.json").write_text(
        json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = [
        "# Rancher Report Dual Fact Benchmark v1",
        "",
        "Dry-run only: no model or network calls were made.",
        "",
        f"- Claims: {plan['claim_count']}",
        f"- Batches: {[item['claim_count'] for item in plan['batches']]}",
        f"- Fact A calls: {plan['planned_fact_a_calls']}",
        f"- Fact B calls: {plan['planned_fact_b_calls']}",
        f"- Total planned model calls: {plan['planned_total_model_calls']}",
        "- Network requests: 0",
        "- Per-claim model calls: 0",
        f"- Input hashes match: {plan['batches'] and all(item['input_hashes_match'] for item in plan['batches'])}",
    ]
    (output / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")


def run_live(inputs: list[Any], *, batch_size: int) -> list[dict[str, Any]]:
    """Run the existing dual-review coordinator after explicit CLI confirmation."""

    from agent_network.claim.fact_model_adapter import fact_model_adapter_from_config
    from agent_network.claim.fact_review import DualFactReviewCoordinator, DualReviewBudget
    from agent_network.config import load_config

    config = load_config()
    fact_a = fact_model_adapter_from_config(config, "fact_a")
    fact_b = fact_model_adapter_from_config(config, "fact_b")
    coordinator = DualFactReviewCoordinator(
        fact_a,
        fact_b,
        DualReviewBudget(
            claims_per_batch=batch_size,
            max_claims_per_batch=batch_size,
            max_batches=ceil(len(inputs) / batch_size),
            max_input_tokens_per_batch=50_000,
            max_expected_output_tokens_per_batch=10_000,
            max_evidence_chars_per_batch=50_000,
            output_safety_ratio=1.0,
        ),
    )
    return [item.to_dict() for item in coordinator.review_batch(inputs)]


def _claim_adapter(data: dict[str, Any]) -> _BenchmarkClaim:
    claim_type = ClaimType(data["claim_type"])
    return _BenchmarkClaim(
        claim_id=data["claim_id"],
        text=data["claim_text"],
        normalized_text=" ".join(data["claim_text"].lower().split()),
        normalized_claim=" ".join(data["claim_text"].lower().split()),
        product=data.get("product"),
        component=data.get("component"),
        claim_type=claim_type,
        status=ClaimStatus.EXTRACTION_FAILED
        if "extraction_failed" in data.get("tags", [])
        else ClaimStatus.PENDING,
        version_scope=SimpleNamespace(exact=data.get("version_scope")),
        entities=[],
    )


def _load_chunks(path: Path) -> list[DocumentChunk]:
    fetched_at = datetime(2026, 7, 14, tzinfo=UTC)
    chunks = []
    for item in _load_json(path):
        text = item["text"]
        chunks.append(
            DocumentChunk(
                chunk_id=item["chunk_id"],
                document_id=item["document_id"],
                canonical_url=item["canonical_url"],
                final_url=item["canonical_url"],
                product=item["product"],
                component=item["component"],
                document_type=item.get("document_type", "reference"),
                document_title=item["document_id"],
                section_heading="Fixture Evidence",
                section_heading_level=2,
                section_order=0,
                chunk_order=0,
                text=text,
                character_count=len(text),
                source_fetched_at=fetched_at,
                product_version=item.get("version"),
                heading_path=["Fixture Evidence"],
            )
        )
    return chunks


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan only; this is the default.")
    parser.add_argument(
        "--run-live", action="store_true", help="Reserved explicit live-run switch."
    )
    parser.add_argument("--confirm-live-model-calls", action="store_true")
    parser.add_argument("--confirm-planned-call-count", type=int)
    parser.add_argument("--fixture-directory", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    inputs = build_review_inputs(args.fixture_directory)
    plan = build_plan(inputs, batch_size=args.batch_size, fixture_directory=args.fixture_directory)
    if args.run_live:
        if not args.confirm_live_model_calls:
            raise SystemExit("live-run requires --confirm-live-model-calls")
        if args.confirm_planned_call_count != plan["planned_total_model_calls"]:
            raise SystemExit("confirm-planned-call-count does not match the dry-run plan")
        results = run_live(inputs, batch_size=args.batch_size)
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        (output / "benchmark-input.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (output / "reconciliation.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"mode": "live", "result_count": len(results)}, ensure_ascii=False))
        return
    write_dry_run(plan, args.output)
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
