"""Deterministic offline benchmark for the catalog-only Evidence Pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_network.evidence.schemas import (
    Claim,
    ClaimType,
    DocumentCatalog,
    VerificationStatus,
    VersionScope,
)
from agent_network.evidence.sources import (
    FixtureOfficialDocumentEvidenceSource,
    load_official_document_domain_config,
)
from agent_network.evidence.verifier import OfflineEvidenceVerifier
from agent_network.evidence.vocabulary import components_match, products_match


class EvidencePipelineBenchmarkCase(BaseModel):
    """One deterministic catalog retrieval and verification expectation."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    claim_type: ClaimType
    product: str
    component: str
    version_scope: VersionScope = Field(default_factory=VersionScope)
    expected_document_ids: list[str] = Field(default_factory=list)
    forbidden_document_ids: list[str] = Field(default_factory=list)
    expected_status: VerificationStatus
    expected_product: str
    expected_component: str
    expected_version_match: bool | None = None
    notes: str = ""

    @field_validator("expected_document_ids", "forbidden_document_ids", mode="before")
    @classmethod
    def unique_document_ids(cls, value: Any) -> list[str]:
        values = value or []
        result: list[str] = []
        for item in values:
            document_id = str(item).strip()
            if document_id and document_id not in result:
                result.append(document_id)
        return result

    def to_claim(self) -> Claim:
        return Claim(
            claim_id=self.case_id,
            source_file="FIXTURE ONLY: evidence-pipeline-v1",
            section="Benchmark",
            line_start=1,
            line_end=1,
            original_text=self.claim,
            normalized_claim=self.claim.lower(),
            claim_type=self.claim_type,
            product=self.product,
            component=self.component,
            version_scope=self.version_scope,
        )


class EvidencePipelineBenchmarkFixture(BaseModel):
    """Fixture payload for one reproducible offline benchmark suite."""

    fixture_id: str
    fixture_notice: str
    benchmark_version: str
    cases: list[EvidencePipelineBenchmarkCase]
    catalog: list[DocumentCatalog]

    @classmethod
    def load(cls, path: str | Path) -> "EvidencePipelineBenchmarkFixture":
        root = Path(path)
        metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))
        catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        fixture = cls(
            fixture_id=str(metadata["fixture_id"]),
            fixture_notice=str(metadata["fixture_notice"]),
            benchmark_version=str(metadata["benchmark_version"]),
            cases=[EvidencePipelineBenchmarkCase.model_validate(item) for item in cases],
            catalog=[DocumentCatalog.model_validate(item) for item in catalog],
        )
        case_ids = [case.case_id for case in fixture.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark case_id values must be unique")
        return fixture


class EvidencePipelineCaseResult(BaseModel):
    case_id: str
    actual_document_ids: list[str]
    expected_document_ids: list[str]
    forbidden_hits: list[str]
    actual_status: VerificationStatus
    expected_status: VerificationStatus
    actual_version_match: bool | None
    expected_version_match: bool | None
    passed: bool
    failure_reasons: list[str] = Field(default_factory=list)


class EvidencePipelineMetrics(BaseModel):
    total_cases: int
    passed_cases: int
    failed_cases: int
    top1_accuracy: float
    recall_at_3: float
    precision_at_3: float
    forbidden_hit_rate: float
    product_isolation_accuracy: float
    component_isolation_accuracy: float
    version_match_accuracy: float
    not_found_accuracy: float
    status_accuracy: float


class EvidencePipelineBenchmarkResult(BaseModel):
    benchmark_version: str
    fixture_path: str
    fixture_notice: str
    run_id: str
    metrics: EvidencePipelineMetrics
    case_results: list[EvidencePipelineCaseResult]
    network_request_count: int = 0
    model_call_count: int = 0
    started_at: datetime
    completed_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def run_evidence_pipeline_benchmark(
    fixture_path: str | Path,
    *,
    domain_config_path: str | Path = "configs/evidence_domains/rancher.yaml",
) -> EvidencePipelineBenchmarkResult:
    """Run catalog Source -> Matcher/Verifier -> deterministic benchmark metrics."""

    started_at = datetime.now(UTC)
    fixture = EvidencePipelineBenchmarkFixture.load(fixture_path)
    domain_config = load_official_document_domain_config(domain_config_path)
    allowed_domains = {
        domain for domains in domain_config.official_domains.values() for domain in domains
    }
    source = FixtureOfficialDocumentEvidenceSource("rancher", allowed_domains, fixture.catalog)
    verifier = OfflineEvidenceVerifier(source)
    catalog_by_id = {document.document_id: document for document in fixture.catalog}
    case_results = [_evaluate_case(case, source, verifier, catalog_by_id) for case in fixture.cases]
    metrics = _metrics(case_results, fixture.cases, catalog_by_id)
    digest = sha256(fixture.fixture_id.encode("utf-8")).hexdigest()[:12]
    return EvidencePipelineBenchmarkResult(
        benchmark_version=fixture.benchmark_version,
        fixture_path=str(Path(fixture_path).as_posix()),
        fixture_notice=fixture.fixture_notice,
        run_id=f"benchmark-{digest}",
        metrics=metrics,
        case_results=case_results,
        network_request_count=source.network_request_count,
        model_call_count=verifier.model_call_count,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


def write_evidence_pipeline_benchmark(
    result: EvidencePipelineBenchmarkResult, output: str | Path
) -> tuple[Path, Path, Path]:
    """Write reproducible JSON, Markdown, and run metadata reports."""

    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    benchmark_path = root / "benchmark.json"
    markdown_path = root / "benchmark.md"
    run_path = root / "run.json"
    benchmark_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    markdown_path.write_text(_render_markdown(result), encoding="utf-8")
    run_path.write_text(
        json.dumps(
            {
                "run_id": result.run_id,
                "benchmark_version": result.benchmark_version,
                "fixture_path": result.fixture_path,
                "total_cases": result.metrics.total_cases,
                "passed_cases": result.metrics.passed_cases,
                "failed_cases": result.metrics.failed_cases,
                "network_request_count": result.network_request_count,
                "model_call_count": result.model_call_count,
                "started_at": result.started_at.isoformat(),
                "completed_at": result.completed_at.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return benchmark_path, markdown_path, run_path


def _evaluate_case(
    case: EvidencePipelineBenchmarkCase,
    source: FixtureOfficialDocumentEvidenceSource,
    verifier: OfflineEvidenceVerifier,
    catalog_by_id: dict[str, DocumentCatalog],
) -> EvidencePipelineCaseResult:
    claim = case.to_claim()
    evidence = source.search(claim)
    actual_document_ids = _stable_unique(
        str(item.source_metadata.get("document_id"))
        for item in evidence
        if item.source_metadata.get("document_id")
    )
    verification = verifier.verify(claim)
    forbidden_hits = [
        document_id
        for document_id in actual_document_ids
        if document_id in case.forbidden_document_ids
    ]
    reasons: list[str] = []
    if not set(case.expected_document_ids).issubset(actual_document_ids):
        reasons.append("missing_expected_document")
    if forbidden_hits:
        reasons.append("forbidden_document_hit")
    if verification.verification_status != case.expected_status:
        reasons.append("unexpected_status")
    if (
        case.expected_version_match is not None
        and verification.version_match != case.expected_version_match
    ):
        reasons.append("unexpected_version_match")
    documents = [catalog_by_id[document_id] for document_id in actual_document_ids]
    if any(not products_match(case.expected_product, document.product) for document in documents):
        reasons.append("product_isolation_failure")
    if any(
        not any(
            components_match(case.expected_component, component)
            for component in document.components
        )
        for document in documents
    ):
        reasons.append("component_isolation_failure")
    if not case.expected_document_ids and actual_document_ids:
        reasons.append("unexpected_document")
    return EvidencePipelineCaseResult(
        case_id=case.case_id,
        actual_document_ids=actual_document_ids,
        expected_document_ids=case.expected_document_ids,
        forbidden_hits=forbidden_hits,
        actual_status=verification.verification_status,
        expected_status=case.expected_status,
        actual_version_match=verification.version_match,
        expected_version_match=case.expected_version_match,
        passed=not reasons,
        failure_reasons=reasons,
    )


def _metrics(
    results: list[EvidencePipelineCaseResult],
    cases: list[EvidencePipelineBenchmarkCase],
    catalog_by_id: dict[str, DocumentCatalog],
) -> EvidencePipelineMetrics:
    by_case = {case.case_id: case for case in cases}
    retrieval_results = [result for result in results if result.expected_document_ids]
    top1 = _ratio(
        sum(
            bool(result.actual_document_ids)
            and result.actual_document_ids[0] in result.expected_document_ids
            for result in retrieval_results
        ),
        len(retrieval_results),
    )
    recall = _ratio(
        sum(
            len(set(result.actual_document_ids[:3]) & set(result.expected_document_ids))
            / len(result.expected_document_ids)
            for result in retrieval_results
        ),
        len(retrieval_results),
    )
    precision = _ratio(
        sum(
            _ratio(
                len(set(result.actual_document_ids[:3]) & set(result.expected_document_ids)),
                len(result.actual_document_ids[:3]),
            )
            for result in retrieval_results
        ),
        len(retrieval_results),
    )
    product_ok = 0
    component_ok = 0
    for result in results:
        case = by_case[result.case_id]
        documents = [catalog_by_id[document_id] for document_id in result.actual_document_ids]
        product_ok += all(
            products_match(case.expected_product, document.product) for document in documents
        )
        component_ok += all(
            any(
                components_match(case.expected_component, component)
                for component in document.components
            )
            for document in documents
        )
    version_results = [result for result in results if result.expected_version_match is not None]
    not_found_results = [result for result in results if not result.expected_document_ids]
    return EvidencePipelineMetrics(
        total_cases=len(results),
        passed_cases=sum(result.passed for result in results),
        failed_cases=sum(not result.passed for result in results),
        top1_accuracy=round(top1, 4),
        recall_at_3=round(recall, 4),
        precision_at_3=round(precision, 4),
        forbidden_hit_rate=round(
            _ratio(sum(bool(item.forbidden_hits) for item in results), len(results)), 4
        ),
        product_isolation_accuracy=round(_ratio(product_ok, len(results)), 4),
        component_isolation_accuracy=round(_ratio(component_ok, len(results)), 4),
        version_match_accuracy=round(
            _ratio(
                sum(
                    result.actual_version_match == result.expected_version_match
                    for result in version_results
                ),
                len(version_results),
            ),
            4,
        ),
        not_found_accuracy=round(
            _ratio(
                sum(
                    not result.actual_document_ids
                    and result.actual_status == result.expected_status
                    and result.actual_status != VerificationStatus.CONTRADICTED
                    for result in not_found_results
                ),
                len(not_found_results),
            ),
            4,
        ),
        status_accuracy=round(
            _ratio(
                sum(result.actual_status == result.expected_status for result in results),
                len(results),
            ),
            4,
        ),
    )


def _render_markdown(result: EvidencePipelineBenchmarkResult) -> str:
    metrics = result.metrics.model_dump()
    rows = "\n".join(f"| {key} | {value} |" for key, value in metrics.items())
    failures = [item for item in result.case_results if not item.passed]
    failure_rows = (
        "\n".join(
            f"| {item.case_id} | {', '.join(item.actual_document_ids) or '-'} | "
            f"{', '.join(item.failure_reasons)} |"
            for item in failures
        )
        or "| None | - | - |"
    )
    return (
        "# Evidence Pipeline Benchmark v1\n\n"
        "## Benchmark Summary\n\n"
        f"- Run ID: `{result.run_id}`\n"
        f"- Fixture: `{result.fixture_path}`\n"
        f"- Network requests: {result.network_request_count}\n"
        f"- Model calls: {result.model_call_count}\n\n"
        "## Metrics\n\n| Metric | Value |\n|---|---:|\n"
        f"{rows}\n\n"
        "## Product Isolation\n\n"
        f"Product isolation accuracy: {metrics['product_isolation_accuracy']}\n\n"
        "## Component Isolation\n\n"
        f"Component isolation accuracy: {metrics['component_isolation_accuracy']}\n\n"
        "## Version Matching\n\n"
        f"Version match accuracy: {metrics['version_match_accuracy']}\n\n"
        "## Failed Cases\n\n| Case | Actual document IDs | Failure reasons |\n|---|---|---|\n"
        f"{failure_rows}\n\n"
        "## Current Limitations\n\n"
        "本基准使用离线 fixture，只验证 Evidence Pipeline 逻辑，不代表真实官方文档检索准确率。\n"
    )


def _ratio(numerator: float, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _stable_unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
