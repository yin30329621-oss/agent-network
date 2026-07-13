from datetime import UTC, datetime
import json

import pytest

from agent_network.agents import FactAgent
from agent_network.evidence.fact_evidence import FactEvidenceLimits, build_fact_evidence_context
from agent_network.evidence.official_evidence_retriever import (
    OfficialEvidenceDocumentFailure,
    OfficialEvidenceRetrievalResult,
    RetrievedOfficialEvidence,
)
from agent_network.prompts import PromptRegistry
from agent_network.schemas import ReviewRequest
from agent_network.workflow import ReviewWorkflow


FETCHED_AT = datetime(2026, 7, 13, tzinfo=UTC)


def evidence(
    chunk_id: str, text: str = "Cluster Agent opens a reverse tunnel."
) -> RetrievedOfficialEvidence:
    return RetrievedOfficialEvidence(
        rank=1,
        score=2.0,
        matched_terms=["cluster", "agent", "reverse", "tunnel"],
        chunk_id=chunk_id,
        document_id="cluster-agent-doc",
        canonical_url="https://ranchermanager.docs.rancher.com/fixture/cluster-agent",
        final_url="https://ranchermanager.docs.rancher.com/fixture/cluster-agent",
        product="Rancher Manager",
        component="Cluster Agent",
        document_type="architecture",
        document_title="Cluster Agent communication",
        section_heading="Reverse tunnel",
        section_order=0,
        chunk_order=0,
        text=text,
        source_fetched_at=FETCHED_AT,
    )


def retrieval_result(
    status: str = "success", evidences: list[RetrievedOfficialEvidence] | None = None
) -> OfficialEvidenceRetrievalResult:
    values = evidences if evidences is not None else [evidence("chunk-1")]
    return OfficialEvidenceRetrievalResult(
        query_text="Cluster Agent reverse tunnel",
        status=status,
        catalog_match_count=1,
        selected_document_count=1,
        processed_document_count=1 if status != "all_documents_failed" else 0,
        failed_document_count=1 if status == "partial_success" else 0,
        total_chunk_count=len(values),
        returned_evidence_count=len(values),
        network_request_count=0,
        evidences=values,
        document_failures=(
            [
                OfficialEvidenceDocumentFailure(
                    document_id="missing-doc",
                    canonical_url="https://ranchermanager.docs.rancher.com/fixture/missing",
                    stage="content_provider",
                    error_code="content_unavailable",
                    safe_message="No offline content is available for this catalog document",
                )
            ]
            if status == "partial_success"
            else []
        ),
        retrieval_started_at=FETCHED_AT,
        retrieval_completed_at=FETCHED_AT,
    )


class CapturingLLM:
    def __init__(
        self, chunk_ids: list[str] | None = None, *, include_finding: bool = False
    ) -> None:
        self.calls = 0
        self.user_prompts: list[str] = []
        self.chunk_ids = chunk_ids or []
        self.include_finding = include_finding
        self.last_response_audit = {}

    def complete(self, **kwargs) -> str:
        self.calls += 1
        self.user_prompts.append(kwargs["user_prompt"])
        return json.dumps(
            {
                "summary": "Fact result",
                "evidence_chunk_ids": self.chunk_ids,
                "findings": (
                    [
                        {
                            "severity": "low",
                            "location": "Summary",
                            "issue": "Needs evidence",
                            "reason": "The claim requires support.",
                            "evidence_needed": "Official source",
                            "reference": "https://invented.invalid/reference",
                            "suggestion": "Add a citation.",
                            "confidence": 0.7,
                        }
                    ]
                    if self.include_finding
                    else []
                ),
            }
        )


def test_fact_evidence_context_enforces_limits_and_preserves_order() -> None:
    result = retrieval_result(
        evidences=[evidence("chunk-1", "a" * 10), evidence("chunk-2", "b" * 10)]
    )

    context = build_fact_evidence_context(
        result, FactEvidenceLimits(top_k=2, max_chars_per_evidence=8, max_total_evidence_chars=12)
    )

    assert [item["chunk_id"] for item in context["official_evidences"]] == ["chunk-1", "chunk-2"]
    assert [item["text"] for item in context["official_evidences"]] == ["a" * 8, "b" * 4]
    assert all(item["text_truncated"] for item in context["official_evidences"])
    assert "evidence_text_truncated" in context["evidence_limitations"]


def test_fact_agent_injects_bounded_evidence_and_validates_model_citations() -> None:
    context = build_fact_evidence_context(retrieval_result(), FactEvidenceLimits())
    llm = CapturingLLM(["chunk-1", "unknown", "chunk-1"])
    agent = FactAgent(llm=llm, prompts=PromptRegistry("prompts"))

    review = agent.review(ReviewRequest(markdown="# Report", fact_evidence_context=context))

    assert llm.calls == 1
    assert "<official_evidence_context>" in llm.user_prompts[0]
    assert "untrusted reference data" in llm.user_prompts[0]
    assert "<html" not in llm.user_prompts[0]
    assert review.evidence_chunk_ids == ["chunk-1"]
    assert review.evidence_document_ids == ["cluster-agent-doc"]
    assert review.evidence_urls == ["https://ranchermanager.docs.rancher.com/fixture/cluster-agent"]
    assert review.evidence_used is True
    assert review.evidence_warnings == ["unknown_evidence_chunk_id:unknown"]
    assert review.to_dict()["retrieval_status"] == "success"


@pytest.mark.parametrize(
    ("status", "evidence_status", "limitation"),
    [
        ("no_catalog_match", "official_evidence_unavailable", "retrieval_status:no_catalog_match"),
        ("no_chunk_match", "insufficient_official_evidence", "retrieval_status:no_chunk_match"),
        (
            "all_documents_failed",
            "official_evidence_unavailable",
            "retrieval_status:all_documents_failed",
        ),
    ],
)
def test_fact_evidence_degrades_without_fabricated_citations(
    status: str, evidence_status: str, limitation: str
) -> None:
    context = build_fact_evidence_context(retrieval_result(status, []), FactEvidenceLimits())
    llm = CapturingLLM(["invented-chunk"])
    review = FactAgent(llm=llm, prompts=PromptRegistry("prompts")).review(
        ReviewRequest(markdown="# Report", fact_evidence_context=context)
    )

    assert review.evidence_status == evidence_status
    assert review.evidence_used is False
    assert review.evidence_chunk_ids == []
    assert review.evidence_warnings == ["unknown_evidence_chunk_id:invented-chunk"]
    assert limitation in review.evidence_limitations


def test_partial_success_keeps_evidence_and_records_document_limitations() -> None:
    context = build_fact_evidence_context(retrieval_result("partial_success"), FactEvidenceLimits())
    review = FactAgent(llm=CapturingLLM(["chunk-1"]), prompts=PromptRegistry("prompts")).review(
        ReviewRequest(markdown="# Report", fact_evidence_context=context)
    )

    assert review.evidence_status == "official_evidence_partial"
    assert review.evidence_chunk_ids == ["chunk-1"]
    assert "document_processing_failures_present" in review.evidence_limitations


class StubRetriever:
    def __init__(self, result: OfficialEvidenceRetrievalResult | Exception) -> None:
        self.result = result
        self.calls = 0

    def retrieve(self, request):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_workflow_uses_retriever_once_before_fact_and_keeps_four_model_calls() -> None:
    llm = CapturingLLM(["chunk-1"], include_finding=True)
    retriever = StubRetriever(retrieval_result())
    workflow = ReviewWorkflow.from_llm(
        llm=llm,
        prompts=PromptRegistry("prompts"),
        fact_evidence_retriever=retriever,
        fact_evidence_config={"enabled": True, "top_k": 5, "allow_network": False},
    )
    workflow.merge_agent.model = "test-merge"

    result = workflow.run(
        ReviewRequest(
            markdown="# Report",
            fact_evidence_query={
                "query_text": "Cluster Agent reverse tunnel",
                "claim_id": "claim-1",
            },
        )
    )

    fact = result.agent_reviews[0]
    assert retriever.calls == 1
    assert llm.calls == 4
    assert fact.evidence_chunk_ids == ["chunk-1"]
    assert fact.evidence_network_request_count == 0
    assert fact.findings[0].reference is None
    assert "unknown_evidence_url" in fact.evidence_warnings
    assert all("<official_evidence_context>" not in prompt for prompt in llm.user_prompts[1:3])


def test_recoverable_retriever_error_and_disabled_feature_keep_fact_running() -> None:
    llm = CapturingLLM()
    workflow = ReviewWorkflow.from_llm(
        llm=llm,
        prompts=PromptRegistry("prompts"),
        fact_evidence_retriever=StubRetriever(RuntimeError("offline failure")),
        fact_evidence_config={"enabled": True},
    )
    degraded = workflow.run_only(
        ReviewRequest(markdown="# Report", fact_evidence_query={"query_text": "claim"}), "fact"
    )
    disabled = FactAgent(llm=CapturingLLM(), prompts=PromptRegistry("prompts")).review(
        ReviewRequest(markdown="# Report")
    )

    assert degraded.agent_reviews[0].retrieval_status == "retrieval_error"
    assert degraded.agent_reviews[0].evidence_used is False
    assert llm.calls == 1
    assert disabled.retrieval_status is None
