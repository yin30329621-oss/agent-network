#!/usr/bin/env python3
"""Case-local Fact A bounded fallback validation runner."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_network.config import load_config
from agent_network.claim.fact_model_adapter import fact_model_adapter_from_config
from agent_network.llm import load_dotenv_if_available
from orchestration_adapter import _configure_fact_a, _prepare_inputs


CASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = CASE_DIR / "output" / "fact-a-only-validation.json"


def _is_success(result: object) -> bool:
    metadata = getattr(result, "response_metadata", {}) or {}
    return (
        getattr(result, "parse_status", "") == "parsed"
        and getattr(getattr(result, "audit_status", None), "value", "") == "completed"
        and metadata.get("finish_reason") != "length"
        and not metadata.get("response_truncated", False)
    )


def _telemetry(result: object) -> dict[str, object]:
    metadata = getattr(result, "response_metadata", {}) or {}
    return {
        "finish_reason": metadata.get("finish_reason"),
        "parse_status": getattr(result, "parse_status", None),
        "audit_status": getattr(getattr(result, "audit_status", None), "value", None),
        "truncated_response": bool(
            metadata.get("response_truncated", False)
            or metadata.get("finish_reason") == "length"
        ),
        "content_length": metadata.get("content_length"),
    }


def main() -> int:
    load_dotenv_if_available()
    _, _, _, retriever, _, review_inputs, _, _ = _prepare_inputs(15)
    inputs = review_inputs[:15]
    config = load_config().with_profile("balanced")
    fact_a = _configure_fact_a(fact_model_adapter_from_config(config, "fact_a"))
    batch_size = 3
    primary_batches = [
        inputs[offset : offset + batch_size] for offset in range(0, len(inputs), batch_size)
    ]
    started = time.monotonic()
    primary_results: list[dict[str, object]] = []
    failed_batches: list[int] = []
    fallback_records: list[dict[str, object]] = []
    recovered_claims: list[str] = []
    unrecovered_claims: list[str] = []
    total_calls = 0

    for batch_number, batch in enumerate(primary_batches, 1):
        results = fact_a.review_batch([item.to_dict() for item in batch])
        total_calls += 1
        batch_failed = not all(_is_success(result) for result in results)
        if batch_failed:
            failed_batches.append(batch_number)
        primary_results.append(
            {
                "batch": batch_number,
                "claim_ids": [item.claim["claim_id"] for item in batch],
                "success_count": sum(_is_success(result) for result in results),
                "failure_count": sum(not _is_success(result) for result in results),
                "results": [_telemetry(result) for result in results],
                "fallback_triggered": batch_failed,
            }
        )
        if not batch_failed:
            continue
        for item in batch:
            result = fact_a.review_batch([item.to_dict()])[0]
            total_calls += 1
            claim_id = item.claim["claim_id"]
            recovered = _is_success(result)
            if recovered:
                recovered_claims.append(claim_id)
            else:
                unrecovered_claims.append(claim_id)
            fallback_records.append(
                {
                    "claim_id": claim_id,
                    "source_batch": batch_number,
                    "attempts": 1,
                    "recovered": recovered,
                    "telemetry": _telemetry(result),
                }
            )

    payload = {
        "mode": "fact_a_bounded_fallback_live_validation",
        "claim_count": len(inputs),
        "model": fact_a.config.model,
        "provider": fact_a.config.provider,
        "temperature": fact_a.llm.temperature,
        "batch_size": batch_size,
        "primary_batch_count": len(primary_batches),
        "failed_primary_batches": failed_batches,
        "fallback_single_claim_calls": len(fallback_records),
        "recovered_claims": recovered_claims,
        "unrecovered_claims": unrecovered_claims,
        "total_fact_a_calls": total_calls,
        "primary_batches": primary_results,
        "fallbacks": fallback_records,
        "runtime_seconds": time.monotonic() - started,
        "evidence_network_requests": retriever.network_request_count,
        "success": len(recovered_claims) + sum(
            item["success_count"] for item in primary_results if not item["fallback_triggered"]
        ) == len(inputs) and not unrecovered_claims,
        "retry_policy": {
            "max_fallback_attempts_per_claim": 1,
            "successful_primary_batches_retried": False,
            "unbounded_retry": False,
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "primary_batch_count": payload["primary_batch_count"],
        "failed_primary_batches": payload["failed_primary_batches"],
        "fallback_single_claim_calls": payload["fallback_single_claim_calls"],
        "recovered_claims": len(recovered_claims),
        "unrecovered_claims": len(unrecovered_claims),
        "total_fact_a_calls": payload["total_fact_a_calls"],
        "success": payload["success"],
        "runtime_seconds": payload["runtime_seconds"],
        "evidence_network_requests": payload["evidence_network_requests"],
    }, ensure_ascii=False))
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
