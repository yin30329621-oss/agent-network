"""Command line interface."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from types import SimpleNamespace
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated

import typer

from agent_network import __version__
from agent_network.claim import ClaimExtractionRequest, DeterministicClaimExtractor
from agent_network.config import load_config
from agent_network.evidence.reporting import write_report as write_evidence_report
from agent_network.evidence.cache import EvidenceCache
from agent_network.evidence.github_advisory import GitHubAdvisoryEvidenceSource
from agent_network.evidence.http import EvidenceHttpClient
from agent_network.evidence.nvd import NvdEvidenceSource
from agent_network.evidence.pilot import public_cve_claim, write_pilot_output
from agent_network.evidence.pipeline_benchmark import (
    run_evidence_pipeline_benchmark,
    write_evidence_pipeline_benchmark,
)
from agent_network.evidence.retrieval_benchmark import (
    run_retrieval_benchmark,
    write_retrieval_benchmark,
)
from agent_network.evidence.sources import EvidenceFixture, FakeEvidenceSource
from agent_network.evidence.verifier import OfflineEvidenceVerifier
from agent_network.evidence.offline_retrieval import OfflineBm25EvidenceRetriever
from agent_network.claim.fact_model_adapter import fact_model_adapter_from_config
from agent_network.claim.fact_review import (
    DualFactReviewCoordinator,
    DualReviewBudget,
    FakeFactReviewer,
)
from agent_network.workflow.report_verification import (
    OfflineReportVerificationConfig,
    OfflineReportVerificationOrchestrator,
)
from agent_network.input_analysis import analyze_input
from agent_network.llm import LiteLLMClient, MockLLMClient, load_dotenv_if_available
from agent_network.outputs import write_outputs
from agent_network.prompts import PromptRegistry
from agent_network.run_registry import baseline_from_review, load_latest, register_run
from agent_network.schemas import ReviewRequest, now_iso
from agent_network.workflow import ReviewWorkflow

app = typer.Typer(help="Agent Network command line interface.", invoke_without_command=True)

ReviewMode = Annotated[str, typer.Option("--mode", help="Review mode: auto, mock, or real.")]


@app.callback()
def root(version: bool = typer.Option(False, "--version", help="Show version and exit.")) -> None:
    """Agent Network command line interface."""
    if version:
        typer.echo(f"agent-network {__version__}")
        raise typer.Exit


@app.command("extract-claims")
def extract_claims(
    report: Path = typer.Argument(..., exists=True, readable=True),
    output: Path | None = typer.Option(None, "--output", "-o"),
    source_name: str | None = typer.Option(
        None, "--source-name", help="Stable source identity; defaults to the report basename."
    ),
) -> None:
    """Extract deterministic Claims from a Markdown report."""
    source = source_name or report.name
    extraction = DeterministicClaimExtractor().extract(
        ClaimExtractionRequest(
            document_text=report.read_text(encoding="utf-8"),
            source_name=source,
        )
    )
    payload = extraction.to_dict()
    payload["statistics"] = {
        "candidate_count": extraction.candidate_count,
        "extracted_count": len(extraction.claims),
        "duplicate_count": extraction.duplicate_count,
        "failure_count": len(extraction.failures),
        "selected_count": len(extraction.claims),
        "truncated_count": 0,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote {output}")



@app.command("verify-report")
def verify_report(
    report: Path = typer.Argument(..., exists=True, readable=True),
    output: Path = typer.Option(Path("report-verification.json"), "--output", "-o"),
    offline: bool = typer.Option(True, "--offline/--online"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    enable_dual_fact: bool = typer.Option(False, "--enable-dual-fact"),
    batch_size: int = typer.Option(
        3, "--batch-size", min=1, help="Claims per Dual Fact reviewer batch."
    ),
    confirm_live_model_calls: bool = typer.Option(
        False, "--confirm-live-model-calls",
        help="Explicitly allow the Dual Fact reviewer execution path.",
    ),
    confirm_planned_call_count: int | None = typer.Option(
        None, "--confirm-planned-call-count", min=0,
        help="Require the estimated Dual Fact call count to match N before execution.",
    ),
) -> None:
    """Run the report-level verification workflow in offline mode."""
    if not offline:
        raise typer.BadParameter("M3.3a only supports --offline evidence retrieval")
    dual_enabled = enable_dual_fact and not dry_run
    live_dual_enabled = dual_enabled and confirm_live_model_calls
    if live_dual_enabled and confirm_planned_call_count is None:
        raise typer.BadParameter(
            "--confirm-planned-call-count is required for live Dual Fact execution"
        )
    if dual_enabled and confirm_planned_call_count is not None:
        estimated_calls = _estimate_dual_fact_calls(report, batch_size)
        if confirm_planned_call_count != estimated_calls:
            raise typer.BadParameter(
                "planned Dual Fact calls do not match: "
                f"estimated={estimated_calls}, confirmed={confirm_planned_call_count}"
            )
    retriever = OfflineBm25EvidenceRetriever([])
    coordinator = None
    if dual_enabled:
        if live_dual_enabled:
            app_config = load_config()
            fact_a = fact_model_adapter_from_config(app_config, "fact_a")
            fact_b = fact_model_adapter_from_config(app_config, "fact_b")
            max_expected_output_tokens = 10_000
        else:
            fact_a = FakeFactReviewer("fact_a")
            fact_b = FakeFactReviewer("fact_b")
            fact_a.config = SimpleNamespace(max_tokens=2400, timeout_seconds=90)
            fact_b.config = SimpleNamespace(max_tokens=2200, timeout_seconds=180)
            max_expected_output_tokens = batch_size * 300
        coordinator = DualFactReviewCoordinator(
            fact_a,
            fact_b,
            budget=DualReviewBudget(
                claims_per_batch=batch_size,
                max_expected_output_tokens_per_batch=max_expected_output_tokens,
            ),
        )
    orchestrator = OfflineReportVerificationOrchestrator(
        retriever,
        config=OfflineReportVerificationConfig(
            source_name=report.name,
            enable_dual_fact=dual_enabled,
            reviewer_batch_size=batch_size,
        ),
        coordinator=coordinator,
    )
    result = orchestrator.run_file(report, output_path=output)
    result.artifact["metadata"]["offline"] = True
    result.artifact["metadata"]["dry_run"] = dry_run
    result.artifact["metadata"]["dual_fact_requested"] = enable_dual_fact
    result.artifact["metadata"]["live_model_calls_confirmed"] = confirm_live_model_calls
    result.artifact["metadata"]["planned_call_count_confirmed"] = confirm_planned_call_count
    result.artifact["metadata"]["reviewer_batch_size"] = batch_size
    output.write_text(
        json.dumps(result.artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"Wrote {output}")


def _estimate_dual_fact_calls(report: Path, batch_size: int = 3) -> int:
    """Estimate two reviewer calls per default three-claim batch."""
    extraction = DeterministicClaimExtractor().extract(
        ClaimExtractionRequest(
            document_text=report.read_text(encoding="utf-8"),
            source_name=report.name,
        )
    )
    claim_count = len(extraction.claims)
    return ((claim_count + batch_size - 1) // batch_size) * 2 if claim_count else 0

@app.command()
def review(
    report: Path = typer.Argument(..., exists=True, readable=True),
    output: Path = typer.Option(Path("outputs"), "--output", "-o"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config", "-c"),
    prompts: Path = typer.Option(Path("prompts"), "--prompts"),
    profile: str = typer.Option("balanced", "--profile", help="Execution profile."),
    only: str | None = typer.Option(
        None, "--only", help="Run only one agent: fact, security, or logic."
    ),
    mode: ReviewMode = "auto",
    language: str = typer.Option(
        "en", "--language", help="Human-readable review language: en or zh."
    ),
    mock: bool = typer.Option(False, "--mock", help="Force deterministic local mock review."),
    open_output: bool = typer.Option(
        False, "--open", help="Open generated review.md after completion."
    ),
) -> None:
    """Review a Markdown technical report."""

    load_dotenv_if_available()
    base_config = load_config(config)
    try:
        app_config = base_config.with_profile(profile)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--profile") from exc
    markdown = report.read_text(encoding="utf-8")
    input_analysis = analyze_input(markdown)
    if input_analysis.input_size_class == "long" and profile == "balanced":
        typer.echo(
            "警告：当前输入属于长报告，balanced profile 可能发生超时。"
            "建议使用 --profile long-report。"
        )
    selected_agents = [only] if only else ["fact", "security", "logic"]
    _validate_agents(selected_agents)
    selected_mode = "mock" if mock else mode.lower()
    if selected_mode not in {"auto", "mock", "real"}:
        raise typer.BadParameter("--mode must be one of: auto, mock, real")
    selected_language = language.lower()
    if selected_language not in {"en", "zh"}:
        raise typer.BadParameter("--language must be one of: en, zh")
    required_agents = selected_agents if only else [*selected_agents, "merge"]
    missing_agents = [
        agent for agent in required_agents if not app_config.has_api_key_for_agent(agent)
    ]
    use_mock = selected_mode == "mock" or (selected_mode == "auto" and bool(missing_agents))
    if selected_mode == "real" and missing_agents:
        missing = ", ".join(missing_agents)
        raise typer.BadParameter(f"Missing API key for agent(s): {missing}")
    if use_mock:
        llm = MockLLMClient()
        typer.echo("Using mock LLM client.")
    else:
        llm = LiteLLMClient(
            default_model=app_config.default_model,
            temperature=app_config.temperature,
            max_tokens=app_config.max_tokens,
            timeout_seconds=app_config.timeout_seconds,
            retry_attempts=app_config.retry_attempts,
            model_options=app_config.llm_options_by_model(),
        )
    workflow = ReviewWorkflow.from_config(
        llm=llm, prompts=PromptRegistry(prompts), config=app_config
    )
    started_at = now_iso()
    started = time.monotonic()
    request = ReviewRequest(markdown=markdown, source_name=report.name, language=selected_language)
    result = (
        workflow.run_only(request, only, progress=_print_progress)
        if only
        else workflow.run(request, progress=_print_progress)
    )
    total_elapsed = time.monotonic() - started
    result.metadata = {
        "version": __version__,
        "timestamp": now_iso(),
        "source_file": str(report),
        "profile": profile,
        "provider": app_config.provider_for_agent("fact"),
        "mode": selected_mode,
        "language": selected_language,
        "total_elapsed_seconds": total_elapsed,
        **input_analysis.to_dict(),
    }
    markdown_path, json_path = write_outputs(result, output)
    register_run(
        result=result,
        markdown_path=markdown_path,
        json_path=json_path,
        output_root="outputs",
        source_file=str(report),
        mode=selected_mode,
        profile=profile,
        config=app_config,
        started_at=started_at,
        completed_at=now_iso(),
        total_elapsed_seconds=total_elapsed,
    )
    typer.echo(f"Wrote {markdown_path}")
    typer.echo(f"Wrote {json_path}")
    if open_output:
        _open_markdown(markdown_path)


@app.command()
def doctor(config: Path = typer.Option(Path("configs/default.yaml"), "--config", "-c")) -> None:
    """Check local dependencies, provider configuration, and API-key readiness."""

    load_dotenv_if_available()
    app_config = load_config(config)
    typer.echo("Agent Network doctor")
    typer.echo(f"Config: {config}")
    typer.echo("")
    typer.echo("Dependencies:")
    for package in ("pytest", "PyYAML", "langgraph", "litellm", "python-dotenv"):
        typer.echo(f"  {package}: {_package_version(package)}")
    typer.echo("")
    typer.echo("Cost protection:")
    typer.echo(f"  max_tokens: {app_config.max_tokens}")
    typer.echo(f"  timeout_seconds: {app_config.timeout_seconds}")
    typer.echo(f"  retry_attempts: {app_config.retry_attempts}")
    typer.echo(f"  configured_mode: {app_config.mode}")
    typer.echo("")
    typer.echo("Providers:")
    seen_providers: set[str] = set()
    for agent in ("fact", "security", "logic", "merge"):
        provider = app_config.provider_for_agent(agent)
        model = app_config.model_for_agent(agent)
        env_name = app_config.api_key_env_for_provider(provider)
        status = "configured" if app_config.has_api_key_for_agent(agent) else "missing"
        timeout = app_config.timeout_for_agent(agent)
        role = app_config.role_for_agent(agent)
        typer.echo(
            f"  {agent}: role={role} provider={provider} model={model} "
            f"timeout={timeout}s key={env_name} status={status}"
        )
        seen_providers.add(provider)

    typer.echo("")
    typer.echo("Known provider keys:")
    for provider in ("siliconflow", "deepseek", "openai", "glm"):
        env_name = app_config.api_key_env_for_provider(provider)
        status = "configured" if env_name and os.getenv(env_name) else "missing"
        active = " active" if provider in seen_providers else ""
        typer.echo(f"  {provider}: key={env_name} status={status}{active}")


@app.command("verify-evidence")
def verify_evidence(
    fixture: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    claim: str | None = typer.Option(None, "--claim", help="Verify one fixture claim ID."),
    output: Path = typer.Option(Path("outputs/evidence-phase1"), "--output", "-o"),
    output_format: str = typer.Option(
        "both", "--format", help="Output format: json, markdown, or both."
    ),
) -> None:
    """Run deterministic offline evidence verification against local fixtures."""

    selected_format = output_format.lower()
    if selected_format not in {"json", "markdown", "both"}:
        raise typer.BadParameter("--format must be one of: json, markdown, both")
    dataset = EvidenceFixture.load(fixture)
    claims = dataset.claims
    if claim:
        claims = [item for item in claims if item.claim_id == claim]
        if not claims:
            raise typer.BadParameter(f"Unknown fixture claim ID: {claim}", param_hint="--claim")
    source = FakeEvidenceSource(dataset.evidence)
    verifier = OfflineEvidenceVerifier(source)
    report = verifier.verify_all(
        claims,
        fixture_id=dataset.fixture_id,
        fixture_notice=dataset.fixture_notice,
    )
    paths = write_evidence_report(
        report,
        output,
        output_format=selected_format,
        fixture_path=fixture,
        claim_filter=claim,
    )
    typer.echo("Offline fixture verification completed.")
    typer.echo(f"Claims: {report.claim_count}; Evidence: {report.evidence_count}")
    typer.echo("Model calls: 0; Network requests: 0")
    for path in paths.values():
        typer.echo(f"Wrote {path}")


@app.command("benchmark-evidence-pipeline")
def benchmark_evidence_pipeline(
    fixture: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    output: Path = typer.Option(Path("outputs/benchmark-evidence-v1"), "--output", "-o"),
    domain_config: Path = typer.Option(
        Path("configs/evidence_domains/rancher.yaml"), "--domain-config"
    ),
) -> None:
    """Run the offline catalog Evidence Pipeline benchmark without network or models."""

    result = run_evidence_pipeline_benchmark(fixture, domain_config_path=domain_config)
    json_path, markdown_path, run_path = write_evidence_pipeline_benchmark(result, output)
    typer.echo(f"Benchmark JSON: {json_path}")
    typer.echo(f"Benchmark Markdown: {markdown_path}")
    typer.echo(f"Run metadata: {run_path}")
    typer.echo(
        f"Cases: {result.metrics.passed_cases}/{result.metrics.total_cases}; "
        f"Model calls: {result.model_call_count}; Network requests: {result.network_request_count}"
    )


@app.command("benchmark-retrieval")
def benchmark_retrieval(
    fixture: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    output: Path = typer.Option(Path("outputs/benchmark-retrieval-v1"), "--output", "-o"),
) -> None:
    """Run the offline DocumentChunk BM25 retrieval benchmark without network or models."""

    result = run_retrieval_benchmark(fixture)
    json_path, markdown_path, run_path = write_retrieval_benchmark(result, output)
    typer.echo(f"Benchmark JSON: {json_path}")
    typer.echo(f"Benchmark Markdown: {markdown_path}")
    typer.echo(f"Run metadata: {run_path}")
    typer.echo(
        f"Cases: {result.metrics.passed_cases}/{result.metrics.total_cases}; "
        f"Model calls: {result.model_call_count}; Network requests: {result.network_request_count}"
    )


@app.command("fetch-evidence")
def fetch_evidence(
    cve_id: str = typer.Argument(..., help="Public CVE ID, for example CVE-2022-45157."),
    source: str = typer.Option(..., "--source", help="Official source: nvd or github."),
    output: Path = typer.Option(Path("outputs/evidence-pilot"), "--output", "-o"),
    cache: Path = typer.Option(
        Path(".cache/agent-network/evidence"), "--cache", help="Local response cache."
    ),
    timeout_seconds: float = typer.Option(20.0, "--timeout", min=1.0, max=120.0),
) -> None:
    """Fetch public CVE evidence without invoking any LLM."""

    selected_source = source.lower()
    if selected_source not in {"nvd", "github"}:
        raise typer.BadParameter("--source must be one of: nvd, github")
    try:
        claim = public_cve_claim(cve_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="CVE_ID") from exc
    client = EvidenceHttpClient(
        cache=EvidenceCache(cache),
        timeout_seconds=timeout_seconds,
        minimum_interval_seconds=0.6 if selected_source == "nvd" else 0.0,
    )
    if selected_source == "nvd":
        evidence_source = NvdEvidenceSource(client, api_key=os.getenv("NVD_API_KEY"))
    else:
        evidence_source = GitHubAdvisoryEvidenceSource(client, token=os.getenv("GITHUB_TOKEN"))
    evidence = evidence_source.search(claim)
    audit = evidence_source.last_audit.to_dict() if evidence_source.last_audit else None
    paths = write_pilot_output(
        output_dir=output,
        cve_id=cve_id,
        source_name=selected_source,
        evidence=evidence,
        audit=audit,
        network_request_count=evidence_source.network_request_count,
    )
    typer.echo(f"Public CVE pilot completed: source={selected_source} evidence={len(evidence)}")
    typer.echo(f"Network requests: {evidence_source.network_request_count}; Model calls: 0")
    if audit and audit.get("error_type"):
        typer.echo(f"Source error: {audit['error_type']}")
    for path in paths.values():
        typer.echo(f"Wrote {path}")


@app.command()
def baseline(
    input: Path | None = typer.Option(None, "--input", "-i"),
    output: Path = typer.Option(Path("docs/baseline-v0.1.md"), "--output", "-o"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config", "-c"),
) -> None:
    """Generate a project baseline from review.json."""

    app_config = load_config(config)
    review_json = input
    if review_json is None:
        latest = load_latest("outputs")
        if not latest:
            raise typer.BadParameter("No completed run found. Provide --input review.json.")
        review_json = Path(latest["review_json"])
    path = baseline_from_review(review_json, output, app_config)
    typer.echo(f"Wrote {path}")


@app.command()
def stats(config: Path = typer.Option(Path("configs/default.yaml"), "--config", "-c")) -> None:
    """Show status for the latest run without calling any LLM API."""

    load_dotenv_if_available()
    latest = load_latest("outputs")
    typer.echo("Agent Network v0.1.0")
    typer.echo("")
    typer.echo("Workflow")
    typer.echo("--------")
    typer.echo("Fact -> Security -> Logic -> Merge")
    typer.echo("")
    typer.echo("Models")
    typer.echo("------")
    app_config = load_config(config) if config.exists() else None
    if app_config:
        for agent in ("fact", "security", "logic", "merge"):
            typer.echo(
                f"{agent.title():<10} {app_config.provider_for_agent(agent).title()} / "
                f"{app_config.model_for_agent(agent)}"
            )
    else:
        typer.echo("configuration unavailable")
    if not latest:
        typer.echo("")
        typer.echo("Last Run")
        typer.echo("--------")
        typer.echo("no completed run found")
        return
    import json

    data = json.loads(Path(latest["review_json"]).read_text(encoding="utf-8"))
    typer.echo("")
    typer.echo("Last Run")
    typer.echo("--------")
    for item in data.get("execution", []):
        typer.echo(
            f"{str(item.get('agent')).title():<10} {str(item.get('status')):<10} "
            f"{(item.get('elapsed_seconds') or 0):.1f}s"
        )
    typer.echo("")
    typer.echo("Total Runtime")
    typer.echo("-------------")
    typer.echo(f"{latest.get('total_elapsed_seconds', 0):.1f}s")
    summary = data.get("summary", {})
    typer.echo("")
    typer.echo("Findings")
    typer.echo("--------")
    for key in ("critical", "high", "medium", "low", "info"):
        typer.echo(f"{key.title()}: {summary.get(key, 0)}")
    typer.echo(f"Needs Human Review: {summary.get('needs_human_review', False)}")
    typer.echo("")
    typer.echo("Tests")
    typer.echo("-----")
    typer.echo("unavailable")
    typer.echo("")
    typer.echo("Provider")
    typer.echo("--------")
    status = "configured" if app_config and app_config.has_api_key_for_agent("fact") else "missing"
    typer.echo(f"SiliconFlow {status}")


def _validate_agents(agents: list[str | None]) -> None:
    valid = {"fact", "security", "logic", "merge"}
    invalid = [agent for agent in agents if agent not in valid]
    if invalid:
        raise typer.BadParameter(f"--only must be one of: {', '.join(sorted(valid))}")


def _package_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "missing"


def _open_markdown(path: Path) -> None:
    try:
        if not path.exists():
            typer.echo(f"review.md not found: {path.resolve()}")
            return
        system = platform.system()
        if system == "Windows":
            os.startfile(str(path.resolve()))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(path.resolve())])
        else:
            subprocess.Popen(["xdg-open", str(path.resolve())])
    except Exception as exc:
        typer.echo(f"Could not open review.md automatically: {type(exc).__name__}")
        typer.echo(str(path.resolve()))


def _print_progress(agent: str, event: str, elapsed_seconds: float | None, review) -> None:
    display_name = agent
    prefix = ""
    if ":" in agent:
        prefix, display_name = agent.split(":", 1)
    label = f"{display_name.title()} Agent"
    if display_name == "merge":
        label = "Merge Agent"
    if event == "start":
        lead = f"[{prefix}] " if prefix else ""
        typer.echo(f"{lead}Running {label}...")
    elif event in {"complete", "completed"}:
        model = f" model={review.model}" if review and review.model else ""
        provider = f" provider={review.provider}" if review and review.provider else ""
        typer.echo(f"{label} completed in {elapsed_seconds or 0:.1f}s{provider}{model}")
    elif event in {
        "completed_with_warnings",
        "parse_failed",
        "failed",
        "skipped",
        "truncated",
    }:
        provider = f" provider={review.provider}" if review and review.provider else ""
        error = f" error={review.error_type}" if review and review.error_type else ""
        typer.echo(
            f"{label} {event} in {elapsed_seconds or 0:.1f}s{provider} model={review.model}{error}"
        )


def main() -> None:
    app()
