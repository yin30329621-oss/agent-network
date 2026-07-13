"""Explicit opt-in harness for a small live Fact Evidence OFF/ON evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import time
from typing import Any, Protocol

from agent_network.evidence.fact_evidence import FactEvidenceLimits, build_fact_evidence_context
from agent_network.schemas import ReviewRequest


class LiveAbSafetyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FactEvidenceLiveAbRunConfig:
    enabled: bool = False
    confirm_live_model_calls: bool = False
    model: str | None = None
    temperature: float = 0.0
    max_output_tokens: int = 800
    case_ids: tuple[str, ...] = ()
    max_cases: int = 3
    evidence_off_enabled: bool = True
    evidence_on_enabled: bool = True
    confirm_planned_call_count: int | None = None
    output_directory: str | None = None
    redact_prompts: bool = True
    save_raw_model_response: bool = False


@dataclass(frozen=True, slots=True)
class FactEvidenceLiveAbCase:
    case_id: str
    claim_text: str
    product: str
    component: str
    expected_verdict: str
    expected_evidence_status: str
    expected_document_ids: list[str]
    forbidden_document_ids: list[str]
    evaluation_notes: str
    report_context: str = ""


@dataclass(slots=True)
class FactEvidenceLiveAbCaseResult:
    case_id: str
    mode: str
    model: str
    verdict: str | None
    confidence: float | None
    evidence_status: str | None
    evidence_chunk_ids: list[str]
    evidence_document_ids: list[str]
    evidence_urls: list[str]
    evidence_limitations: list[str]
    validated_reference_count: int
    rejected_reference_count: int
    prompt_character_count: int
    response_character_count: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    model_call_count: int
    network_request_count: int
    latency_ms: float
    error_code: str | None = None
    safe_error_message: str | None = None


@dataclass(slots=True)
class FactEvidenceLiveAbRunResult:
    selected_case_count: int
    planned_fact_model_calls: int
    results: list[FactEvidenceLiveAbCaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_case_count": self.selected_case_count,
            "planned_fact_model_calls": self.planned_fact_model_calls,
            "results": [asdict(item) for item in self.results],
        }


class FactAgentPort(Protocol):
    def review(self, request: ReviewRequest): ...


class FactEvidenceLiveAbEvaluator:
    def __init__(self, fact_agent: FactAgentPort, retriever: Any | None = None) -> None:
        self.fact_agent = fact_agent
        self.retriever = retriever

    def plan(
        self, cases: list[FactEvidenceLiveAbCase], config: FactEvidenceLiveAbRunConfig
    ) -> dict[str, int | bool]:
        selected = self._select(cases, config)
        calls_per_case = int(config.evidence_off_enabled) + int(config.evidence_on_enabled)
        calls = len(selected) * calls_per_case
        return {
            "selected_case_count": len(selected),
            "planned_fact_model_calls": calls,
            "planned_off_calls": len(selected) * int(config.evidence_off_enabled),
            "planned_on_calls": len(selected) * int(config.evidence_on_enabled),
            "maximum_possible_calls": calls,
            "evidence_off_enabled": config.evidence_off_enabled,
            "evidence_on_enabled": config.evidence_on_enabled,
        }

    def run(
        self, cases: list[FactEvidenceLiveAbCase], config: FactEvidenceLiveAbRunConfig
    ) -> FactEvidenceLiveAbRunResult:
        plan = self.plan(cases, config)
        self._require_opt_in(config, int(plan["planned_fact_model_calls"]))
        selected = self._select(cases, config)
        result = FactEvidenceLiveAbRunResult(len(selected), int(plan["planned_fact_model_calls"]))
        for case in selected:
            if config.evidence_off_enabled:
                result.results.append(self._run_case(case, "off", config, None))
            if config.evidence_on_enabled:
                if self.retriever is None:
                    raise LiveAbSafetyError("Evidence ON requires an injected retriever")
                retrieval = self.retriever.retrieve(
                    type("Request", (), {"query_text": case.claim_text})()
                )
                context = build_fact_evidence_context(retrieval, FactEvidenceLimits())
                result.results.append(self._run_case(case, "on", config, context))
        if config.output_directory:
            self._save(result, config.output_directory)
        return result

    def _run_case(self, case, mode, config, context) -> FactEvidenceLiveAbCaseResult:
        request = ReviewRequest(
            markdown=case.report_context or case.claim_text, fact_evidence_context=context
        )
        started = time.monotonic()
        try:
            review = self.fact_agent.review(request)
            audit = getattr(self.fact_agent, "llm", None)
            usage = getattr(audit, "last_response_audit", {}) or {}
            return FactEvidenceLiveAbCaseResult(
                case.case_id,
                mode,
                config.model or "",
                review.summary,
                None,
                review.evidence_status,
                review.evidence_chunk_ids,
                review.evidence_document_ids,
                review.evidence_urls,
                review.evidence_limitations,
                len(review.evidence_chunk_ids),
                len(review.evidence_warnings),
                len(case.claim_text) + (len(json.dumps(context)) if context else 0),
                0,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
                review.model_call_count or 1,
                review.evidence_network_request_count,
                (time.monotonic() - started) * 1000,
            )
        except Exception as exc:
            return FactEvidenceLiveAbCaseResult(
                case.case_id,
                mode,
                config.model or "",
                None,
                None,
                None,
                [],
                [],
                [],
                [],
                0,
                0,
                len(case.claim_text),
                0,
                None,
                None,
                None,
                1,
                0,
                (time.monotonic() - started) * 1000,
                type(exc).__name__,
                "Fact evaluation call failed",
            )

    def _select(self, cases, config):
        selected = [
            case for case in cases if not config.case_ids or case.case_id in config.case_ids
        ]
        return selected[: config.max_cases]

    def _require_opt_in(self, config, planned_calls):
        if not config.enabled or not config.confirm_live_model_calls or not config.model:
            raise LiveAbSafetyError("Live model evaluation is disabled")
        if config.max_cases <= 0 or config.confirm_planned_call_count != planned_calls:
            raise LiveAbSafetyError("Live model call plan was not explicitly confirmed")

    def _save(self, result, output_directory):
        target = Path(output_directory).resolve()
        if "benchmarks" not in target.parts or "results-local" not in target.parts:
            raise LiveAbSafetyError("Live results may only be saved below benchmarks/results-local")
        target.mkdir(parents=True, exist_ok=True)
        (target / "fact-evidence-live-ab.json").write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8"
        )
