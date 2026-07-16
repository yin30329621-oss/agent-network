"""Offline Markdown Claim extraction benchmark v1 runner."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent_network.claim import ClaimExtractionRequest, DeterministicClaimExtractor


DEFAULT_FIXTURE = Path("benchmarks/fixtures/report-claim-extraction-v1")


def run_benchmark(fixture_directory: str | Path = DEFAULT_FIXTURE) -> dict[str, Any]:
    fixture_dir = Path(fixture_directory)
    report_path = fixture_dir / "report.md"
    expected = _load_json(fixture_dir / "expected.json")
    extraction = DeterministicClaimExtractor().extract(
        ClaimExtractionRequest(
            document_text=report_path.read_text(encoding="utf-8"),
            source_name=expected["source_name"],
        )
    )
    actual_statistics = {
        "candidate_count": extraction.candidate_count,
        "extracted_count": len(extraction.claims),
        "duplicate_count": extraction.duplicate_count,
        "failure_count": len(extraction.failures),
    }
    actual_ids = [claim.claim_id for claim in extraction.claims]
    actual_heading_paths = [claim.heading_path for claim in extraction.claims]
    checks = {
        "statistics_match": actual_statistics == expected["expected_statistics"],
        "claim_ids_match": actual_ids == expected["expected_claim_ids"],
        "heading_paths_match": actual_heading_paths == expected["expected_heading_paths"],
    }
    return {
        "benchmark_version": "report-claim-extraction-v1",
        "fixture": "FIXTURE ONLY",
        "metrics": actual_statistics,
        "checks": checks,
        "passed": all(checks.values()),
        "claims": [claim.to_dict() for claim in extraction.claims],
        "failures": [failure.model_dump(mode="json") for failure in extraction.failures],
        "audit": {
            "model_call_count": 0,
            "network_request_count": 0,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    lines = [
        "# Report Claim Extraction Benchmark v1",
        "",
        "Offline deterministic fixture benchmark; no model or network calls were made.",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key in (
        "candidate_count",
        "extracted_count",
        "duplicate_count",
        "failure_count",
    ):
        lines.append(f"| {key} | {metrics[key]} |")
    lines.extend(
        [
            "",
            f"- Passed: {report['passed']}",
            f"- Model calls: {report['audit']['model_call_count']}",
            f"- Network requests: {report['audit']['network_request_count']}",
        ]
    )
    return "\n".join(lines) + "\n"


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
