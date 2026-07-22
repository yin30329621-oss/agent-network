#!/usr/bin/env python3
"""Case-local dry-run orchestration adapter for live validation."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import re
import sys
import time
from difflib import SequenceMatcher
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
LOGIC_MAX_CLAIM_CHARS = 320
LOGIC_MAX_LIMITATION_CHARS = 80
LOGIC_MAX_REASONING_CHARS = 80
LOGIC_MAX_SECURITY_SUMMARY_CHARS = 240
LOGIC_MAX_SECURITY_FIELD_CHARS = 140
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
    compact_facts = {}
    fact_by_claim: dict[str, dict[str, dict[str, Any]]] = {}
    for reviewer, values in fact_results.items():
        compact_values = []
        for value in values:
            if not isinstance(value, dict):
                continue
            limitations = [
                str(item)[:LOGIC_MAX_LIMITATION_CHARS]
                for item in value.get("limitations", [])
                if str(item).strip()
            ][:1]
            compact_value = {
                "claim_id": value.get("claim_id"),
                "status": value.get("status"),
                "recommended_status": value.get("recommended_status"),
                "cited_chunk_ids": value.get("cited_chunk_ids", []),
                "reasoning_summary": str(value.get("reasoning_summary", ""))[
                    :LOGIC_MAX_REASONING_CHARS
                ],
                "limitations": limitations,
            }
            compact_values.append(compact_value)
            claim_id = str(value.get("claim_id"))
            fact_by_claim.setdefault(claim_id, {})[reviewer] = compact_value
        compact_facts[reviewer] = compact_values

    compact_claims = []
    evidence = []
    for item in fact_inputs:
        claim = item["claim"]
        decision = item.get("decision", {})
        claim_id = str(claim.get("claim_id"))
        fact_pair = fact_by_claim.get(claim_id, {})
        fact_a = fact_pair.get("fact_a", {})
        fact_b = fact_pair.get("fact_b", {})
        disputed = (
            fact_a.get("status") != fact_b.get("status")
            or fact_a.get("recommended_status") != fact_b.get("recommended_status")
            or bool(fact_a.get("limitations"))
            or bool(fact_b.get("limitations"))
        )
        compact_claims.append(
            {
                "claim_id": claim_id,
                "text": str(claim.get("text", ""))[:LOGIC_MAX_CLAIM_CHARS],
                "claim_type": claim.get("claim_type"),
                "verification_status": decision.get("status"),
                "limitations": [
                    str(value)[:LOGIC_MAX_LIMITATION_CHARS]
                    for value in decision.get("limitations", [])
                    if str(value).strip()
                ][:1],
            }
        )
        verification_status = str(decision.get("status") or "").lower()
        needs_evidence = verification_status in {
            "unsupported",
            "contradicted",
            "needs_external_verification",
            "unverifiable",
        }
        if disputed and needs_evidence:
            chunks = item.get("retrieval", {}).get("results", [])[:FACT_TOP_K]
            evidence.append(
                {
                    "claim_id": claim_id,
                    "chunk_ids": [chunk.get("chunk_id") for chunk in chunks],
                    "sources": [chunk.get("document_id") for chunk in chunks],
                }
            )
    security = security_review.to_dict()
    compact_security = {
        "status": security.get("status"),
        "summary": str(security.get("summary", ""))[:LOGIC_MAX_SECURITY_SUMMARY_CHARS],
        "findings": [
            {
                key: (
                    str(finding.get(key, ""))[:LOGIC_MAX_SECURITY_FIELD_CHARS]
                    if key in {"location", "issue", "reason", "evidence_needed", "suggestion"}
                    else finding.get(key)
                )
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


def _claim_ids_in_finding(finding: dict[str, Any]) -> set[str]:
    text = " ".join(
        str(finding.get(key) or "")
        for key in ("location", "issue", "reason", "evidence_needed", "suggestion")
    )
    return set(re.findall(r"claim-[0-9a-f]+", text))


def _fact_status(value: dict[str, Any]) -> str:
    return str(
        value.get("normalized_status")
        or value.get("recommended_status")
        or value.get("decision")
        or value.get("status")
        or "unavailable"
    )


def _fact_reason(value: dict[str, Any]) -> str:
    return str(value.get("reasoning_summary") or "unavailable")


def _display_value(value: object) -> str:
    if value is None or value == "" or value == []:
        return "unavailable"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "unavailable"
    return str(value)


def _claim_reporting_bucket(reconciliation: dict[str, Any]) -> str:
    if reconciliation.get("needs_manual_review") or reconciliation.get("status") == "manual_review_required":
        return "manual_review"
    fact_values = [reconciliation.get("fact_a", {}), reconciliation.get("fact_b", {})]
    statuses = {_fact_status(value) for value in fact_values}
    if "unavailable" in statuses:
        return "manual_review"
    if statuses & {"contradicted", "unsupported"}:
        return "contradicted_or_unsupported"
    limitations = " ".join(
        str(item)
        for value in fact_values
        for item in value.get("limitations", [])
    ).lower()
    if "external" in limitations or "verification" in limitations:
        return "external_verification"
    if statuses == {"supported"}:
        return "supported"
    return "evidence_insufficient"


def _render_finding(finding: dict[str, Any], *, include_agent: bool = True) -> list[str]:
    lines = []
    if include_agent:
        lines.append(f"- Agent: {_display_value(finding.get('agent'))}")
    lines.extend(
        [
            f"  - Severity: {_display_value(finding.get('severity'))}",
            f"  - Location: {_display_value(finding.get('location'))}",
            f"  - Issue: {_display_value(finding.get('issue'))}",
            f"  - Reason: {_display_value(finding.get('reason'))}",
            f"  - Evidence needed: {_display_value(finding.get('evidence_needed'))}",
            f"  - Suggestion: {_display_value(finding.get('suggestion'))}",
            f"  - Status: {_display_value(finding.get('status'))}",
        ]
    )
    return lines


def _render_legacy_report() -> None:
    """Rebuild the user-facing report from existing case-local JSON artifacts."""

    def load(name: str) -> dict[str, Any]:
        return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))

    claims_payload = load("claims.json")
    evidence_payload = load("evidence-retrieval.json")
    fact_payload = load("fact-review.json")
    security_payload = load("security-review.json")
    logic_payload = load("logic-review.json")
    merge_payload = load("merge-result.json")
    metadata = load("run-metadata.json")

    claims = claims_payload.get("claims", [])
    reconciliations = fact_payload.get("reconciliations", [])
    reconciliation_by_id = {item.get("claim_id"): item for item in reconciliations}
    evidence_by_id: dict[str, list[dict[str, Any]]] = {}
    for record in evidence_payload.get("results", []):
        claim_id = record.get("claim_id")
        evidence_by_id[claim_id] = record.get("results", [])

    security_findings = security_payload.get("findings", [])
    logic_findings = logic_payload.get("findings", [])
    merge_findings = merge_payload.get("findings", [])
    all_findings = [
        ("security", finding) for finding in security_findings
    ] + [
        ("logic", finding) for finding in logic_findings
    ] + [
        ("merge", finding) for finding in merge_findings
    ]
    findings_by_claim: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for agent, finding in all_findings:
        for claim_id in _claim_ids_in_finding(finding):
            findings_by_claim.setdefault(claim_id, []).append((agent, finding))

    exact_status_counts = Counter(item.get("status", "unavailable") for item in reconciliations)
    bucket_counts = Counter(_claim_reporting_bucket(item) for item in reconciliations)
    risk_counts = Counter(str(finding.get("severity") or "unavailable") for finding in merge_findings)
    supported_ids: set[str] = set()
    contradicted_ids: set[str] = set()
    evidence_insufficient_ids: set[str] = set()
    external_verification_ids: set[str] = set()
    for reconciliation in reconciliations:
        claim_id = reconciliation.get("claim_id")
        statuses = {
            _fact_status(reconciliation.get("fact_a", {})),
            _fact_status(reconciliation.get("fact_b", {})),
        }
        if statuses == {"supported"}:
            supported_ids.add(claim_id)
        if statuses & {"unsupported", "contradicted"}:
            contradicted_ids.add(claim_id)
        if statuses & {"partially_supported", "unknown", "unavailable"}:
            evidence_insufficient_ids.add(claim_id)
    for claim_id, claim_findings in findings_by_claim.items():
        if any(
            "needs_external_verification" in str(finding.get("evidence_needed") or "")
            for _, finding in claim_findings
        ):
            external_verification_ids.add(claim_id)
    disagreement_ids = [
        item.get("claim_id")
        for item in reconciliations
        if item.get("status") == "reviewer_disagreement"
    ]
    manual_ids = [
        item.get("claim_id")
        for item in reconciliations
        if item.get("needs_manual_review") or item.get("status") == "manual_review_required"
    ]
    evidence_hit_count = sum(bool(evidence_by_id.get(claim.get("claim_id"))) for claim in claims)
    cited_chunk_count = sum(
        len(set(
            chunk_id
            for reviewer in ("fact_a", "fact_b")
            for chunk_id in reconciliation_by_id.get(claim.get("claim_id"), {})
            .get(reviewer, {})
            .get("cited_chunk_ids", [])
        ))
        for claim in claims
    )

    lines = [
        "# Rancher Security Review Live Validation Final Report",
        "",
        "This report was reconstructed from the existing structured case artifacts. "
        "It is a validation output, not a formal security audit conclusion.",
        "",
        "## 1. Executive Summary",
        "",
        f"- Claims reviewed: {metadata.get('claim_count', len(claims))}",
        f"- Evidence retrieval coverage: {evidence_hit_count}/{len(claims)} Claims with retrieval results",
        f"- Cited evidence chunk references: {cited_chunk_count}",
        f"- Fact A/B disagreements: {len(disagreement_ids)}",
        f"- Claims requiring manual review: {len(manual_ids)}",
        f"- Merge findings: {len(merge_findings)}",
        f"- Risk findings: high={risk_counts.get('high', 0)}, medium={risk_counts.get('medium', 0)}, "
        f"low={risk_counts.get('low', 0)}, other={sum(value for key, value in risk_counts.items() if key not in {'high', 'medium', 'low'})}",
        "",
        "### Claim status distribution",
        "",
        "The exact reconciliation statuses and derived reporting buckets are both shown; "
        "derived buckets do not replace the source statuses.",
        "",
        "| Exact reconciliation status | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| {status} | {count} |" for status, count in sorted(exact_status_counts.items()))
    lines.extend(
        [
            "",
            "| Review flag (non-exclusive) | Count |",
            "|---|---:|",
            f"| supported | {len(supported_ids)} |",
            f"| contradicted or unsupported | {len(contradicted_ids)} |",
            f"| evidence insufficient or partially supported | {len(evidence_insufficient_ids)} |",
            f"| external verification requested | {len(external_verification_ids)} |",
            f"| manual review required | {len(manual_ids)} |",
            "",
            "| Primary reporting bucket | Count |",
            "|---|---:|",
        ]
    )
    lines.extend(f"| {status} | {count} |" for status, count in sorted(bucket_counts.items()))

    lines.extend(["", "## 2. Claim-Level Findings", ""])
    for index, claim in enumerate(claims, start=1):
        claim_id = claim.get("claim_id")
        reconciliation = reconciliation_by_id.get(claim_id, {})
        fact_a = reconciliation.get("fact_a", {})
        fact_b = reconciliation.get("fact_b", {})
        fact_a_status = _fact_status(fact_a)
        fact_b_status = _fact_status(fact_b)
        agreement = (
            fact_a_status == fact_b_status
            and fact_a.get("recommended_status") == fact_b.get("recommended_status")
        )
        claim_findings = findings_by_claim.get(claim_id, [])
        claim_evidence = evidence_by_id.get(claim_id, [])
        cited_ids = sorted(set(
            fact_a.get("cited_chunk_ids", []) + fact_b.get("cited_chunk_ids", [])
        ))
        limitations = sorted(set(
            fact_a.get("limitations", []) + fact_b.get("limitations", [])
        ))
        merge_for_claim = [finding for agent, finding in claim_findings if agent == "merge"]
        suggestions = sorted(set(
            str(finding.get("suggestion"))
            for _, finding in claim_findings
            if finding.get("suggestion")
        ))
        lines.extend(
            [
                f"### {index}. {claim_id}",
                "",
                f"- Original Claim: {_display_value(claim.get('text'))}",
                f"- Source location: {_display_value(claim.get('source_location'))}",
                f"- Heading path: {_display_value(claim.get('heading_path'))}",
                f"- Claim priority: {_display_value(claim.get('priority'))}",
                f"- Verification bucket: {_claim_reporting_bucket(reconciliation)}",
                "",
                "#### Fact A / Fact B",
                "",
                "| Field | Fact A | Fact B |",
                "|---|---|---|",
                f"| Decision | {_display_value(fact_a.get('decision'))} | {_display_value(fact_b.get('decision'))} |",
                f"| Recommended status | {_display_value(fact_a.get('recommended_status'))} | {_display_value(fact_b.get('recommended_status'))} |",
                f"| Short reason | {_display_value(_fact_reason(fact_a))} | {_display_value(_fact_reason(fact_b))} |",
                f"| Cited chunk IDs | {_display_value(fact_a.get('cited_chunk_ids'))} | {_display_value(fact_b.get('cited_chunk_ids'))} |",
                f"| Consistent | {str(agreement).lower()} | {str(agreement).lower()} |",
                "",
                "#### Assessments",
                "",
            ]
        )
        for agent_name in ("security", "logic", "merge"):
            related = [finding for agent, finding in claim_findings if agent == agent_name]
            lines.append(f"**{agent_name.title()} assessment:**")
            if not related:
                lines.append("- unavailable: no finding explicitly linked to this Claim ID")
            else:
                for finding in related:
                    lines.extend(_render_finding(finding, include_agent=False))
            lines.append("")
        lines.extend(
            [
                "#### Evidence and limitations",
                "",
                f"- Cited chunk IDs: {_display_value(cited_ids)}",
                f"- Evidence records: {len(claim_evidence)}",
                f"- Evidence document IDs: {_display_value(sorted(set(str(item.get('document_id')) for item in claim_evidence if item.get('document_id'))))}",
                f"- Evidence canonical URLs: {_display_value(sorted(set(str(item.get('canonical_url')) for item in claim_evidence if item.get('canonical_url'))))}",
                f"- Limitations: {_display_value(limitations)}",
                f"- Merge final status: {_display_value([finding.get('status') for finding in merge_for_claim])}",
                f"- Revision suggestion: {_display_value(suggestions)}",
                "",
            ]
        )

    lines.extend(["## 3. Disagreement and Manual Review", ""])
    lines.append("### Fact A/B disagreements")
    lines.append("")
    if not disagreement_ids:
        lines.append("- unavailable: no Fact A/B disagreement was recorded.")
    else:
        for claim_id in disagreement_ids:
            reconciliation = reconciliation_by_id.get(claim_id, {})
            lines.append(
                f"- `{claim_id}`: Fact A={_fact_status(reconciliation.get('fact_a', {}))}; "
                f"Fact B={_fact_status(reconciliation.get('fact_b', {}))}; "
                f"reconciliation={_display_value(reconciliation.get('status'))}."
            )
    lines.extend(["", "### Claims requiring manual review", ""])
    if not manual_ids:
        lines.append("- unavailable: no Claim was marked for manual review.")
    else:
        for claim_id in manual_ids:
            reconciliation = reconciliation_by_id.get(claim_id, {})
            lines.append(
                f"- `{claim_id}`: {_display_value(reconciliation.get('manual_review_reasons'))}"
            )

    lines.extend(["", "## 4. Document Revision Checklist", ""])
    checklist: list[tuple[str, str, str]] = []
    for finding in merge_findings:
        claim_ids = sorted(_claim_ids_in_finding(finding))
        checklist.append(
            (
                str(finding.get("severity") or "unavailable"),
                ", ".join(claim_ids) or "unavailable",
                str(finding.get("suggestion") or finding.get("evidence_needed") or "unavailable"),
            )
        )
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    checklist.sort(key=lambda item: priority_order.get(item[0], 5))
    if not checklist:
        lines.append("- unavailable: no Merge findings were recorded.")
    else:
        for severity, claim_ids, suggestion in checklist:
            lines.append(f"- [{severity}] Claims `{claim_ids}`: {suggestion}")

    lines.extend(["", "## 5. Audit Appendix", ""])
    lines.extend(
        [
            f"- Model allocation: {_display_value(metadata.get('model_names'))}",
            f"- Actual model calls: {_display_value(metadata.get('actual_model_calls'))}",
            f"- Runtime seconds: {_display_value(metadata.get('runtime_seconds'))}",
            f"- Evidence network requests: {_display_value(metadata.get('evidence_network_requests'))}",
            f"- Input token estimates: {_display_value(metadata.get('input_token_estimates'))}",
            f"- Fact isolation: {_display_value(fact_payload.get('isolation'))}",
            f"- Completed agents: {_display_value(metadata.get('completed_agents'))}",
            f"- Failed agent: {_display_value(metadata.get('failed_agent'))}",
            f"- Workflow execution status: {_display_value(metadata.get('execution_status'))}",
            "- Traceability: Claim IDs, cited chunk IDs, document IDs, and canonical URLs are retained where present in the source artifacts.",
        ]
    )
    (OUTPUT_DIR / "final-review-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_report_artifacts() -> dict[str, Any]:
    def load(name: str) -> dict[str, Any]:
        return json.loads((OUTPUT_DIR / name).read_text(encoding="utf-8"))

    return {
        "claims": load("claims.json").get("claims", []),
        "evidence": load("evidence-retrieval.json").get("results", []),
        "fact": load("fact-review.json"),
        "security": load("security-review.json"),
        "logic": load("logic-review.json"),
        "merge": load("merge-result.json"),
        "metadata": load("run-metadata.json"),
    }


def _similar_finding(left: dict[str, Any], right: dict[str, Any]) -> bool:
    def normalized(value: object) -> str:
        return re.sub(r"\W+", "", str(value or "").lower())

    if _claim_ids_in_finding(left) != _claim_ids_in_finding(right):
        return False
    topic_terms = (
        ("etcd", "etcd"),
        ("rbac", "rbac"),
        ("cluster agent", "rbac"),
        ("registration token", "token"),
        ("token", "token"),
        ("cve", "cve"),
        ("authentication", "authentication"),
        ("身份认证", "authentication"),
        ("api server", "api_server"),
    )
    left_text = " ".join(str(left.get(key) or "").lower() for key in ("location", "issue", "suggestion"))
    right_text = " ".join(str(right.get(key) or "").lower() for key in ("location", "issue", "suggestion"))
    left_topics = {topic for term, topic in topic_terms if term in left_text}
    right_topics = {topic for term, topic in topic_terms if term in right_text}
    if left_topics & right_topics:
        return True
    issue_ratio = SequenceMatcher(
        None, normalized(left.get("issue")), normalized(right.get("issue"))
    ).ratio()
    suggestion_ratio = SequenceMatcher(
        None, normalized(left.get("suggestion")), normalized(right.get("suggestion"))
    ).ratio()
    return issue_ratio >= 0.72 and suggestion_ratio >= 0.72


def _deduplicate_findings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for record in records:
        matched = next(
            (group for group in groups if _similar_finding(group["finding"], record["finding"])),
            None,
        )
        if matched is None:
            groups.append(
                {
                    "finding": record["finding"],
                    "sources": [record["agent"]],
                    "source_findings": [record],
                }
            )
        else:
            if record["agent"] not in matched["sources"]:
                matched["sources"].append(record["agent"])
            matched["source_findings"].append(record)
            if record["agent"] == "merge":
                matched["finding"] = record["finding"]
    return groups


def _report_records(artifacts: dict[str, Any]) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    claims = artifacts["claims"]
    reconciliations = artifacts["fact"].get("reconciliations", [])
    reconciliation_by_id = {item.get("claim_id"): item for item in reconciliations}
    evidence_by_id = {
        item.get("claim_id"): item.get("results", []) for item in artifacts["evidence"]
    }
    records = []
    for agent in ("security", "logic", "merge"):
        for finding in artifacts[agent].get("findings", []):
            records.append(
                {
                    "agent": agent,
                    "finding": finding,
                    "claim_ids": _claim_ids_in_finding(finding),
                }
            )
    findings_by_claim: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        for claim_id in record["claim_ids"]:
            findings_by_claim.setdefault(claim_id, []).append(record)
    data = {
        "claims": claims,
        "claim_by_id": {claim.get("claim_id"): claim for claim in claims},
        "reconciliations": reconciliation_by_id,
        "evidence": evidence_by_id,
        "findings": findings_by_claim,
        "all_findings": records,
        "merge_status": artifacts["merge"].get("status", "unavailable"),
        "metadata": artifacts["metadata"],
        "fact_payload": artifacts["fact"],
    }
    return data, findings_by_claim


def _root_causes(
    claim_id: str, reconciliation: dict[str, Any], records: list[dict[str, Any]]
) -> set[str]:
    causes: set[str] = set()
    fact_values = [reconciliation.get("fact_a", {}), reconciliation.get("fact_b", {})]
    statuses = {_fact_status(value) for value in fact_values}
    text = " ".join(
        str(record["finding"].get(key) or "")
        for record in records
        for key in ("issue", "reason", "evidence_needed", "suggestion")
    ).lower()
    limitations = " ".join(
        str(item) for value in fact_values for item in value.get("limitations", [])
    ).lower()
    if reconciliation.get("status") == "reviewer_disagreement":
        causes.add("Reviewer disagreement")
    if not any(value.get("cited_chunk_ids") for value in fact_values):
        causes.add("Evidence missing")
    if "unrelated" in text or "不相关" in text or "不匹配" in text:
        causes.add("Evidence unrelated")
    if "partial" in text or "partially" in text or "部分" in text or "partially_supported" in statuses:
        causes.add("Evidence only partially covers claim")
    if "scope" in text or "多种" in text or "过度" in text or "broad" in text:
        causes.add("Claim scope too broad")
    if ("architecture" in text or "架构" in text) and (
        "needs_external_verification" in text or "external" in limitations
    ):
        causes.add("Architecture assertion lacks direct official support")
    if "needs_external_verification" in text or "external" in limitations:
        causes.add("External verification required")
    if "cve" in text or "outdated" in text or "过时" in text or "版本" in text:
        causes.add("Possible outdated or invalid version/CVE reference")
    if not causes and statuses & {"unknown", "unavailable"}:
        causes.add("Other / Unclassified")
    return causes or {"Other / Unclassified"}


def _state_label(value: object, language: str) -> str:
    raw = str(value or "unavailable")
    if language == "en":
        return raw
    translations = {
        "completed": "已完成",
        "consensus": "达成共识",
        "reviewer_disagreement": "Reviewer 分歧",
        "supported": "支持",
        "partially_supported": "部分支持",
        "unsupported": "不支持",
        "contradicted": "矛盾",
        "manual_review_required": "需要人工复核",
        "valid": "有效",
        "unknown": "未知",
    }
    return f"{translations.get(raw, raw)} ({raw})"


def _token_estimate_value(value: object, language: str) -> object:
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key.endswith("_tokens") and item == 0:
            result[key] = _missing_label(language, "not_recorded")
        else:
            result[key] = _token_estimate_value(item, language)
    return result


def _root_cause_label(value: str, language: str) -> str:
    if language == "en":
        return value
    return {
        "Evidence missing": "缺少证据",
        "Evidence unrelated": "证据与 Claim 不相关",
        "Evidence only partially covers claim": "证据只部分覆盖 Claim",
        "Claim scope too broad": "Claim 论述范围过宽",
        "Architecture assertion lacks direct official support": "架构断言缺少直接官方支持",
        "Reviewer disagreement": "Reviewer 分歧",
        "External verification required": "需要外部验证",
        "Possible outdated or invalid version/CVE reference": "可能过时或无效的版本/CVE 引用",
        "Other / Unclassified": "其他 / 未分类",
    }.get(value, value)


def _missing_label(language: str, kind: str) -> str:
    if language == "en":
        return {
            "security": "No security finding linked",
            "logic": "No logic finding linked",
            "merge": "No merged finding linked",
            "revision": "No explicit revision generated",
            "none": "none",
            "not_recorded": "not recorded",
        }[kind]
    return {
        "security": "未关联安全分析项",
        "logic": "未关联逻辑分析项",
        "merge": "未关联综合分析项",
        "revision": "未生成明确修改建议",
        "none": "无",
        "not_recorded": "未记录",
    }[kind]


def _semantic_value(value: object, language: str, *, null_means_none: bool = False) -> str:
    if value is None or value == "" or value == []:
        return _missing_label(language, "none" if null_means_none else "not_recorded")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or _missing_label(language, "not_recorded")
    return str(value)


def _claim_bucket_flags(claim_id: str, data: dict[str, Any]) -> dict[str, bool]:
    reconciliation = data["reconciliations"].get(claim_id, {})
    statuses = {
        _fact_status(reconciliation.get("fact_a", {})),
        _fact_status(reconciliation.get("fact_b", {})),
    }
    records = data["findings"].get(claim_id, [])
    return {
        "supported": statuses == {"supported"},
        "contradicted": bool(statuses & {"unsupported", "contradicted"}),
        "evidence_insufficient": bool(statuses & {"partially_supported", "unknown", "unavailable"}),
        "external": any(
            "needs_external_verification" in str(record["finding"].get("evidence_needed") or "")
            for record in records
        ),
        "manual": bool(
            reconciliation.get("needs_manual_review")
            or reconciliation.get("status") == "manual_review_required"
        ),
    }


def _chapter_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    chapters: dict[str, list[str]] = {}
    for claim in data["claims"]:
        path = claim.get("heading_path") or [claim.get("section") or "unavailable"]
        chapter = " / ".join(str(item) for item in path)
        chapters.setdefault(chapter, []).append(claim.get("claim_id"))
    output = []
    for chapter, claim_ids in chapters.items():
        flags = [_claim_bucket_flags(claim_id, data) for claim_id in claim_ids]
        disagreements = sum(
            data["reconciliations"].get(claim_id, {}).get("status") == "reviewer_disagreement"
            for claim_id in claim_ids
        )
        manual = sum(flag["manual"] for flag in flags)
        evidence_gaps = sum(flag["evidence_insufficient"] or flag["external"] for flag in flags)
        linked = [record for claim_id in claim_ids for record in data["findings"].get(claim_id, [])]
        deduped = _deduplicate_findings(linked)
        high = any(group["finding"].get("severity") in {"high", "critical"} for group in deduped)
        if manual:
            action = "Manual review required"
        elif high:
            action = "Major rewrite"
        elif evidence_gaps:
            action = "Add evidence"
        elif deduped:
            action = "Revise selected paragraphs"
        else:
            action = "Keep"
        issues = []
        for group in deduped[:3]:
            issue = group["finding"].get("issue")
            if issue and issue not in issues:
                issues.append(str(issue))
        output.append(
            {
                "name": chapter,
                "claim_ids": claim_ids,
                "claim_count": len(claim_ids),
                "consensus": sum(
                    data["reconciliations"].get(claim_id, {}).get("status") == "consensus"
                    for claim_id in claim_ids
                ),
                "disagreement": disagreements,
                "manual": manual,
                "evidence_gaps": evidence_gaps,
                "security": len({record["finding"].get("id") for record in linked if record["agent"] == "security"}),
                "logic": len({record["finding"].get("id") for record in linked if record["agent"] == "logic"}),
                "merge": len({record["finding"].get("id") for record in linked if record["agent"] == "merge"}),
                "issues": issues,
                "action": action,
            }
        )
    return output


def _render_finding_group(group: dict[str, Any], language: str) -> list[str]:
    finding = group["finding"]
    source_finding_ids = sorted(
        {
            str(record["finding"].get("id"))
            for record in group.get("source_findings", [])
            if record["finding"].get("id")
        }
    )
    if language == "en":
        fields = [
            ("Finding ID", finding.get("id")),
            ("Source finding IDs", ", ".join(source_finding_ids)),
            ("Severity", finding.get("severity")),
            ("Location", finding.get("location")),
            ("Issue", finding.get("issue")),
            ("Reason", finding.get("reason")),
            ("Required evidence", finding.get("evidence_needed")),
            ("Suggestion", finding.get("suggestion")),
            ("Status", finding.get("status")),
        ]
        lines = [f"- Sources: {', '.join(group['sources'])}"]
    else:
        fields = [
            ("Finding ID", finding.get("id")),
            ("来源 finding IDs", ", ".join(source_finding_ids)),
            ("严重性", finding.get("severity")),
            ("原文位置", finding.get("location")),
            ("问题", finding.get("issue")),
            ("原因", finding.get("reason")),
            ("所需证据", finding.get("evidence_needed")),
            ("建议", finding.get("suggestion")),
            ("状态", _state_label(finding.get("status"), language)),
        ]
        lines = [f"- 来源：{', '.join(group['sources'])}"]
    lines.extend(f"  - {key}: {_semantic_value(value, language)}" for key, value in fields)
    return lines


def _revision_groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    groups = _deduplicate_findings(data["all_findings"])
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    for group in groups:
        claim_ids = sorted(_claim_ids_in_finding(group["finding"]))
        group["claim_ids"] = claim_ids
        group["manual"] = any(
            _claim_bucket_flags(claim_id, data)["manual"] for claim_id in claim_ids
        )
        group["direct_evidence_gap"] = "needs_external_verification" in str(
            group["finding"].get("evidence_needed") or ""
        )
        group["source_location"] = ", ".join(
            str(data["claim_by_id"].get(claim_id, {}).get("source_location") or "unavailable")
            for claim_id in claim_ids
        )
    groups.sort(
        key=lambda group: (
            priority_order.get(str(group["finding"].get("severity") or "info"), 5),
            not group["manual"],
            not group["direct_evidence_gap"],
            group["source_location"],
        )
    )
    return groups


def _revision_chapters(group: dict[str, Any], data: dict[str, Any]) -> str:
    chapters = []
    for claim_id in group["claim_ids"]:
        path = data["claim_by_id"].get(claim_id, {}).get("heading_path") or []
        chapter = str(path[-1]) if path else str(data["claim_by_id"].get(claim_id, {}).get("section") or "not recorded")
        if chapter not in chapters:
            chapters.append(chapter)
    return "; ".join(chapters) or "not recorded"


def _render_revision_plan(data: dict[str, Any], groups: list[dict[str, Any]], language: str) -> list[str]:
    if language == "en":
        lines = [
            "## Prioritized Revision Plan",
            "",
            "Each priority item is rendered as a card to keep the actionable revision visible in GitHub and VS Code previews. Full source locations remain in the Claim appendix.",
            "",
            "Deduplication groups findings when Claim ID sets match and issue/suggestion similarity is at least 0.72. Sources and source finding IDs are retained; original JSON findings are unchanged.",
        ]
        for index, group in enumerate(groups, start=1):
            finding = group["finding"]
            signals = [
                f"{claim_id}: {_fact_status(data['reconciliations'].get(claim_id, {}).get('fact_a', {}))}/{_fact_status(data['reconciliations'].get(claim_id, {}).get('fact_b', {}))}"
                for claim_id in group["claim_ids"]
            ]
            source_ids = sorted(
                {
                    str(record["finding"].get("id"))
                    for record in group.get("source_findings", [])
                    if record["finding"].get("id")
                }
            )
            lines.extend(
                [
                    "",
                    f"### Priority {index} — {finding.get('severity', 'not recorded')}",
                    "",
                    f"- **Section:** {_revision_chapters(group, data)}",
                    f"- **Source location:** {group['source_location'] or 'not recorded'}",
                    f"- **Claim IDs:** {', '.join(group['claim_ids']) or 'not recorded'}",
                    f"- **Reviewer signals:** {'; '.join(signals) or 'not recorded'}",
                    f"- **Current issue:** {finding.get('issue') or 'not recorded'}",
                    f"- **Required evidence:** {finding.get('evidence_needed') or 'not recorded'}",
                    f"- **Recommended revision:** {finding.get('suggestion') or 'No explicit revision generated'}",
                    f"- **Sources:** {', '.join(group['sources']) or 'not recorded'}",
                    f"- **Source finding IDs:** {', '.join(source_ids) or 'not recorded'}",
                ]
            )
        return lines

    action_labels = {
        "Keep": "保留",
        "Add evidence": "补充证据",
        "Narrow claims": "缩小论述范围",
        "Revise selected paragraphs": "修改部分段落",
        "Major rewrite": "建议重点重写",
        "Manual review required": "需要人工复核",
    }
    lines = [
        "## 优先修改计划",
        "",
        "以下采用卡片式布局，便于在 GitHub 和 VS Code 预览中阅读；完整 source_location 保留在 Claim 审计附录。",
        "",
        "去重规则：Claim ID 集合相同且 issue/suggestion 相似度至少为 0.72；保留来源和 source finding ID，不修改原始 JSON findings。",
    ]
    for index, group in enumerate(groups, start=1):
        finding = group["finding"]
        signals = [
            f"{claim_id}：{_state_label(_fact_status(data['reconciliations'].get(claim_id, {}).get('fact_a', {})), language)}/{_state_label(_fact_status(data['reconciliations'].get(claim_id, {}).get('fact_b', {})), language)}"
            for claim_id in group["claim_ids"]
        ]
        source_ids = sorted(
            {
                str(record["finding"].get("id"))
                for record in group.get("source_findings", [])
                if record["finding"].get("id")
            }
        )
        lines.extend(
            [
                "",
                f"### 优先级 {index} — {finding.get('severity', '未记录')}",
                "",
                f"- **章节：** {_revision_chapters(group, data)}",
                f"- **原文位置：** {group['source_location'] or '未记录'}",
                f"- **Claim IDs：** {', '.join(group['claim_ids']) or '未记录'}",
                f"- **Reviewer 信号：** {'；'.join(signals) or '未记录'}",
                f"- **当前问题：** {finding.get('issue') or '未记录'}",
                f"- **所需证据：** {finding.get('evidence_needed') or '未记录'}",
                f"- **建议修改：** {finding.get('suggestion') or '未生成明确修改建议'}",
                f"- **建议动作：** {action_labels.get('Manual review required' if group['manual'] else 'Add evidence' if group['direct_evidence_gap'] else 'Revise selected paragraphs', '未记录')}",
                f"- **来源：** {', '.join(group['sources']) or '未记录'}",
                f"- **来源 finding IDs：** {', '.join(source_ids) or '未记录'}",
            ]
        )
    return lines


def _render_executive_summary(
    data: dict[str, Any],
    claims: list[dict[str, Any]],
    revision_groups: list[dict[str, Any]],
    root_counts: Counter[str],
    disagreement_count: int,
    manual_count: int,
    evidence_coverage: int,
    language: str,
) -> list[str]:
    if language == "en":
        lines = [
            "# Rancher Security Review v0.4.1 Executive Summary",
            "",
            "This summary is renderer-derived from existing JSON artifacts. It does not replace Fact A/B, Security, Logic, or Merge conclusions.",
            "",
            "## Overall Audit Conclusion",
            "",
            f"The review covers {len(claims)} Claims. Evidence retrieval is present for {evidence_coverage}/{len(claims)} Claims; {disagreement_count} Claims have Fact A/B disagreement and {manual_count} require manual review. These signals identify review and evidence gaps, not confirmed factual errors.",
            "",
            "## Key Statistics",
            "",
            f"- Claims: {len(claims)}",
            f"- Consensus: {len(claims) - disagreement_count}",
            f"- Fact A/B disagreement: {disagreement_count}",
            f"- Manual review required: {manual_count}",
            f"- Evidence retrieval coverage: {evidence_coverage}/{len(claims)}",
            "",
            "## Top Risk Categories",
            "",
        ]
        lines.extend(f"- {key}: {value}" for key, value in root_counts.most_common(8))
        lines.extend(["", "## Highest-Priority Document Revisions", ""])
        for index, group in enumerate(revision_groups[:5], start=1):
            finding = group["finding"]
            lines.extend(
                [
                    f"### P{index} {finding.get('severity', 'not recorded')}",
                    "",
                    f"- **Affected Claims:** {', '.join(group['claim_ids']) or 'not recorded'}",
                    f"- **Section:** {_revision_chapters(group, data)}",
                    f"- **Recommended revision:** {finding.get('suggestion') or 'No explicit revision generated'}",
                    "",
                ]
            )
        return lines

    lines = [
        "# Rancher 安全审查 v0.4.1 执行摘要",
        "",
        "本摘要由现有 JSON artifacts 经 renderer 派生生成，不替代 Fact A/B、Security、Logic 或 Merge 原始结论。",
        "",
        "## 总体审计结论",
        "",
        f"本次审查覆盖 {len(claims)} 个 Claim；{evidence_coverage}/{len(claims)} 个 Claim 存在 Evidence 检索记录，{disagreement_count} 个 Claim 存在 Fact A/B 分歧，{manual_count} 个 Claim 需要人工复核。这些信号表示审查或证据缺口，不等于已确认事实错误。",
        "",
        "## 核心统计",
        "",
        f"- Claim 数量：{len(claims)}",
        f"- Consensus：{len(claims) - disagreement_count}",
        f"- Fact A/B 分歧：{disagreement_count}",
        f"- 需要人工复核：{manual_count}",
        f"- Evidence 检索覆盖：{evidence_coverage}/{len(claims)}",
        "",
        "## 主要风险类别",
        "",
    ]
    lines.extend(f"- {_root_cause_label(key, language)}：{value}" for key, value in root_counts.most_common(8))
    lines.extend(["", "## 最高优先级文档修改", ""])
    for index, group in enumerate(revision_groups[:5], start=1):
        finding = group["finding"]
        lines.extend(
            [
                f"### P{index} {finding.get('severity', '未记录')}",
                "",
                f"- **涉及 Claim：** {', '.join(group['claim_ids']) or '未记录'}",
                f"- **章节：** {_revision_chapters(group, data)}",
                f"- **建议修改：** {finding.get('suggestion') or '未生成明确修改建议'}",
                "",
            ]
        )
    return lines


def _render_chapter_review(chapters: list[dict[str, Any]], language: str) -> list[str]:
    action_labels = {
        "Keep": "保留",
        "Add evidence": "补充证据",
        "Narrow claims": "缩小论述范围",
        "Revise selected paragraphs": "修改部分段落",
        "Major rewrite": "建议重点重写",
        "Manual review required": "需要人工复核",
    }
    if language == "en":
        lines = ["## Chapter-Level Review", "", "Chapter statistics and actions are renderer-derived and do not label an entire chapter as wrong."]
        for chapter in chapters:
            lines.extend(
                [
                    "",
                    f"### {chapter['name']}",
                    "",
                    f"- **Claim count:** {chapter['claim_count']}",
                    f"- **Consensus:** {chapter['consensus']}",
                    f"- **Disagreement:** {chapter['disagreement']}",
                    f"- **Evidence gaps:** {chapter['evidence_gaps']}",
                    f"- **Main issues:** {'; '.join(chapter['issues']) or 'No linked finding'}",
                    f"- **Recommended action:** {chapter['action']}",
                ]
            )
        return lines
    lines = ["## 章节级审查", "", "章节统计和动作均为 renderer 派生结果，不将整章直接判定为错误。"]
    for chapter in chapters:
        lines.extend(
            [
                "",
                f"### {chapter['name']}",
                "",
                f"- **Claim 数量：** {chapter['claim_count']}",
                f"- **Consensus：** {chapter['consensus']}",
                f"- **分歧：** {chapter['disagreement']}",
                f"- **证据缺口：** {chapter['evidence_gaps']}",
                f"- **主要问题：** {'；'.join(chapter['issues']) or '未关联分析项'}",
                f"- **建议动作：** {action_labels.get(chapter['action'], chapter['action'])}",
            ]
        )
    return lines


def _render_report(language: str) -> str:
    artifacts = _load_report_artifacts()
    data, _ = _report_records(artifacts)
    claims = data["claims"]
    metadata = data["metadata"]
    chapters = _chapter_data(data)
    revision_groups = _revision_groups(data)
    merge_findings = artifacts["merge"].get("findings", [])
    reconciliations = list(data["reconciliations"].values())
    disagreement_count = sum(item.get("status") == "reviewer_disagreement" for item in reconciliations)
    manual_count = sum(_claim_bucket_flags(item.get("claim_id"), data)["manual"] for item in reconciliations)
    evidence_coverage = sum(bool(data["evidence"].get(claim.get("claim_id"))) for claim in claims)
    root_counts = Counter(
        cause
        for item in reconciliations
        for cause in _root_causes(
            item.get("claim_id"),
            item,
            data["findings"].get(item.get("claim_id"), []),
        )
    )
    flag_counts = Counter()
    for claim in claims:
        flags = _claim_bucket_flags(claim.get("claim_id"), data)
        for key, enabled in flags.items():
            if enabled:
                flag_counts[key] += 1
    risk_counts = Counter(str(item.get("severity") or "unavailable") for item in merge_findings)
    if language == "en":
        title = "Rancher Security Review Live Validation Final Report"
        toc = [
            ("Executive Summary", "executive-summary"),
            ("Top Priority Findings", "top-priority-findings"),
            ("Chapter-Level Review", "chapter-level-review"),
            ("Prioritized Revision Plan", "prioritized-revision-plan"),
            ("Claim-Level Audit Appendix", "claim-level-audit-appendix"),
            ("Audit Appendix", "audit-appendix"),
        ]
        lines = [f"# {title}", "", "This report is reconstructed from existing JSON artifacts. It is a validation output, not a formal security audit conclusion.", "", "## Table of Contents", ""]
        lines.extend(f"- [{name}](#{anchor})" for name, anchor in toc)
        lines.extend(["", "## Quick Navigation", "", "- Review findings are prioritized before the full Claim appendix.", "- Chapter statistics are renderer-derived and do not declare an entire chapter incorrect.", "- Reviewer Signals are not final factual-error conclusions.", "", "## Executive Summary", "", "### Overall Review Summary", "", f"- Claims reviewed: {len(claims)}", f"- Evidence retrieval coverage: {evidence_coverage}/{len(claims)}", f"- Fact A/B disagreements: {disagreement_count}", f"- Manual review required: {manual_count}", f"- Merge findings: {len(merge_findings)}", f"- Risk findings: high={risk_counts.get('high', 0)}, medium={risk_counts.get('medium', 0)}, low={risk_counts.get('low', 0)}, other={sum(value for key, value in risk_counts.items() if key not in {'high', 'medium', 'low'})}", "", "### Top Review Signals", ""])
        lines.extend([
            f"- Claims with at least one unsupported or contradicted reviewer signal: {flag_counts['contradicted']}",
            f"- Claims with evidence insufficiency or partial coverage signals: {flag_counts['evidence_insufficient']}",
            f"- Claims requiring external verification: {flag_counts['external']}",
            f"- Claims requiring manual review: {flag_counts['manual']}",
        ])
        lines.extend(["", "### Top Root Causes", ""])
        lines.extend(f"- {key}: {value}" for key, value in root_counts.most_common(8))
        lines.extend(["", "### Highest-Priority Document Issues", ""])
        for group in revision_groups[:5]:
            lines.append(f"- [{group['finding'].get('severity', 'unavailable')}] {', '.join(group['claim_ids']) or 'unavailable'}: {group['finding'].get('suggestion') or group['finding'].get('evidence_needed') or 'No explicit revision generated'}")
        lines.extend(["", "### Manual Review Overview", "", f"- {manual_count} Claims are marked for manual review by the Fact reconciliation artifact.", "- Manual review is triggered by reviewer disagreement; it does not prove either reviewer is factually correct."])
        lines.extend([""])
        lines.extend(_render_chapter_review(chapters, language))
        lines.extend(["", "### Chapter Main Issues and Recommended Actions", ""])
        for chapter in chapters:
            lines.append(f"- **{chapter['name']}** — {', '.join(chapter['issues']) or 'No linked finding'}; action: {chapter['action']}.")
        lines.extend([""])
        lines.extend(_render_revision_plan(data, revision_groups, language))
        lines.extend(["", "## Top Priority Findings", ""])
        for group in revision_groups[:5]:
            lines.extend(_render_finding_group(group, language))
            lines.append("")
        lines.extend(["## Claim-Level Audit Appendix", ""])
    else:
        title = "Rancher 安全审查 Live Validation 最终报告"
        toc = [("执行摘要", "执行摘要"), ("高优先级发现", "高优先级发现"), ("章节级审查", "章节级审查"), ("优先修改计划", "优先修改计划"), ("Claim 审计附录", "claim-审计附录"), ("审计附录", "审计附录")]
        lines = [f"# {title}", "", "本报告基于现有 JSON artifacts 重建，不调用模型、不发起网络请求；报告是验证输出，不构成正式安全审计结论。", "", "## 目录", ""]
        lines.extend(f"- [{name}](#{anchor})" for name, anchor in toc)
        lines.extend(["", "## 快速导航", "", "- 前半部分先展示高优先级问题和章节统计，后半部分保留全部 Claim 追溯信息。", "- 章节结论是 renderer 派生统计，不代表整章错误。", "- Reviewer 信号不等于最终事实错误结论。", "", "## 执行摘要", "", "### 总体审查摘要", "", f"- Claim 数量：{len(claims)}", f"- Evidence 检索覆盖：{evidence_coverage}/{len(claims)}", f"- Fact A/B 分歧：{disagreement_count}", f"- 需要人工复核：{manual_count}", f"- Merge findings：{len(merge_findings)}", f"- 风险发现：高={risk_counts.get('high', 0)}，中={risk_counts.get('medium', 0)}，低={risk_counts.get('low', 0)}，其他={sum(value for key, value in risk_counts.items() if key not in {'high', 'medium', 'low'})}", "", "### 主要 Reviewer 信号", ""])
        lines.extend([
            f"- 至少收到一个‘不支持’或‘矛盾’Reviewer 信号的 Claim：{flag_counts['contradicted']}",
            f"- 存在证据不足或部分覆盖信号的 Claim：{flag_counts['evidence_insufficient']}",
            f"- 需要外部验证的 Claim：{flag_counts['external']}",
            f"- 需要人工复核的 Claim：{flag_counts['manual']}",
        ])
        lines.extend(["", "### 主要根因", ""])
        lines.extend(f"- {_root_cause_label(key, language)}：{value}" for key, value in root_counts.most_common(8))
        lines.extend(["", "### 最高优先级文档问题", ""])
        for group in revision_groups[:5]:
            lines.append(f"- [{group['finding'].get('severity', 'unavailable')}] {', '.join(group['claim_ids']) or 'unavailable'}：{group['finding'].get('suggestion') or group['finding'].get('evidence_needed') or '未生成明确修改建议'}")
        lines.extend(["", "### 人工复核概览", "", f"- Fact reconciliation 将 {manual_count} 个 Claim 标记为需要人工复核。", "- 当前触发原因是 Reviewer 分歧；这不证明任何一方已经得出最终事实结论。"])
        lines.extend([""])
        lines.extend(_render_chapter_review(chapters, language))
        lines.extend(["", "### 章节主要问题与建议动作", ""])
        action_labels = {
            "Keep": "保留",
            "Add evidence": "补充证据",
            "Narrow claims": "缩小论述范围",
            "Revise selected paragraphs": "修改部分段落",
            "Major rewrite": "建议重点重写",
            "Manual review required": "需要人工复核",
        }
        for chapter in chapters:
            lines.append(f"- **{chapter['name']}**：{ '；'.join(chapter['issues']) or '未关联分析项'}；建议动作：{action_labels.get(chapter['action'], chapter['action'])}。")
        lines.extend([""])
        lines.extend(_render_revision_plan(data, revision_groups, language))
        lines.extend(["", "## 高优先级发现", ""])
        for group in revision_groups[:5]:
            lines.extend(_render_finding_group(group, language))
            lines.append("")
        lines.extend(["## Claim 审计附录", ""])

    for index, claim in enumerate(claims, start=1):
        claim_id = claim.get("claim_id")
        reconciliation = data["reconciliations"].get(claim_id, {})
        fact_a = reconciliation.get("fact_a", {})
        fact_b = reconciliation.get("fact_b", {})
        claim_records = data["findings"].get(claim_id, [])
        finding_groups = _deduplicate_findings(claim_records)
        flags = _claim_bucket_flags(claim_id, data)
        agreement = _fact_status(fact_a) == _fact_status(fact_b) and fact_a.get("recommended_status") == fact_b.get("recommended_status")
        evidence_items = data["evidence"].get(claim_id, [])
        cited_ids = sorted(set(fact_a.get("cited_chunk_ids", []) + fact_b.get("cited_chunk_ids", [])))
        limitations = sorted(set(fact_a.get("limitations", []) + fact_b.get("limitations", [])))
        if language == "en":
            lines.extend([f"### {index}. {claim_id}", "", "#### Claim Metadata", "", f"- Claim ID: {claim_id}", f"- Original Claim: {claim.get('text') or 'unavailable'}", f"- Source location: {claim.get('source_location') or 'unavailable'}", f"- Heading path: {', '.join(str(item) for item in claim.get('heading_path', [])) or 'unavailable'}", f"- Priority: {claim.get('priority') or 'unavailable'}", "", "#### Verification Summary", "", f"- Primary reporting bucket: {_claim_reporting_bucket(reconciliation)}", f"- Reconciliation status: {reconciliation.get('status') or 'unavailable'}", f"- Manual review required: {str(flags['manual']).lower()}", f"- Combined summary: Fact A={_fact_status(fact_a)}; Fact B={_fact_status(fact_b)}; Reviewer Signal is not a final factual-error conclusion.", "", "#### Fact A / Fact B", "", "| Field | Fact A | Fact B |", "|---|---|---|", f"| Decision | {fact_a.get('decision') or 'unavailable'} | {fact_b.get('decision') or 'unavailable'} |", f"| Recommended status | {fact_a.get('recommended_status') or 'unavailable'} | {fact_b.get('recommended_status') or 'unavailable'} |", f"| Short reason | {_fact_reason(fact_a)} | {_fact_reason(fact_b)} |", f"| Cited chunk IDs | {', '.join(fact_a.get('cited_chunk_ids', [])) or 'unavailable'} | {', '.join(fact_b.get('cited_chunk_ids', [])) or 'unavailable'} |", f"| Agreement | {str(agreement).lower()} | {str(agreement).lower()} |", "", "#### Related Assessments", ""])
            labels = {"security": "Security", "logic": "Logic", "merge": "Merge"}
        else:
            lines.extend([f"### {index}. {claim_id}", "", "#### Claim 元数据", "", f"- Claim ID：{claim_id}", f"- Original Claim：{claim.get('text') or '不可用'}", f"- 原文位置：{claim.get('source_location') or '不可用'}", f"- Heading path：{', '.join(str(item) for item in claim.get('heading_path', [])) or '不可用'}", f"- 优先级：{claim.get('priority') or '不可用'}", "", "#### 验证摘要", "", f"- Primary reporting bucket：{_state_label(_claim_reporting_bucket(reconciliation), language)}", f"- Reconciliation status：{_state_label(reconciliation.get('status'), language)}", f"- 人工复核状态：{'需要人工复核 (manual_review)' if flags['manual'] else '无 (none)'}", f"- 综合摘要：Fact A={_state_label(_fact_status(fact_a), language)}；Fact B={_state_label(_fact_status(fact_b), language)}；Reviewer 信号不等于最终事实错误结论。", "", "#### Fact A / Fact B", "", "| 字段 | Fact A | Fact B |", "|---|---|---|", f"| Decision | {_state_label(fact_a.get('decision'), language)} | {_state_label(fact_b.get('decision'), language)} |", f"| Recommended status | {_state_label(fact_a.get('recommended_status'), language)} | {_state_label(fact_b.get('recommended_status'), language)} |", f"| 简短理由 | {fact_a.get('reasoning_summary') or '不可用'} | {fact_b.get('reasoning_summary') or '不可用'} |", f"| Cited chunk IDs | {', '.join(fact_a.get('cited_chunk_ids', [])) or '不可用'} | {', '.join(fact_b.get('cited_chunk_ids', [])) or '不可用'} |", f"| 一致性 | {str(agreement).lower()} | {str(agreement).lower()} |", "", "#### 关联分析", ""])
            labels = {"security": "Security 安全分析", "logic": "Logic 逻辑分析", "merge": "Merge 综合分析"}
        for agent in ("security", "logic", "merge"):
            related = [record for record in finding_groups if agent in record["sources"]]
            lines.append(f"**{labels[agent]}：**")
            if not related:
                lines.append(f"- {_missing_label(language, agent)}")
            else:
                for group in related:
                    owner = group["sources"][0]
                    if owner == agent:
                        lines.extend(_render_finding_group(group, language))
                    elif language == "en":
                        lines.append(
                            f"- Finding rendered under {owner.title()}; sources: "
                            f"{', '.join(group['sources'])}"
                        )
                    else:
                        lines.append(
                            f"- 该 finding 已在 {owner.title()} 下聚合展示；来源："
                            f"{', '.join(group['sources'])}"
                        )
            lines.append("")
        merge_related = [group for group in finding_groups if "merge" in group["sources"]]
        merge_status = data["merge_status"]
        lines.extend(["#### Evidence and Revision" if language == "en" else "#### Evidence 与修改建议", ""])
        if language == "en":
            lines.extend([f"- Merge workflow status: {merge_status}", f"- Related merged finding status: {', '.join(str(group['finding'].get('status')) for group in merge_related) or 'No merged finding linked'}", f"- Cited chunk IDs: {', '.join(cited_ids) or 'not recorded'}", f"- Evidence records: {len(evidence_items)}", f"- Document IDs: {', '.join(sorted(set(str(item.get('document_id')) for item in evidence_items if item.get('document_id')))) or 'not recorded'}", f"- Canonical URLs: {', '.join(sorted(set(str(item.get('canonical_url')) for item in evidence_items if item.get('canonical_url')))) or 'not recorded'}", f"- Limitations: {', '.join(limitations) or 'none'}", f"- Recommended revision: {', '.join(sorted(set(str(group['finding'].get('suggestion')) for group in finding_groups if group['finding'].get('suggestion')))) or 'No explicit revision generated'}", ""])
        else:
            lines.extend([f"- Merge workflow status：{_state_label(merge_status, language)}", f"- 关联综合 finding 状态：{', '.join(_state_label(group['finding'].get('status'), language) for group in merge_related) or '未关联综合分析项'}", f"- Cited chunk IDs：{', '.join(cited_ids) or '未记录'}", f"- Evidence records：{len(evidence_items)}", f"- Document IDs：{', '.join(sorted(set(str(item.get('document_id')) for item in evidence_items if item.get('document_id')))) or '未记录'}", f"- Canonical URLs：{', '.join(sorted(set(str(item.get('canonical_url')) for item in evidence_items if item.get('canonical_url')))) or '未记录'}", f"- Limitations：{', '.join(limitations) or '无'}", f"- 建议修改：{', '.join(sorted(set(str(group['finding'].get('suggestion')) for group in finding_groups if group['finding'].get('suggestion')))) or '未生成明确修改建议'}", ""])

    if language == "en":
        lines.extend(["## Audit Appendix", "", f"- Model allocation: {metadata.get('model_names') or 'not recorded'}", f"- Actual model calls: {metadata.get('actual_model_calls', 'not recorded')}", f"- Runtime seconds: {metadata.get('runtime_seconds', 'not recorded')}", f"- Evidence network requests: {metadata.get('evidence_network_requests', 'not recorded')}", f"- Input token estimates: {_token_estimate_value(metadata.get('input_token_estimates'), language)}", f"- Fact isolation: {artifacts['fact'].get('isolation') or 'not recorded'}", f"- Failed agent: {_missing_label(language, 'none') if metadata.get('failed_agent') is None else metadata.get('failed_agent')}", f"- Completed agents: {', '.join(metadata.get('completed_agents', [])) or 'not recorded'}", "- Root causes, chapter actions, priority, and deduplication are renderer-derived statistics; they do not replace original Agent statuses.", ""])
    else:
        lines.extend(["## 审计附录", "", f"- 模型分配：{metadata.get('model_names') or '未记录'}", f"- 实际模型调用：{metadata.get('actual_model_calls', '未记录')}", f"- Runtime 秒数：{metadata.get('runtime_seconds', '未记录')}", f"- Evidence 网络请求：{metadata.get('evidence_network_requests', '未记录')}", f"- Token 估算：{_token_estimate_value(metadata.get('input_token_estimates'), language)}", f"- Fact isolation：{artifacts['fact'].get('isolation') or '未记录'}", f"- 失败 Agent：{'无 (none)' if metadata.get('failed_agent') is None else metadata.get('failed_agent')}", f"- 已完成 Agent：{', '.join(metadata.get('completed_agents', [])) or '未记录'}", "- 根因、章节动作、优先级和去重结果均为 renderer 派生统计，不替代原始 Agent 状态。", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_chinese_final_report() -> None:
    """Render the Chinese report from the same artifacts used by the English report."""

    (OUTPUT_DIR / "final-review-report.zh-CN.md").write_text(
        _render_report("zh-CN"), encoding="utf-8"
    )


def _render_auxiliary_reports() -> None:
    artifacts = _load_report_artifacts()
    data, _ = _report_records(artifacts)
    claims = data["claims"]
    revision_groups = _revision_groups(data)
    reconciliations = list(data["reconciliations"].values())
    disagreement_count = sum(item.get("status") == "reviewer_disagreement" for item in reconciliations)
    manual_count = sum(_claim_bucket_flags(item.get("claim_id"), data)["manual"] for item in reconciliations)
    evidence_coverage = sum(bool(data["evidence"].get(claim.get("claim_id"))) for claim in claims)
    root_counts = Counter(
        cause
        for item in reconciliations
        for cause in _root_causes(
            item.get("claim_id"),
            item,
            data["findings"].get(item.get("claim_id"), []),
        )
    )
    (OUTPUT_DIR / "executive-summary.md").write_text(
        "\n".join(
            _render_executive_summary(
                data,
                claims,
                revision_groups,
                root_counts,
                disagreement_count,
                manual_count,
                evidence_coverage,
                "en",
            )
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "executive-summary.zh-CN.md").write_text(
        "\n".join(
            _render_executive_summary(
                data,
                claims,
                revision_groups,
                root_counts,
                disagreement_count,
                manual_count,
                evidence_coverage,
                "zh-CN",
            )
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "revision-plan.md").write_text(
        "\n".join(_render_revision_plan(data, revision_groups, "en")).rstrip() + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "revision-plan.zh-CN.md").write_text(
        "\n".join(_render_revision_plan(data, revision_groups, "zh-CN")).rstrip() + "\n",
        encoding="utf-8",
    )


def render_final_report() -> None:
    """Render both language reports without model or network calls."""

    (OUTPUT_DIR / "final-review-report.md").write_text(
        _render_report("en"), encoding="utf-8"
    )
    render_chinese_final_report()
    _render_auxiliary_reports()


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
    render_final_report()
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
