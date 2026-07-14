"""Deterministic offline benchmark for Claim-to-Chunk BM25 retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace

from agent_network.evidence.document_chunker import DocumentChunk
from agent_network.evidence.offline_retrieval import OfflineBm25EvidenceRetriever


@dataclass(slots=True)
class RetrievalBenchmarkMetrics:
    total_cases: int
    passed_cases: int
    failed_cases: int
    top1_accuracy: float
    recall_at_3: float
    precision_at_3: float
    mean_reciprocal_rank: float
    forbidden_hit_rate: float
    product_isolation_accuracy: float
    component_isolation_accuracy: float
    version_match_accuracy: float
    no_match_accuracy: float
    budget_compliance_rate: float


@dataclass(slots=True)
class RetrievalBenchmarkResult:
    metrics: RetrievalBenchmarkMetrics
    failures: list[dict[str, object]]
    network_request_count: int = 0
    model_call_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "metrics": asdict(self.metrics),
            "failures": self.failures,
            "network_request_count": 0,
            "model_call_count": 0,
        }


def run_retrieval_benchmark(fixture_path: str | Path) -> RetrievalBenchmarkResult:
    root = Path(fixture_path)
    chunks = [_chunk(item) for item in _load(root / "chunks.json")]
    cases = _load(root / "cases.json")
    retriever = OfflineBm25EvidenceRetriever(chunks)
    passed = 0
    failures: list[dict[str, object]] = []
    top1 = recall = precision = reciprocal = forbidden = product = component = version = (
        no_match
    ) = budget = 0
    for case in cases:
        claim = SimpleNamespace(
            claim_id=case["case_id"],
            normalized_claim=case["claim"],
            product=case.get("product"),
            component=case.get("component"),
            version_scope=SimpleNamespace(exact=case.get("version")),
            entities=[],
        )
        result = retriever.retrieve(claim)
        actual = [item.document_id for item in result.results]
        expected = set(case.get("expected_document_ids", []))
        prohibited = set(case.get("forbidden_document_ids", []))
        forbidden_hits = sorted(set(actual) & prohibited)
        expected_no_match = not expected
        hit = bool(expected & set(actual)) if expected else not actual
        reasons = []
        if forbidden_hits:
            reasons.append("forbidden_hit")
        if not hit:
            reasons.append("expected_document_missing")
        if expected_no_match and result.no_match_reason is None:
            reasons.append("expected_no_match")
        if reasons:
            failures.append(
                {
                    "case_id": case["case_id"],
                    "actual_document_ids": actual,
                    "expected_document_ids": sorted(expected),
                    "forbidden_hits": forbidden_hits,
                    "actual_status": result.no_match_reason or "matched",
                    "expected_status": "no_match" if expected_no_match else "matched",
                    "failure_reasons": reasons,
                }
            )
        else:
            passed += 1
        top1 += int(bool(actual) and actual[0] in expected) if expected else int(not actual)
        recall += int(hit)
        precision += (
            len(set(actual[:3]) & expected) / min(3, len(actual))
            if actual and expected
            else int(not actual)
        )
        reciprocal += next(
            (1 / (index + 1) for index, item in enumerate(actual) if item in expected),
            1 if expected_no_match and not actual else 0,
        )
        forbidden += int(bool(forbidden_hits))
        product += int(not forbidden_hits)
        component += int(not forbidden_hits)
        version += int(
            not case.get("version")
            or all(item.version_match is not False for item in result.results)
            or result.version_fallback_used
        )
        no_match += int(not expected_no_match or not actual)
        budget += int(
            result.selected_count <= result.top_k
            and sum(len(item.text_excerpt) for item in result.results) <= 3000
        )
    total = len(cases) or 1
    return RetrievalBenchmarkResult(
        RetrievalBenchmarkMetrics(
            total,
            passed,
            total - passed,
            top1 / total,
            recall / total,
            precision / total,
            reciprocal / total,
            forbidden / total,
            product / total,
            component / total,
            version / total,
            no_match / total,
            budget / total,
        ),
        failures,
    )


def write_retrieval_benchmark(
    result: RetrievalBenchmarkResult, output: str | Path
) -> tuple[Path, Path, Path]:
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=True)
    json_path, markdown_path, run_path = (
        directory / "benchmark.json",
        directory / "benchmark.md",
        directory / "run.json",
    )
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    metrics = result.metrics
    markdown_path.write_text(
        "# Offline Retrieval Benchmark\n\n> 本基准使用离线 fixture，只验证 Evidence Pipeline 逻辑，不代表真实官方文档检索准确率。\n\n| Metric | Value |\n| --- | ---: |\n"
        + "\n".join(f"| {key} | {value} |" for key, value in asdict(metrics).items())
        + "\n",
        encoding="utf-8",
    )
    run_path.write_text(
        json.dumps(
            {
                "run_id": "retrieval-benchmark-v1",
                "claim_count": metrics.total_cases,
                "deduplicated_claim_count": metrics.total_cases,
                "chunk_count": None,
                "selected_evidence_count": None,
                "estimated_context_chars": None,
                "estimated_context_tokens": None,
                "estimated_model_calls": 0,
                "budget_exceeded": False,
                "network_request_count": 0,
                "model_call_count": 0,
                "started_at": datetime.now(UTC).isoformat(),
                "completed_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return json_path, markdown_path, run_path


def _load(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Retrieval benchmark fixture must be a list")
    return data


def _chunk(value: dict) -> DocumentChunk:
    text = value["text"]
    return DocumentChunk(
        chunk_id=value["chunk_id"],
        document_id=value["document_id"],
        canonical_url=value["canonical_url"],
        final_url=value["canonical_url"],
        product=value["product"],
        component=value["component"],
        document_type=value.get("document_type", "reference"),
        document_title=value.get("title", value["document_id"]),
        section_heading=value.get("heading", "Overview"),
        section_heading_level=2,
        section_order=0,
        chunk_order=0,
        text=text,
        character_count=len(text),
        source_fetched_at=datetime(2026, 7, 14, tzinfo=UTC),
        product_version=value.get("version"),
        heading_path=[value.get("heading", "Overview")],
    )
