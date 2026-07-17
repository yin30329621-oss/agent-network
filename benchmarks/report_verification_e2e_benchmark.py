"""Offline end-to-end report verification benchmark v1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_network.claim import Claim
from agent_network.claim.fact_review import (
    DualFactReviewCoordinator,
    DualReviewBudget,
    FakeFactReviewer,
)
from agent_network.evidence.offline_retrieval import RetrievalResult, SelectedEvidence
from agent_network.workflow.report_verification import (
    OfflineReportVerificationConfig,
    OfflineReportVerificationOrchestrator,
)


DEFAULT_FIXTURE = Path("benchmarks/fixtures/report-verification-e2e-v1")


class FixtureOfflineRetriever:
    """Deterministic fixture retriever with one intentional failure path."""

    model_call_count = 0
    network_request_count = 0

    def __init__(self, failing_marker: str) -> None:
        self.failing_marker = failing_marker
        self.calls: list[str] = []

    def retrieve(self, claim: Claim, *, top_k: int | None = None) -> RetrievalResult:
        self.calls.append(claim.claim_id)
        if self.failing_marker in claim.text:
            raise RuntimeError("fixture retrieval failure")
        evidence = SelectedEvidence(
            chunk_id=f"fixture-chunk-{claim.claim_id}",
            document_id="fixture-document",
            canonical_url="https://docs.example.test/fixture",
            heading_path=list(claim.heading_path),
            text_excerpt=claim.text,
            bm25_score=1.0,
            final_score=1.0,
            matched_terms=["rancher", "supports"],
            product_match=True,
            component_match=None,
            version_match=True,
            document_type="official",
            source_priority=1,
            selection_reason="fixture",
            evidence_limitations=[],
        )
        return RetrievalResult(
            claim_id=claim.claim_id,
            query_terms=["rancher"],
            candidate_count=1,
            filtered_candidate_count=1,
            selected_count=1,
            top_k=top_k or 5,
            results=[evidence],
        )


def run_benchmark(fixture_directory: str | Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    fixture_dir = Path(fixture_directory)
    expected = _load_json(
        fixture_dir
        / ("expected-extraction.json" if (fixture_dir / "expected-extraction.json").exists() else "expected.json")
    )
    report_path = fixture_dir / "report.md"
    retriever = FixtureOfflineRetriever(expected.get("failing_marker", "__never__"))
    reviewer_batch_size = int(expected.get("reviewer_batch_size", 3))
    dual_enabled = bool(expected.get("enable_dual_fact", False))
    coordinator = None
    if dual_enabled:
        fact_a = FakeFactReviewer("fact_a")
        fact_b = FakeFactReviewer("fact_b")
        fact_a.config = type("Config", (), {"max_tokens": 2400, "timeout_seconds": 90})()
        fact_b.config = type("Config", (), {"max_tokens": 2200, "timeout_seconds": 180})()
        coordinator = DualFactReviewCoordinator(
            fact_a,
            fact_b,
            budget=DualReviewBudget(
                claims_per_batch=reviewer_batch_size,
                max_expected_output_tokens_per_batch=reviewer_batch_size * 300,
            ),
        )
    result = OfflineReportVerificationOrchestrator(
        retriever,
        config=OfflineReportVerificationConfig(
            source_name=expected["source_name"],
            enable_dual_fact=dual_enabled,
            reviewer_batch_size=reviewer_batch_size,
        ),
        coordinator=coordinator,
    ).run_file(report_path, source_name=expected["source_name"])
    artifact = result.artifact
    claims = artifact["claims"]["claims"]
    evidence_results = artifact["evidence"]["results"]
    failure_slots = artifact["evidence"]["failure_slots"]
    claim_ids = [claim["claim_id"] for claim in claims]
    evidence_ids = [item["claim_id"] for item in evidence_results]
    reconciliation_ids = [item["claim_id"] for item in artifact["reconciliation"]]
    call_metadata = artifact["fact_review"]["call_metadata"]
    actual = {
        "candidate_count": artifact["claims"]["candidate_count"],
        "extracted_count": len(claims),
        "evidence_decision_count": sum(item["decision"] is not None for item in evidence_results),
        "failure_slot_count": len(failure_slots),
        "artifact_complete": set(artifact)
        == {"metadata", "claims", "evidence", "fact_review", "reconciliation", "statistics"},
        "claim_id_aligned": claim_ids == evidence_ids == reconciliation_ids,
        "model_call_count": artifact["statistics"]["model_call_count"],
        "network_request_count": artifact["statistics"]["network_request_count"],
        "fact_a_calls": int(call_metadata.get("estimated_reviewer_calls", 0)) // 2,
        "fact_b_calls": int(call_metadata.get("estimated_reviewer_calls", 0)) // 2,
        "total_planned_calls": int(call_metadata.get("estimated_reviewer_calls", 0)),
        "reconciliation_executed": artifact["statistics"]["reconciliation_executed"],
    }
    expected_metrics = expected.get("expected", {})
    if not expected_metrics:
        expected_metrics = {
            key: expected[key]
            for key in (
                "candidate_count",
                "extracted_count",
                "evidence_decision_count",
                "failure_slot_count",
                "artifact_complete",
                "claim_id_aligned",
                "model_call_count",
                "network_request_count",
            )
            if key in expected
        }
    checks = {
        "statistics_match": {
            key: actual[key] == expected_metrics[key]
            for key in (
                "candidate_count",
                "extracted_count",
                "evidence_decision_count",
                "failure_slot_count",
            )
            if key in expected_metrics
        },
        "claim_ids_match": claim_ids == expected.get("expected_claim_ids", claim_ids),
        "artifact_checks": all(
            actual[key] == expected_metrics[key]
            for key in (
                "artifact_complete",
                "claim_id_aligned",
                "model_call_count",
                "network_request_count",
            )
            if key in expected_metrics
        ),
        "dual_fact_checks": all(
            actual[key] == expected[key]
            for key in ("fact_a_calls", "fact_b_calls", "total_planned_calls")
            if key in expected
        ),
    }
    passed = all(checks["statistics_match"].values()) and all(
        value is True for value in (
            checks["claim_ids_match"],
            checks["artifact_checks"],
            checks["dual_fact_checks"],
        )
    )
    return {
        "benchmark_version": "report-verification-e2e-v1",
        "fixture": str(fixture_dir),
        "metrics": actual,
        "checks": checks,
        "passed": passed,
        "artifact": artifact,
        "audit": {
            "model_call_count": 0,
            "network_request_count": 0,
            "retriever_calls": len(retriever.calls),
        },
    }


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(args.fixture)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
