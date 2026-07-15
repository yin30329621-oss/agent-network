"""Offline Rancher Report Benchmark v1 runner."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_network.claim.claim import ClaimStatus, ClaimType
from agent_network.claim.policy import status_for
from agent_network.evidence.document_chunker import DocumentChunk
from agent_network.evidence.offline_retrieval import (
    EvidenceSelectionConfig,
    OfflineBm25EvidenceRetriever,
)


def run_benchmark(fixture_directory: str | Path) -> dict[str, Any]:
    fixture_dir = Path(fixture_directory)
    claims_payload = _load_json(fixture_dir / "claims.json")
    truth_payload = _load_json(fixture_dir / "ground-truth.json")
    truth_by_id = {item["claim_id"]: item for item in truth_payload["claims"]}
    chunks_path = fixture_dir.parent / "retrieval-v1" / "chunks.json"
    chunks = _load_chunks(chunks_path)
    retriever = OfflineBm25EvidenceRetriever(
        chunks,
        EvidenceSelectionConfig(
            max_evidence_per_claim=3,
            max_excerpt_chars_per_evidence=1500,
            max_total_evidence_chars_per_claim=3000,
        ),
    )

    results: list[dict[str, Any]] = []
    for claim_data in claims_payload["claims"]:
        truth = truth_by_id[claim_data["claim_id"]]
        result = _evaluate_claim(claim_data, truth, retriever)
        results.append(result)

    metrics = _metrics(results)
    return {
        "benchmark_version": "rancher-report-v1",
        "fixture": "FIXTURE ONLY",
        "source_chunks": str(chunks_path).replace("\\", "/"),
        "metrics": metrics,
        "results": results,
        "audit": {
            "model_call_count": retriever.model_call_count,
            "network_request_count": retriever.network_request_count,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# Rancher Report Benchmark v1",
        "",
        "本基准使用离线 FIXTURE ONLY 文档 Chunk，评估 Claim、检索和保守验证规则，不代表真实官方文档或模型准确率。",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key, value in metrics.items():
        if key != "per_status":
            lines.append(f"| `{key}` | `{value}` |")
    lines.extend(
        ["", "## Per Status", "", "| Status | Expected | Actual | Exact |", "|---|---:|---:|---:|"]
    )
    for status, values in metrics["per_status"].items():
        lines.append(
            f"| `{status}` | {values['expected']} | {values['actual']} | {values['exact']} |"
        )
    failures = [item for item in report["results"] if not item["status_match"]]
    lines.extend(["", "## Failed Status Cases", ""])
    if failures:
        for item in failures:
            lines.append(
                f"- `{item['claim_id']}`: expected `{item['expected_status']}`, "
                f"actual `{item['actual_status']}`"
            )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Candidate-only local policy never upgrades BM25 relevance to direct support or contradiction.",
            "- `needs_external_verification` remains required for CVE, release and version-scoped facts.",
            "- This benchmark does not call Fact A/B and does not measure model agreement.",
        ]
    )
    return "\n".join(lines) + "\n"


def _evaluate_claim(
    claim_data: dict[str, Any], truth: dict[str, Any], retriever: OfflineBm25EvidenceRetriever
) -> dict[str, Any]:
    claim_id = claim_data["claim_id"]
    if "extraction_failed" in claim_data.get("tags", []):
        actual_status, actual_relation, evidence = "extraction_failed", "unavailable", []
        no_match_reason = "extraction_failed"
    elif "unavailable" in claim_data.get("tags", []):
        actual_status, actual_relation, evidence = "unavailable", "unavailable", []
        no_match_reason = "cache_unavailable"
    else:
        claim = _claim_namespace(claim_data)
        retrieved = retriever.retrieve(claim, top_k=3)
        evidence = [item.to_dict() for item in retrieved.results]
        status, relation, _limitations = status_for(
            claim,
            candidate_count=retrieved.selected_count,
            loaded_document_count=1,
            failed_document_count=0,
        )
        actual_status, actual_relation = status.value, relation.value
        no_match_reason = retrieved.no_match_reason

    actual_ids = [item["chunk_id"] for item in evidence]
    expected_ids = list(truth["expected_chunk_ids"])
    forbidden_ids = set(truth["forbidden_chunk_ids"])
    correct_ids = set(actual_ids) & set(expected_ids)
    unsupported_ids = [chunk_id for chunk_id in actual_ids if chunk_id not in expected_ids]
    return {
        "claim_id": claim_id,
        "expected_status": truth["expected_status"],
        "actual_status": actual_status,
        "expected_relation": truth["expected_relation"],
        "actual_relation": actual_relation,
        "expected_chunk_ids": expected_ids,
        "actual_chunk_ids": actual_ids,
        "forbidden_hits": [chunk_id for chunk_id in actual_ids if chunk_id in forbidden_ids],
        "unsupported_citations": unsupported_ids,
        "evidence": evidence,
        "no_match_reason": no_match_reason,
        "status_match": actual_status == truth["expected_status"],
        "relation_match": actual_relation == truth["expected_relation"],
        "citation_correct_count": len(correct_ids),
        "expected_citation_count": len(expected_ids),
        "actual_evidence_count": len(actual_ids),
        "requires_manual_review": True,
        "rationale": truth["rationale"],
        "limitations": truth["limitations"],
    }


def _metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    expected_citations = sum(item["expected_citation_count"] for item in results)
    actual_citations = sum(item["actual_evidence_count"] for item in results)
    correct_citations = sum(item["citation_correct_count"] for item in results)
    forbidden_hits = sum(len(item["forbidden_hits"]) for item in results)
    status_counts = Counter(item["expected_status"] for item in results)
    actual_counts = Counter(item["actual_status"] for item in results)
    per_status = {
        status: {
            "expected": count,
            "actual": actual_counts.get(status, 0),
            "exact": sum(
                item["status_match"] and item["expected_status"] == status for item in results
            ),
        }
        for status, count in sorted(status_counts.items())
    }
    status_exact = sum(item["status_match"] for item in results)
    return {
        "total_claims": total,
        "exact_status_accuracy": _ratio(status_exact, total),
        "relation_accuracy": _ratio(sum(item["relation_match"] for item in results), total),
        "citation_precision": _ratio(correct_citations, actual_citations, empty_value=1.0),
        "citation_recall": _ratio(correct_citations, expected_citations, empty_value=1.0),
        "unsupported_citation_count": sum(len(item["unsupported_citations"]) for item in results),
        "agreement_rate": _ratio(
            sum(item["status_match"] and item["relation_match"] for item in results), total
        ),
        "auto_resolve_rate": 0.0,
        "manual_review_rate": _ratio(
            sum(item["requires_manual_review"] for item in results), total
        ),
        "forbidden_hit_count": forbidden_hits,
        "average_evidence_count": round(actual_citations / total, 3) if total else 0.0,
        "model_call_count": 0,
        "network_request_count": 0,
        "per_status": per_status,
    }


def _claim_namespace(data: dict[str, Any]) -> SimpleNamespace:
    claim_type = ClaimType(data["claim_type"])
    version = data.get("version_scope")
    return SimpleNamespace(
        claim_id=data["claim_id"],
        text=data["claim_text"],
        normalized_text=data["claim_text"],
        normalized_claim=data["claim_text"],
        product=data.get("product"),
        component=data.get("component"),
        claim_type=claim_type,
        status=ClaimStatus.PENDING,
        version_scope=SimpleNamespace(exact=version),
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


def _ratio(numerator: int, denominator: int, *, empty_value: float = 0.0) -> float:
    return round(numerator / denominator, 4) if denominator else empty_value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "fixture_directory",
        nargs="?",
        type=Path,
        default=Path("benchmarks/fixtures/rancher-report-v1"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(args.fixture_directory)
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "benchmark.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (args.output / "benchmark.md").write_text(render_markdown(report), encoding="utf-8")
        (args.output / "run.json").write_text(
            json.dumps(
                {
                    "run_id": datetime.now(UTC).isoformat(),
                    "benchmark_version": report["benchmark_version"],
                    "fixture_path": str(args.fixture_directory).replace("\\", "/"),
                    **report["metrics"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
