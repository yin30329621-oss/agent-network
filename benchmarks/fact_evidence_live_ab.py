"""Explicit opt-in harness for a small live Fact Evidence OFF/ON evaluation.

The module is deliberately safe to import and execute in plan mode.  Live
model calls require both command-line confirmations and an explicit model.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import queue
import threading
import time
from typing import Any, Protocol

from agent_network.evidence.fact_evidence import FactEvidenceLimits, build_fact_evidence_context
from agent_network.evidence.official_evidence_retriever import (
    OfficialEvidenceRetrievalRequest,
    OfficialEvidenceRetrievalResult,
    RetrievedOfficialEvidence,
)
from agent_network.schemas import ReviewRequest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE_DIRECTORY = PROJECT_ROOT / "benchmarks" / "fixtures" / "fact-evidence-live-ab-v1"
RESULTS_ROOT = PROJECT_ROOT / "benchmarks" / "results-local"


class LiveAbSafetyError(RuntimeError):
    """Raised before an unsafe or unconfirmed live benchmark action."""


@dataclass(frozen=True, slots=True)
class FactEvidenceLiveAbRunConfig:
    enabled: bool = False
    confirm_live_model_calls: bool = False
    model: str | None = None
    temperature: float = 0.0
    max_output_tokens: int = 800
    timeout_seconds: float = 100.0
    case_ids: tuple[str, ...] = ()
    max_cases: int = 3
    evidence_off_enabled: bool = True
    evidence_on_enabled: bool = True
    confirm_planned_call_count: int | None = None
    output_directory: str | None = None
    save_results: bool = False
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


@dataclass(frozen=True, slots=True)
class FactEvidenceLiveAbFixture:
    cases: list[FactEvidenceLiveAbCase]
    metadata: dict[str, Any]
    human_review_template: dict[str, Any]
    evidence_by_case_id: dict[str, list[dict[str, Any]]]


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


def load_live_ab_fixture(
    fixture_directory: Path = DEFAULT_FIXTURE_DIRECTORY,
) -> FactEvidenceLiveAbFixture:
    """Load only the fixed local live A/B fixture in its declared order."""
    cases_data = _load_json(fixture_directory / "cases.json")
    metadata = _load_json(fixture_directory / "metadata.json")
    template = _load_json(fixture_directory / "human-review-template.json")
    evidence_path = fixture_directory / "evidence.json"
    evidence = _load_json(evidence_path) if evidence_path.exists() else {}
    if not isinstance(cases_data, list):
        raise ValueError("Live A/B cases fixture must be a JSON list")
    cases = [FactEvidenceLiveAbCase(**item) for item in cases_data]
    _validate_case_ids(cases)
    if (
        not isinstance(metadata, dict)
        or not isinstance(template, dict)
        or not isinstance(evidence, dict)
    ):
        raise ValueError("Live A/B fixture metadata must be JSON objects")
    return FactEvidenceLiveAbFixture(cases, metadata, template, evidence)


def load_live_ab_cases(
    fixture_directory: Path = DEFAULT_FIXTURE_DIRECTORY,
    *,
    case_ids: tuple[str, ...] = (),
) -> list[FactEvidenceLiveAbCase]:
    fixture = load_live_ab_fixture(fixture_directory)
    if not case_ids:
        return fixture.cases
    available = {case.case_id for case in fixture.cases}
    unknown = [case_id for case_id in case_ids if case_id not in available]
    if unknown:
        raise ValueError(f"Unknown live A/B case_id: {unknown[0]}")
    requested = set(case_ids)
    return [case for case in fixture.cases if case.case_id in requested]


class FixtureLiveEvidenceRetriever:
    """Local fixture evidence provider for ON mode; it never performs HTTP."""

    network_request_count = 0
    model_call_count = 0

    def __init__(self, evidence_by_case_id: dict[str, list[dict[str, Any]]]) -> None:
        self._evidence_by_case_id = evidence_by_case_id

    def retrieve(
        self, request: OfficialEvidenceRetrievalRequest
    ) -> OfficialEvidenceRetrievalResult:
        records = self._evidence_by_case_id.get(request.claim_id or "", [])
        evidences = [
            _fixture_evidence(record, rank) for rank, record in enumerate(records, start=1)
        ]
        status = "success" if evidences else "no_chunk_match"
        now = datetime.now(UTC)
        return OfficialEvidenceRetrievalResult(
            query_text=request.query_text,
            status=status,
            catalog_match_count=int(bool(records)),
            selected_document_count=int(bool(records)),
            processed_document_count=int(bool(records)),
            failed_document_count=0,
            total_chunk_count=len(evidences),
            returned_evidence_count=len(evidences),
            network_request_count=0,
            evidences=evidences,
            document_failures=[],
            retrieval_started_at=now,
            retrieval_completed_at=now,
        )


class FactEvidenceLiveAbEvaluator:
    def __init__(self, fact_agent: FactAgentPort | None, retriever: Any | None = None) -> None:
        self.fact_agent = fact_agent
        self.retriever = retriever

    def plan(
        self, cases: list[FactEvidenceLiveAbCase], config: FactEvidenceLiveAbRunConfig
    ) -> dict[str, int | bool | str | list[str] | None]:
        selected = self._select(cases, config)
        calls_per_case = int(config.evidence_off_enabled) + int(config.evidence_on_enabled)
        calls = len(selected) * calls_per_case
        estimated_characters = sum(
            self._estimate_case_prompt_characters(case, config) for case in selected
        )
        return {
            "selected_case_ids": [case.case_id for case in selected],
            "selected_case_count": len(selected),
            "planned_fact_model_calls": calls,
            "planned_off_calls": len(selected) * int(config.evidence_off_enabled),
            "planned_on_calls": len(selected) * int(config.evidence_on_enabled),
            "maximum_possible_calls": calls,
            "estimated_prompt_characters": estimated_characters,
            "model": config.model,
            "temperature": config.temperature,
            "timeout_per_call": config.timeout_seconds,
            "maximum_expected_wait_seconds": calls * config.timeout_seconds,
            "evidence_off_enabled": config.evidence_off_enabled,
            "evidence_on_enabled": config.evidence_on_enabled,
            "live_calls_enabled": config.enabled and config.confirm_live_model_calls,
            "output_path": config.output_directory if config.save_results else None,
        }

    def run(
        self, cases: list[FactEvidenceLiveAbCase], config: FactEvidenceLiveAbRunConfig
    ) -> FactEvidenceLiveAbRunResult:
        plan = self.plan(cases, config)
        self._require_opt_in(config, int(plan["planned_fact_model_calls"]))
        if self.fact_agent is None:
            raise LiveAbSafetyError("Live model evaluation requires a Fact Agent")
        selected = self._select(cases, config)
        result = FactEvidenceLiveAbRunResult(len(selected), int(plan["planned_fact_model_calls"]))
        total_calls = int(plan["planned_fact_model_calls"])
        print(
            "Live A/B plan: "
            + json.dumps(
                {
                    "selected_case_ids": plan["selected_case_ids"],
                    "planned_fact_model_calls": plan["planned_fact_model_calls"],
                    "timeout_per_call": plan["timeout_per_call"],
                    "maximum_expected_wait_seconds": plan["maximum_expected_wait_seconds"],
                },
                ensure_ascii=False,
            )
        )
        call_index = 0
        for case in selected:
            if config.evidence_off_enabled:
                call_index += 1
                result.results.append(
                    self._run_case(case, "OFF", config, None, call_index, total_calls)
                )
            if config.evidence_on_enabled:
                if self.retriever is None:
                    raise LiveAbSafetyError("Evidence ON requires an injected retriever")
                retrieval = self.retriever.retrieve(
                    OfficialEvidenceRetrievalRequest(
                        query_text=case.claim_text,
                        claim_id=case.case_id,
                        product=case.product,
                        component=case.component,
                    )
                )
                context = build_fact_evidence_context(retrieval, FactEvidenceLimits())
                call_index += 1
                result.results.append(
                    self._run_case(case, "ON", config, context, call_index, total_calls)
                )
        if config.save_results:
            self._save(result, config.output_directory)
        return result

    def _estimate_case_prompt_characters(
        self, case: FactEvidenceLiveAbCase, config: FactEvidenceLiveAbRunConfig
    ) -> int:
        base = len(case.report_context or case.claim_text)
        total = base * int(config.evidence_off_enabled)
        if config.evidence_on_enabled:
            context_size = 0
            if self.retriever is not None:
                retrieval = self.retriever.retrieve(
                    OfficialEvidenceRetrievalRequest(
                        query_text=case.claim_text,
                        claim_id=case.case_id,
                        product=case.product,
                        component=case.component,
                    )
                )
                context_size = len(
                    json.dumps(build_fact_evidence_context(retrieval, FactEvidenceLimits()))
                )
            total += base + context_size
        return total

    def _run_case(
        self, case, mode, config, context, call_index, total_calls
    ) -> FactEvidenceLiveAbCaseResult:
        assert self.fact_agent is not None
        request = ReviewRequest(
            markdown=case.report_context or case.claim_text, fact_evidence_context=context
        )
        print(
            f"Calling case_id={case.case_id} mode={mode} "
            f"call={call_index}/{total_calls} model={config.model or ''} "
            f"timeout_seconds={config.timeout_seconds}"
        )
        started = time.monotonic()
        response: queue.Queue[tuple[object | None, BaseException | None]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                response.put((self.fact_agent.review(request), None))
            except BaseException as exc:  # pragma: no cover - exercised by integration stubs
                response.put((None, exc))

        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        worker.join(config.timeout_seconds)
        elapsed_ms = (time.monotonic() - started) * 1000
        if worker.is_alive():
            print(
                f"Call failed case_id={case.case_id} mode={mode} "
                f"latency_ms={elapsed_ms:.1f} token_usage_available=false error_code=harness_timeout"
            )
            return FactEvidenceLiveAbCaseResult(
                case.case_id,
                mode.lower(),
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
                elapsed_ms,
                "harness_timeout",
                "Fact evaluation exceeded the harness deadline",
            )
        review, error = response.get_nowait()
        if error is not None:
            print(
                f"Call failed case_id={case.case_id} mode={mode} "
                f"latency_ms={elapsed_ms:.1f} token_usage_available=false "
                f"error_code={type(error).__name__}"
            )
            return FactEvidenceLiveAbCaseResult(
                case.case_id,
                mode.lower(),
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
                elapsed_ms,
                type(error).__name__,
                "Fact evaluation call failed",
            )
        try:
            assert review is not None
            audit = getattr(getattr(self.fact_agent, "llm", None), "last_response_audit", {}) or {}
            token_usage_available = any(
                audit.get(key) is not None
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            )
            print(
                f"Call success case_id={case.case_id} mode={mode} "
                f"latency_ms={elapsed_ms:.1f} token_usage_available={token_usage_available}"
            )
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
                len(review.summary),
                audit.get("prompt_tokens"),
                audit.get("completion_tokens"),
                audit.get("total_tokens"),
                review.model_call_count or 1,
                review.evidence_network_request_count,
                elapsed_ms,
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
                elapsed_ms,
                type(exc).__name__,
                "Fact evaluation call failed",
            )

    def _select(self, cases, config):
        known = {case.case_id for case in cases}
        unknown = [case_id for case_id in config.case_ids if case_id not in known]
        if unknown:
            raise ValueError(f"Unknown live A/B case_id: {unknown[0]}")
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
        target = safe_results_directory(output_directory)
        target.mkdir(parents=True, exist_ok=True)
        (target / "fact-evidence-live-ab.json").write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8"
        )


def safe_results_directory(output_directory: str | None) -> Path:
    if not output_directory:
        raise LiveAbSafetyError("Saving live results requires an output directory")
    target = Path(output_directory)
    resolved = (PROJECT_ROOT / target).resolve() if not target.is_absolute() else target.resolve()
    try:
        resolved.relative_to(RESULTS_ROOT.resolve())
    except ValueError as exc:
        raise LiveAbSafetyError(
            "Live results may only be saved below benchmarks/results-local"
        ) from exc
    return resolved


def _fixture_evidence(record: dict[str, Any], rank: int) -> RetrievedOfficialEvidence:
    fetched_at = datetime.fromisoformat(record["source_fetched_at"])
    return RetrievedOfficialEvidence(
        rank=rank,
        score=float(record["score"]),
        matched_terms=list(record["matched_terms"]),
        chunk_id=record["chunk_id"],
        document_id=record["document_id"],
        canonical_url=record["canonical_url"],
        final_url=record["canonical_url"],
        product=record["product"],
        component=record["component"],
        document_type=record["document_type"],
        document_title=record["document_title"],
        section_heading=record["section_heading"],
        section_order=0,
        chunk_order=0,
        text=record["text"],
        source_fetched_at=fetched_at,
    )


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid live A/B fixture file: {path.name}") from exc


def _validate_case_ids(cases: list[FactEvidenceLiveAbCase]) -> None:
    seen: set[str] = set()
    for case in cases:
        if not case.case_id or case.case_id in seen:
            raise ValueError("Live A/B fixture contains a duplicate or empty case_id")
        seen.add(case.case_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safe, opt-in Fact Evidence OFF/ON live A/B harness"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="Print an offline plan (the default).")
    mode.add_argument(
        "--run-live", action="store_true", help="Run confirmed live Fact model calls."
    )
    parser.add_argument("--model", help="Explicit Fact model for live evaluation.")
    parser.add_argument(
        "--case-id", action="append", default=[], help="Fixture case_id; repeatable."
    )
    parser.add_argument("--max-cases", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-output-tokens", type=int, default=800)
    parser.add_argument("--timeout-seconds", type=float, default=100.0)
    parser.add_argument("--enable-off", dest="enable_off", action="store_true", default=True)
    parser.add_argument("--disable-off", dest="enable_off", action="store_false")
    parser.add_argument("--enable-on", dest="enable_on", action="store_true", default=True)
    parser.add_argument("--disable-on", dest="enable_on", action="store_false")
    parser.add_argument("--confirm-live-model-calls", action="store_true")
    parser.add_argument("--confirm-planned-call-count", type=int)
    parser.add_argument("--output")
    parser.add_argument("--save-results", action="store_true")
    parser.add_argument("--save-raw-model-response", action="store_true")
    parser.add_argument(
        "--redact-prompts", dest="redact_prompts", action="store_true", default=True
    )
    parser.add_argument("--no-redact-prompts", dest="redact_prompts", action="store_false")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    fixture = load_live_ab_fixture()
    config = FactEvidenceLiveAbRunConfig(
        enabled=args.run_live,
        confirm_live_model_calls=args.confirm_live_model_calls,
        model=args.model,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        timeout_seconds=args.timeout_seconds,
        case_ids=tuple(args.case_id),
        max_cases=args.max_cases,
        evidence_off_enabled=args.enable_off,
        evidence_on_enabled=args.enable_on,
        confirm_planned_call_count=args.confirm_planned_call_count,
        output_directory=args.output,
        save_results=args.save_results,
        redact_prompts=args.redact_prompts,
        save_raw_model_response=args.save_raw_model_response,
    )
    retriever = FixtureLiveEvidenceRetriever(fixture.evidence_by_case_id)
    evaluator = FactEvidenceLiveAbEvaluator(None, retriever)
    cases = load_live_ab_cases(case_ids=config.case_ids)
    plan = evaluator.plan(cases, config)
    if not args.run_live:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    evaluator._require_opt_in(config, int(plan["planned_fact_model_calls"]))
    if config.save_results:
        safe_results_directory(config.output_directory)
    if not os.getenv("SILICONFLOW_API_KEY"):
        raise LiveAbSafetyError("SILICONFLOW_API_KEY is required for confirmed live evaluation")
    evaluator.fact_agent = _live_fact_agent(config)
    result = evaluator.run(cases, config)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _live_fact_agent(config: FactEvidenceLiveAbRunConfig) -> FactAgentPort:
    """Build the existing Fact Agent only after all live safeguards have passed."""
    from agent_network.agents.builtin import FactAgent
    from agent_network.config import load_config
    from agent_network.llm import LiteLLMClient
    from agent_network.prompts import PromptRegistry

    app_config = load_config(PROJECT_ROOT / "configs" / "default.yaml")
    fact_model = app_config.model_for_agent("fact")
    fact_options = app_config.llm_options_by_model().get(fact_model, {})
    client = LiteLLMClient(
        default_model=config.model or "",
        temperature=config.temperature,
        max_tokens=config.max_output_tokens,
        timeout_seconds=config.timeout_seconds,
        retry_attempts=1,
        model_options={config.model or "": fact_options},
    )
    return FactAgent(
        llm=client,
        prompts=PromptRegistry(PROJECT_ROOT / "prompts"),
        model=config.model,
        provider=app_config.provider_for_agent("fact"),
        timeout_seconds=config.timeout_seconds,
        max_tokens=config.max_output_tokens,
    )


if __name__ == "__main__":
    raise SystemExit(main())
