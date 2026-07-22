#!/usr/bin/env python3
"""Case-local dry-run orchestration adapter for live validation."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_network.claim.evidence_decision import (
    EvidenceDecisionBatch,
    EvidenceDecisionEngine,
    FactReviewInput,
)
from agent_network.claim.fact_adapter import FactReviewInputAdapter
from agent_network.claim.fact_coordinator_adapter import FactReviewInputCoordinatorAdapter
from agent_network.claim.fact_model_adapter import fact_model_adapter_from_config
from agent_network.claim.fact_review import DualFactReviewCoordinator, DualReviewBudget
from agent_network.claim.registry import ClaimRegistry
from agent_network.config import load_config
from agent_network.evidence.offline_retrieval import OfflineBm25EvidenceRetriever
from agent_network.llm import LiteLLMClient, load_dotenv_if_available
from agent_network.prompts import PromptRegistry
from agent_network.schemas import AgentReview, ReviewRequest
from agent_network.workflow.review import ReviewWorkflow
from run_live_validation import INPUT_PATH, CHUNKS_PATH, _load_chunks, _select_claims
from agent_network.claim import ClaimExtractionRequest, DeterministicClaimExtractor


CASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = CASE_DIR / "output"


class _JsonOnlyLLM:
    """Case-local request policy wrapper; core agents remain unchanged."""

    def __init__(self, client: LiteLLMClient) -> None:
        self.client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    @property
    def last_response_audit(self) -> dict[str, Any]:
        return self.client.last_response_audit

    def complete(self, **kwargs: Any) -> str:
        kwargs.setdefault("response_format", {"type": "json_object"})
        return self.client.complete(**kwargs)


def _review_to_dict(review: AgentReview) -> dict[str, Any]:
    return review.to_dict()



FACT_TOP_K = 2
FACT_CHARS_PER_CHUNK = 350
FACT_MAX_EVIDENCE_CHARS = 900
FACT_A_COMPACT_SYSTEM_PROMPT = """You are Fact A, an Evidence Support Reviewer.
Review only the supplied JSON batch and do not infer facts. Return exactly one valid JSON object:
{"reviews":[...]}.
Each review must contain only these existing schema fields:
claim_id, decision, recommended_status, cited_chunk_ids, reasoning_summary, limitations.
Use the input claim_id exactly. cited_chunk_ids may contain only chunk IDs from that claim's decision.evidence.
Use a short reason in reasoning_summary, at most 80 characters. Use limitations=[] unless essential, otherwise one string at most 80 characters.
Do not output confidence, URLs, evidence text, repeated evidence, markdown, explanations, analysis, or reasoning text.
Output JSON only, with one review per input claim in input order."""
FACT_A_REQUEST_OPTIONS = {"response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}}
FACT_A_DRY_RUN_BATCH_SIZE = 3
FACT_B_DRY_RUN_BATCH_SIZE = 5


def _configure_fact_a(adapter: Any) -> Any:
    adapter.system_prompt = FACT_A_COMPACT_SYSTEM_PROMPT
    adapter.llm.temperature = 0.0
    adapter.config = replace(
        adapter.config,
        request_options=dict(FACT_A_REQUEST_OPTIONS),
    )
    return adapter


def _estimate_tokens(value: Any) -> int:
    return math.ceil(len(json.dumps(value, ensure_ascii=False, sort_keys=True)) / 4)


def _compact_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": item.get("chunk_id"),
        "document_id": item.get("document_id"),
        "canonical_url": item.get("canonical_url"),
        "heading_path": item.get("heading_path", []),
        "bm25_score": item.get("bm25_score"),
        "final_score": item.get("final_score"),
        "text_excerpt": str(item.get("text_excerpt", ""))[:FACT_CHARS_PER_CHUNK],
    }


def _compact_inputs(
    claim: Any, decision: Any, retrieval: Any
) -> FactReviewInput:
    retrieval_data = retrieval.to_dict()
    selected = retrieval_data.get("results", [])[:FACT_TOP_K]
    selected = [_compact_evidence_item(item) for item in selected]
    decision_data = decision.to_dict()
    decision_data["evidence"] = [
        _compact_evidence_item(item) for item in decision_data.get("evidence", [])[:FACT_TOP_K]
    ]
    decision_data["limitations"] = list(decision_data.get("limitations", []))[:2]
    compact_retrieval = {
        "claim_id": retrieval_data.get("claim_id"),
        "query_terms": retrieval_data.get("query_terms", []),
        "top_k": FACT_TOP_K,
        "results": selected,
        "selected_count": len(selected),
        "traceability": {
            "chunk_ids": [item["chunk_id"] for item in selected],
            "source_document_ids": [item["document_id"] for item in selected],
        },
    }
    return FactReviewInput(
        claim=claim.to_dict(),
        decision=decision_data,
        retrieval=compact_retrieval,
    )



def _security_context(
    fact_inputs: list[dict[str, Any]], fact_results: dict[str, Any]
) -> dict[str, Any]:
    claims = [
        {
            "claim_id": item["claim"].get("claim_id"),
            "text": item["claim"].get("text"),
            "claim_type": item["claim"].get("claim_type"),
            "heading_path": item["claim"].get("heading_path", []),
        }
        for item in fact_inputs
    ]
    evidence_references = []
    for item in fact_inputs:
        chunks = []
        for chunk in item["retrieval"].get("results", [])[:FACT_TOP_K]:
            chunks.append(
                {
                    "chunk_id": chunk.get("chunk_id"),
                    "document_id": chunk.get("document_id"),
                    "canonical_url": chunk.get("canonical_url"),
                    "text_excerpt": str(chunk.get("text_excerpt", ""))[:200],
                }
            )
        evidence_references.append(
            {"claim_id": item["claim"].get("claim_id"), "chunks": chunks}
        )
    compact_fact_results = {
        key: [
            {
                "claim_id": value.get("claim_id"),
                "status": value.get("status"),
                "recommended_status": value.get("recommended_status"),
                "cited_chunk_ids": value.get("cited_chunk_ids", []),
                "reasoning_summary": str(value.get("reasoning_summary", ""))[:240],
            }
            for value in values
        ]
        for key, values in fact_results.items()
        if isinstance(values, list)
    }
    return {
        "claims": claims,
        "evidence_references": evidence_references,
        "fact_results": compact_fact_results,
    }


def _logic_context(
    fact_inputs: list[dict[str, Any]],
    fact_results: dict[str, Any],
    security_review: AgentReview,
) -> dict[str, Any]:
    compact_claims = []
    evidence = []
    for item in fact_inputs:
        claim = item["claim"]
        decision = item.get("decision", {})
        compact_claims.append(
            {
                "claim_id": claim.get("claim_id"),
                "text": claim.get("text"),
                "claim_type": claim.get("claim_type"),
                "verification_status": decision.get("status"),
                "limitations": list(decision.get("limitations", []))[:1],
            }
        )
        chunks = item.get("retrieval", {}).get("results", [])[:FACT_TOP_K]
        evidence.append(
            {
                "claim_id": claim.get("claim_id"),
                "chunk_ids": [chunk.get("chunk_id") for chunk in chunks],
                "sources": [chunk.get("document_id") for chunk in chunks],
            }
        )
    compact_facts = {}
    for reviewer, values in fact_results.items():
        compact_facts[reviewer] = [
            {
                "claim_id": value.get("claim_id"),
                "status": value.get("status"),
                "recommended_status": value.get("recommended_status"),
                "cited_chunk_ids": value.get("cited_chunk_ids", []),
                "reasoning_summary": str(value.get("reasoning_summary", ""))[:120],
                "limitations": list(value.get("limitations", []))[:1],
            }
            for value in values
            if isinstance(value, dict)
        ]
    security = security_review.to_dict()
    compact_security = {
        "status": security.get("status"),
        "summary": str(security.get("summary", ""))[:300],
        "findings": [
            {
                key: finding.get(key)
                for key in (
                    "severity",
                    "location",
                    "issue",
                    "reason",
                    "evidence_needed",
                    "reference",
                    "suggestion",
                    "confidence",
                )
                if key in finding
            }
            for finding in security.get("findings", [])
        ],
    }
    return {
        "claims": compact_claims,
        "verification_evidence_references": evidence,
        "fact_results": compact_facts,
        "security_result": compact_security,
    }


def _prepare_inputs(claim_limit: int) -> tuple[Any, list[Any], ClaimRegistry, Any, list[Any], list[FactReviewInput], list[dict[str, Any]], dict[str, Any]]:
    extraction = DeterministicClaimExtractor().extract(
        ClaimExtractionRequest(
            document_text=INPUT_PATH.read_text(encoding="utf-8"),
            source_name=INPUT_PATH.name,
        )
    )
    selected = _select_claims(extraction.claims, limit=claim_limit)
    registry = ClaimRegistry(selected)
    retriever = OfflineBm25EvidenceRetriever(_load_chunks(CHUNKS_PATH))
    engine = EvidenceDecisionEngine()
    decisions = []
    review_inputs = []
    retrieval_records = []
    for claim in registry:
        retrieval = retriever.retrieve(claim, top_k=5)
        decision = engine.decide(claim, retrieval)
        decisions.append(decision)
        retrieval_records.append(retrieval.to_dict())
        review_inputs.append(_compact_inputs(claim, decision, retrieval))
    input_dicts = [item.to_dict() for item in review_inputs]
    batch_count = math.ceil(len(input_dicts) / 5) if input_dicts else 0
    batch_token_totals = [
        sum(_estimate_tokens(item) for item in input_dicts[offset:offset + 5])
        for offset in range(0, len(input_dicts), 5)
    ]
    token_stats = {
        "fact_a_total_input_tokens": sum(batch_token_totals),
        "fact_b_total_input_tokens": sum(batch_token_totals),
        "fact_batch_max_input_tokens": max(batch_token_totals, default=0),
        "security_input_tokens": 0,
        "logic_input_tokens": 0,
        "merge_input_tokens": 0,
        "fact_batch_count": batch_count,
        "evidence_traceability": all(
            bool(item["retrieval"]["traceability"]["chunk_ids"])
            == bool(item["decision"].get("evidence"))
            for item in input_dicts
        ),
    }
    return extraction, selected, registry, retriever, decisions, review_inputs, retrieval_records, token_stats


def _write_json(name: str, payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _review_calls(review: AgentReview | None) -> int:
    if review is None:
        return 0
    return int(review.model_call_count or review.request_attempt_count or 0)


def run_live(batch_size: int = 5, claim_limit: int = 30) -> dict[str, Any]:
    started = time.monotonic()
    load_dotenv_if_available()
    extraction, selected, registry, retriever, decisions, review_inputs, retrieval_records, token_stats = _prepare_inputs(claim_limit)
    config = load_config().with_profile("balanced")
    config.raw["review"]["agents"]["security"]["model"] = "Pro/moonshotai/Kimi-K2.6"
    fact_a = _configure_fact_a(fact_model_adapter_from_config(config, "fact_a"))
    fact_b = fact_model_adapter_from_config(config, "fact_b")
    model_names = {
        "fact_a": fact_a.config.model,
        "fact_b": fact_b.config.model,
        "security": config.model_for_agent("security"),
        "logic": config.model_for_agent("logic"),
        "merge": config.model_for_agent("merge"),
    }
    metadata = {
        "mode": "live",
        "claim_count": len(selected),
        "batch_size": batch_size,
        "model_names": model_names,
        "completed_agents": [],
        "failed_agent": None,
        "actual_model_calls": 0,
        "runtime_seconds": 0.0,
        "evidence_network_requests": retriever.network_request_count,
        "input_token_estimates": token_stats,
        "agent_invocation_config": {
            "fact_a": {
                "temperature": config.temperature,
                "response_format": dict(FACT_A_REQUEST_OPTIONS["response_format"]),
                "json_only_instruction": True,
                "compact_fields": ["claim_id", "decision", "recommended_status", "cited_chunk_ids", "reasoning_summary", "limitations"],
                "max_reasoning_chars": 80,
                "evidence_repetition": False,
            },
            "fact_b": {
                "unchanged": True,
            },
            "security": {
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
                "json_only_instruction": True,
            },
            "logic": {
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
                "timeout_seconds": 180,
                "retry_attempts": 1,
                "json_only_instruction": True,
            },
            "merge": {
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
                "json_only_instruction": True,
            },
        },
        "execution_status": "running",
    }
    _write_json("claims.json", {"claims": [claim.to_dict() for claim in selected]})
    _write_json("evidence-retrieval.json", {"results": retrieval_records, "top_k": 5})
    _write_json("run-metadata.json", metadata)

    decision_batch = EvidenceDecisionBatch(
        decisions=decisions,
        review_inputs=review_inputs,
        status_counts={},
        network_request_count=retriever.network_request_count,
        model_call_count=0,
    )
    adapter_result = FactReviewInputAdapter().adapt(decision_batch)
    coordinator = DualFactReviewCoordinator(
        fact_a,
        fact_b,
        budget=DualReviewBudget(
            claims_per_batch=batch_size,
            max_expected_output_tokens_per_batch=10_000,
            max_evidence_chars_per_batch=30_000,
        ),
    )
    coordinator_result = FactReviewInputCoordinatorAdapter(coordinator).review(adapter_result)
    fact_review = {
        "execution_status": "completed",
        "reconciliations": [item.to_dict() for item in coordinator_result.reconciliations],
        "failure_slots": [item.to_dict() for item in coordinator_result.failure_slots],
        "cost_metadata": coordinator_result.cost_metadata,
        "isolation": {"deep_copy": True, "shared_reviewer_output": False},
    }
    _write_json("fact-review.json", fact_review)
    fact_calls = int(coordinator_result.cost_metadata.get("actual_reviewer_calls", 0))
    metadata["completed_agents"] = ["fact_a", "fact_b"]
    metadata["actual_model_calls"] = fact_calls
    metadata["runtime_seconds"] = time.monotonic() - started
    _write_json("run-metadata.json", metadata)

    fact_result_payload = {
        "fact_a": [
            item.get("fact_a", {}) for item in fact_review["reconciliations"]
            if isinstance(item, dict) and isinstance(item.get("fact_a"), dict)
        ],
        "fact_b": [
            item.get("fact_b", {}) for item in fact_review["reconciliations"]
            if isinstance(item, dict) and isinstance(item.get("fact_b"), dict)
        ],
    }
    review_markdown = (
        "Return exactly one JSON object with a findings array. JSON only; "
        "do not output reasoning, analysis, markdown, or extra text."
        + chr(10)
        + json.dumps(
            _security_context([item.to_dict() for item in review_inputs], fact_result_payload),
            ensure_ascii=False,
        )
    )
    llm = _JsonOnlyLLM(
        LiteLLMClient(
            default_model=config.default_model,
            temperature=0.0,
            max_tokens=config.max_tokens,
            timeout_seconds=config.timeout_seconds,
            retry_attempts=config.retry_attempts,
            model_options=config.llm_options_by_model(),
        )
    )
    workflow = ReviewWorkflow.from_config(
        llm=llm, prompts=PromptRegistry(ROOT / "prompts"), config=config
    )
    request = ReviewRequest(markdown=review_markdown, source_name=INPUT_PATH.name)
    try:
        security = workflow.security_agent.review(request)
    except Exception as exc:
        security = AgentReview(agent="security", summary="Security Agent failed.", status="failed", error_type=type(exc).__name__, error_message=str(exc), failure_stage="review")
    _write_json("security-review.json", _review_to_dict(security))
    metadata["completed_agents"].append("security")
    metadata["actual_model_calls"] = fact_calls + _review_calls(security)
    metadata["runtime_seconds"] = time.monotonic() - started
    if security.status not in {"completed", "completed_with_warnings", "valid"}:
        metadata["failed_agent"] = "security"
    _write_json("run-metadata.json", metadata)

    logic_context = _logic_context(
        [item.to_dict() for item in review_inputs],
        fact_result_payload,
        security,
    )
    logic_request = ReviewRequest(
        markdown=(
            "Return exactly one JSON object. JSON only; no reasoning, markdown, or extra text."
            + chr(10)
            + json.dumps(logic_context, ensure_ascii=False)
        ),
        source_name=INPUT_PATH.name,
    )
    token_stats["logic_input_tokens"] = _estimate_tokens(logic_request.markdown)
    metadata["input_token_estimates"]["logic_input_tokens"] = token_stats["logic_input_tokens"]
    _write_json("run-metadata.json", metadata)
    workflow.logic_agent.timeout_seconds = 180
    if hasattr(workflow.logic_agent.llm, "retry_attempts"):
        workflow.logic_agent.llm.retry_attempts = 1
    try:
        logic = workflow.logic_agent.review(logic_request)
    except Exception as exc:
        logic = AgentReview(agent="logic", summary="Logic Agent failed.", status="failed", error_type=type(exc).__name__, error_message=str(exc), failure_stage="review")
    _write_json("logic-review.json", _review_to_dict(logic))
    metadata["completed_agents"].append("logic")
    metadata["actual_model_calls"] = fact_calls + _review_calls(security) + _review_calls(logic)
    metadata["runtime_seconds"] = time.monotonic() - started
    if logic.status not in {"completed", "completed_with_warnings", "valid"}:
        metadata["failed_agent"] = "logic"
        _write_json("merge-result.json", {"agent": "merge", "status": "incomplete", "skip_reason": "logic_failed", "completed_inputs": ["fact_a", "fact_b", "security"]})
        metadata["execution_status"] = "failed"
        _write_json("run-metadata.json", metadata)
        (OUTPUT_DIR / "final-review-report.md").write_text(
            chr(10).join(["# Rancher Security Review Live Validation", f"Workflow stopped at Logic Agent: {logic.error_message or logic.summary}", ""]),
            encoding="utf-8",
        )
        return metadata
    _write_json("run-metadata.json", metadata)

    fact_a_review = AgentReview(agent="fact_a", summary="See fact-review.json", status="completed")
    fact_b_review = AgentReview(agent="fact_b", summary="See fact-review.json", status="completed")
    try:
        merged = workflow.merge_agent.merge([fact_a_review, fact_b_review, security, logic], language="zh")
    except Exception as exc:
        merged = AgentReview(agent="merge", summary="Merge Agent failed.", status="failed", error_type=type(exc).__name__, error_message=str(exc), failure_stage="merge")
    _write_json("merge-result.json", _review_to_dict(merged))
    metadata["completed_agents"].append("merge")
    metadata["actual_model_calls"] = fact_calls + _review_calls(security) + _review_calls(logic) + _review_calls(merged)
    metadata["runtime_seconds"] = time.monotonic() - started
    metadata["execution_status"] = "completed" if merged.status in {"completed", "completed_with_warnings", "valid"} else "failed"
    _write_json("run-metadata.json", metadata)
    (OUTPUT_DIR / "final-review-report.md").write_text(
        chr(10).join([
            "# \u0052\u0061\u006e\u0063\u0068\u0065\u0072 \u5b89\u5168\u5ba1\u67e5 Live Validation \u6700\u7ec8\u62a5\u544a",
            f"- Claim \u6570\u91cf\uff1a{len(selected)}",
            f"- \u5b9e\u9645\u6a21\u578b\u8c03\u7528\uff1a{metadata['actual_model_calls']}",
            f"- Evidence \u7f51\u7edc\u8bf7\u6c42\uff1a{retriever.network_request_count}",
            "",
            "## Merge Agent \u603b\u7ed3",
            f"{merged.summary}",
            "",
        ]),
        encoding="utf-8",
    )
    return metadata


def run_dry_run(batch_size: int = 5, claim_limit: int = 30) -> dict[str, Any]:
    extraction, selected, registry, retriever, decisions, review_inputs, retrieval_records, token_stats = _prepare_inputs(claim_limit)
    fact_inputs = [item.to_dict() for item in review_inputs]

    fact_a_inputs = deepcopy(fact_inputs)
    fact_b_inputs = deepcopy(fact_inputs)
    fact_review = {
        "execution_status": "not_executed",
        "fact_a": {"inputs": fact_a_inputs, "planned_calls": math.ceil(len(selected) / batch_size)},
        "fact_b": {"inputs": fact_b_inputs, "planned_calls": math.ceil(len(selected) / batch_size)},
        "isolation": {
            "deep_copy": True,
            "shared_reviewer_output": False,
            "input_claim_ids_equal": [item["claim"]["claim_id"] for item in fact_a_inputs]
                == [item["claim"]["claim_id"] for item in fact_b_inputs],
        },
        "results": [],
    }
    planned_fact_a = [
        {"claim_id": item["claim"]["claim_id"], "status": "not_executed", "cited_chunk_ids": []}
        for item in fact_inputs
    ]
    planned_fact_b = [dict(item) for item in planned_fact_a]
    planned_security = [
        {"claim_id": item["claim"]["claim_id"], "status": "not_executed"}
        for item in fact_inputs
    ]
    security_input = _security_context(
        fact_inputs,
        {"fact_a": planned_fact_a, "fact_b": planned_fact_b},
    )
    security_input["execution_status"] = "not_executed"
    logic_input = {
        "execution_status": "not_executed",
        "claims": [item["claim"] for item in fact_inputs],
        "fact_output": {"fact_a": planned_fact_a, "fact_b": planned_fact_b},
        "security_output": planned_security,
    }
    merge_input = {
        "execution_status": "not_executed",
        "fact_a": planned_fact_a,
        "fact_b": planned_fact_b,
        "security": planned_security,
        "logic": [{"claim_id": item["claim"]["claim_id"], "status": "not_executed"} for item in fact_inputs],
    }
    fact_item_tokens = [_estimate_tokens(item) for item in fact_inputs]
    fact_a_batch_token_estimates = [
        sum(fact_item_tokens[offset:offset + FACT_A_DRY_RUN_BATCH_SIZE])
        for offset in range(0, len(fact_item_tokens), FACT_A_DRY_RUN_BATCH_SIZE)
    ]
    fact_b_batch_token_estimates = [
        sum(fact_item_tokens[offset:offset + FACT_B_DRY_RUN_BATCH_SIZE])
        for offset in range(0, len(fact_item_tokens), FACT_B_DRY_RUN_BATCH_SIZE)
    ]
    token_stats["fact_a_batch_token_estimates"] = fact_a_batch_token_estimates
    token_stats["fact_a_max_batch_input_tokens"] = max(fact_a_batch_token_estimates, default=0)
    token_stats["fact_b_batch_token_estimates"] = fact_b_batch_token_estimates
    token_stats["fact_b_max_batch_input_tokens"] = max(fact_b_batch_token_estimates, default=0)
    token_stats["security_input_tokens"] = _estimate_tokens(security_input)
    token_stats["logic_input_tokens"] = _estimate_tokens(logic_input)
    token_stats["merge_input_tokens"] = _estimate_tokens(merge_input)
    total_model_calls = 2 * math.ceil(len(selected) / batch_size) + 3 if selected else 0
    metadata = {
        "mode": "dry_run",
        "claim_count": len(selected),
        "batch_size": batch_size,
        "planned_calls": {
            "fact_a": math.ceil(len(selected) / FACT_A_DRY_RUN_BATCH_SIZE) if selected else 0,
            "fact_b": math.ceil(len(selected) / FACT_B_DRY_RUN_BATCH_SIZE) if selected else 0,
            "security": 1 if selected else 0,
            "logic": 1 if selected else 0,
            "merge": 1 if selected else 0,
            "total": (
                (math.ceil(len(selected) / FACT_A_DRY_RUN_BATCH_SIZE)
                 + math.ceil(len(selected) / FACT_B_DRY_RUN_BATCH_SIZE)
                 + 3)
                if selected else 0
            ),
        },
        "fact_batch_plan": {
            "fact_a_batch_size": FACT_A_DRY_RUN_BATCH_SIZE,
            "fact_b_batch_size": FACT_B_DRY_RUN_BATCH_SIZE,
            "fact_a_output_limits": {
                "reasoning_summary_max_chars": 80,
                "limitations_max_chars": 80,
                "json_only": True,
                "no_markdown": True,
                "no_evidence_repetition": True,
                "no_reasoning_chain": True,
            },
        },
        "fact_a_invocation": {
            "response_format": dict(FACT_A_REQUEST_OPTIONS["response_format"]),
            "json_only_instruction": True,
            "compact_fields": ["claim_id", "decision", "recommended_status", "cited_chunk_ids", "reasoning_summary", "limitations"],
            "max_reasoning_chars": 80,
            "evidence_repetition": False,
            "output_parse_status": "not_executed",
        },
        "fact_b_invocation": {"unchanged": True},
        "actual_model_call_count": 0,
        "evidence_network_request_count": retriever.network_request_count,
        "input_token_estimates": token_stats,
        "agent_invocation_config": {
            "security": {
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
                "json_only_instruction": True,
            },
            "logic": {
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
                "timeout_seconds": 180,
                "retry_attempts": 1,
                "json_only_instruction": True,
            },
            "merge": {
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
                "json_only_instruction": True,
            },
        },
        "evidence_compression": {
            "top_k": FACT_TOP_K,
            "chars_per_chunk": FACT_CHARS_PER_CHUNK,
            "max_evidence_chars_per_claim": FACT_MAX_EVIDENCE_CHARS,
        },
        "execution_status": "not_executed",
    }
    artifacts = {
        "claims.json": {"claims": [claim.to_dict() for claim in selected]},
        "evidence-retrieval.json": {"results": retrieval_records, "top_k": 5},
        "fact-review.json": fact_review,
        "security-review.json": security_input,
        "logic-review.json": logic_input,
        "merge-result.json": merge_input,
        "run-metadata.json": metadata,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in artifacts.items():
        (OUTPUT_DIR / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    final_report = (
        "# Rancher Security Review Live Validation\n\n"
        "This artifact was generated by a deterministic dry-run only.\n\n"
        f"- Claims: {len(selected)}\n"
        f"- Evidence retrieval hits: {sum(bool(item['results']) for item in retrieval_records)}/{len(selected)}\n"
        f"- Planned model calls: {total_model_calls}\n"
        "- Actual model calls: 0\n"
        f"- Evidence network requests: {retriever.network_request_count}\n"
        "- Fact, Security, Logic, and Merge execution: not executed\n"
    )
    (OUTPUT_DIR / "final-review-report.md").write_text(final_report, encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--claim-limit", type=int, default=30)
    args = parser.parse_args()
    if args.live and args.dry_run:
        parser.error("choose either --dry-run or --live")
    if not args.live and not args.dry_run:
        parser.error("explicitly pass --dry-run or --live")
    if args.batch_size < 1 or args.claim_limit < 1:
        parser.error("batch size and claim limit must be positive")
    result = run_live(args.batch_size, args.claim_limit) if args.live else run_dry_run(args.batch_size, args.claim_limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
