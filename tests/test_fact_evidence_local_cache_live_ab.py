from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmarks"))

from fact_evidence_live_ab import (
    FactEvidenceLiveAbCase,
    FactEvidenceLiveAbEvaluator,
    FactEvidenceLiveAbRunConfig,
    LiveAbSafetyError,
    load_live_ab_cases,
    load_live_ab_fixture,
)

from agent_network.agents import FactAgent
from agent_network.evidence.cached_official_evidence import CachedEvidenceIndexBuilder
from agent_network.prompts import PromptRegistry


FETCHED_AT = "2026-07-13T00:00:00+00:00"


def _stable_hash(value: dict) -> str:
    stable = {key: item for key, item in value.items() if key != "source_fetched_at"}
    return sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_cached_document(root: Path, document_id: str, component: str, text: str) -> None:
    target = root / "phase8b" / "multi-doc" / "documents" / document_id
    target.mkdir(parents=True)
    url = f"https://ranchermanager.docs.rancher.com/fixture/{document_id}"
    cleaned = {
        "document_id": document_id,
        "canonical_url": url,
        "final_url": url,
        "product": "Rancher Manager",
        "component": component,
        "document_type": "reference",
        "title": f"{component} reference",
        "plain_text": text,
        "headings": [component],
        "sections": [{"heading": component, "heading_level": 2, "text": text, "order": 0}],
        "source_fetched_at": FETCHED_AT,
        "source_response_size_bytes": len(text.encode()),
    }
    raw = f"<html><main>{text}</main></html>".encode()
    metadata = {
        "document_id": document_id,
        "canonical_url": url,
        "final_url": url,
        "product": "Rancher Manager",
        "component": component,
        "document_type": "reference",
        "fetched_at": FETCHED_AT,
        "synced_at": FETCHED_AT,
        "status_code": 200,
        "content_type": "text/html",
        "response_size_bytes": len(raw),
        "raw_content_sha256": sha256(raw).hexdigest(),
        "cleaned_content_sha256": _stable_hash(cleaned),
        "etag": None,
        "last_modified": None,
        "cleaner_version": "1",
        "sync_status": "fetched",
    }
    (target / "raw.html").write_bytes(raw)
    (target / "cleaned.json").write_text(json.dumps(cleaned), encoding="utf-8")
    (target / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


class _CitationLlm:
    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.last_response_audit = {}

    def complete(self, **kwargs) -> str:
        self.calls += 1
        prompt = kwargs["user_prompt"]
        self.prompts.append(prompt)
        chunk_ids: list[str] = []
        if "<official_evidence_context>" in prompt:
            encoded = prompt.split("<official_evidence_context>\n", 1)[1].split(
                "\n</official_evidence_context>", 1
            )[0]
            context = json.loads(encoded)
            chunk_ids = (
                [context["official_evidences"][0]["chunk_id"], "invented"]
                if context["official_evidences"]
                else []
            )
        return json.dumps(
            {
                "summary": "supported",
                "evidence_chunk_ids": chunk_ids,
                "evidence_relation": "direct_support",
                "findings": [],
            }
        )


class _NeverCacheBuilder(CachedEvidenceIndexBuilder):
    def retrieve(self, request):
        raise AssertionError("OFF mode must not read local cache")


def _config(**overrides) -> FactEvidenceLiveAbRunConfig:
    values = {
        "enabled": True,
        "confirm_live_model_calls": True,
        "model": "deepseek-ai/DeepSeek-V4-Pro",
        "max_cases": 2,
        "case_ids": ("cluster-agent-cache", "rbac-cache"),
        "confirm_planned_call_count": 4,
        "evidence_provider": "local_cache",
        "cache_directory": "phase8b/multi-doc",
        "document_ids": (
            "rancher-downstream-cluster-communication",
            "rancher-rbac-reference",
        ),
        "max_documents": 2,
        "top_k": 5,
        "max_chunks_per_document": 1,
        "min_documents_in_results": 2,
        "min_score": 0.0,
        "min_matched_terms": 1,
        "exclude_navigation_like": True,
    }
    values.update(overrides)
    return FactEvidenceLiveAbRunConfig(**values)


def test_local_cache_fixture_has_six_controlled_cases() -> None:
    fixture = load_live_ab_fixture(Path("benchmarks/fixtures/fact-evidence-local-cache-ab-v1"))

    assert [case.case_id for case in fixture.cases[:2]] == ["cluster-agent-cache", "tunnel-cache"]
    assert len(fixture.cases) == 6
    assert "evidence_relation_correct" in fixture.human_review_template
    # The RBAC claim states the role distinction itself; the fixture evidence
    # explicitly names those role types, so direct_support is intentional.
    rbac = next(case for case in fixture.cases if case.case_id == "rbac-cache")
    assert rbac.expected_evidence_relation == "direct_support"


def test_local_cache_plan_is_four_calls_and_off_does_not_read_cache(tmp_path: Path) -> None:
    cases = load_live_ab_cases(
        Path("benchmarks/fixtures/fact-evidence-local-cache-ab-v1"),
        case_ids=("cluster-agent-cache", "rbac-cache"),
    )
    evaluator = FactEvidenceLiveAbEvaluator(
        None, local_cache_builder=_NeverCacheBuilder(cache_root=tmp_path)
    )
    off_only = _config(evidence_on_enabled=False, confirm_planned_call_count=2)
    local = _config()

    assert evaluator.plan(cases, off_only)["planned_fact_model_calls"] == 2
    with pytest.raises(AssertionError, match="OFF mode"):
        evaluator.plan(cases, local)


def test_local_cache_on_uses_fact_citation_validation_without_network(tmp_path: Path) -> None:
    _write_cached_document(
        tmp_path,
        "rancher-downstream-cluster-communication",
        "Cluster Agent",
        "Cluster Agent communicates with Rancher Server for downstream clusters. " * 5,
    )
    _write_cached_document(
        tmp_path,
        "rancher-rbac-reference",
        "RBAC",
        "Global Role Cluster Role and Project Role define Rancher authorization. " * 5,
    )
    cases = load_live_ab_cases(
        Path("benchmarks/fixtures/fact-evidence-local-cache-ab-v1"),
        case_ids=("cluster-agent-cache", "rbac-cache"),
    )
    llm = _CitationLlm()
    agent = FactAgent(llm=llm, prompts=PromptRegistry("prompts"), model="test")
    evaluator = FactEvidenceLiveAbEvaluator(
        agent,
        local_cache_builder=CachedEvidenceIndexBuilder(cache_root=tmp_path),
        human_review_template=load_live_ab_fixture(
            Path("benchmarks/fixtures/fact-evidence-local-cache-ab-v1")
        ).human_review_template,
    )

    plan = evaluator.plan(cases, _config())
    result = evaluator.run(cases, _config())
    on_results = [item for item in result.results if item.mode.lower() == "on"]

    assert (
        plan["planned_fact_model_calls"]
        == plan["planned_off_calls"] + plan["planned_on_calls"]
        == 4
    )
    assert plan["network_request_count"] == 0
    assert llm.calls == 4
    assert all(item.evidence_provider == "local_cache" for item in on_results)
    assert all(item.network_request_count == 0 for item in result.results)
    assert all(item.rejected_reference_count == 1 for item in on_results)
    assert all(item.loaded_document_count >= 1 for item in on_results)
    assert {document_id for item in on_results for document_id in item.evidence_document_ids} == {
        "rancher-downstream-cluster-communication",
        "rancher-rbac-reference",
    }
    assert all(item.human_review["evidence_relation_correct"] == "unclear" for item in on_results)
    assert result.summary["total_model_call_count"] == 4
    assert result.summary["total_network_request_count"] == 0


def test_local_cache_can_inject_two_documents_for_one_cross_component_claim(tmp_path: Path) -> None:
    _write_cached_document(
        tmp_path,
        "rancher-downstream-cluster-communication",
        "Cluster Agent",
        "Cluster Agent communicates with Rancher Server for downstream clusters. " * 5,
    )
    _write_cached_document(
        tmp_path,
        "rancher-rbac-reference",
        "RBAC",
        "ServiceAccount RBAC authorizes access to downstream cluster resources. " * 5,
    )
    case = FactEvidenceLiveAbCase(
        "cross-component",
        "Cluster Agent ServiceAccount RBAC manages downstream clusters.",
        "Rancher Manager",
        None,
        "supported",
        "official_evidence_available",
        ["rancher-downstream-cluster-communication", "rancher-rbac-reference"],
        [],
        "Cross-component local cache retrieval.",
        expected_evidence_relation="direct_support",
    )
    llm = _CitationLlm()
    evaluator = FactEvidenceLiveAbEvaluator(
        FactAgent(llm=llm, prompts=PromptRegistry("prompts"), model="test"),
        local_cache_builder=CachedEvidenceIndexBuilder(cache_root=tmp_path),
    )
    config = _config(
        case_ids=("cross-component",),
        max_cases=1,
        confirm_planned_call_count=2,
    )

    result = evaluator.run([case], config)
    on_result = [item for item in result.results if item.mode.lower() == "on"][0]

    assert on_result.loaded_document_count == 2
    assert on_result.returned_document_count == 2
    assert '"document_id":"rancher-downstream-cluster-communication"' in llm.prompts[1]
    assert '"document_id":"rancher-rbac-reference"' in llm.prompts[1]
    assert on_result.network_request_count == 0


def test_local_cache_failures_and_live_guards_are_safe(tmp_path: Path) -> None:
    cases = load_live_ab_cases(
        Path("benchmarks/fixtures/fact-evidence-local-cache-ab-v1"),
        case_ids=("cluster-agent-cache",),
    )
    agent = FactAgent(llm=_CitationLlm(), prompts=PromptRegistry("prompts"), model="test")
    evaluator = FactEvidenceLiveAbEvaluator(
        agent, local_cache_builder=CachedEvidenceIndexBuilder(cache_root=tmp_path)
    )
    missing = _config(case_ids=("cluster-agent-cache",), max_cases=1, confirm_planned_call_count=2)

    result = evaluator.run(cases, missing)
    on_result = [item for item in result.results if item.mode.lower() == "on"][0]
    assert on_result.evidence_status == "official_evidence_unavailable"
    assert on_result.evidence_relation == "unavailable"
    assert on_result.network_request_count == 0

    with pytest.raises(LiveAbSafetyError, match="call plan"):
        evaluator.run(
            cases,
            _config(
                case_ids=("cluster-agent-cache",),
                max_cases=1,
                confirm_planned_call_count=2,
                timeout_seconds=601,
            ),
        )


def test_off_only_run_does_not_read_local_cache(tmp_path: Path) -> None:
    case = load_live_ab_cases(
        Path("benchmarks/fixtures/fact-evidence-local-cache-ab-v1"),
        case_ids=("cluster-agent-cache",),
    )
    llm = _CitationLlm()
    evaluator = FactEvidenceLiveAbEvaluator(
        FactAgent(llm=llm, prompts=PromptRegistry("prompts"), model="test"),
        local_cache_builder=_NeverCacheBuilder(cache_root=tmp_path),
    )

    result = evaluator.run(
        case,
        _config(
            case_ids=("cluster-agent-cache",),
            max_cases=1,
            confirm_planned_call_count=1,
            evidence_on_enabled=False,
        ),
    )

    assert llm.calls == result.summary["total_model_call_count"] == 1
    assert result.summary["total_network_request_count"] == 0
