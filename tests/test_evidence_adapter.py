from __future__ import annotations

from agent_network.claim.claim import Claim
from agent_network.claim.evidence_adapter import (
    ClaimEvidenceAdapter,
    ClaimEvidenceAdapterRequest,
    EvidenceAdapterConfig,
)
from agent_network.claim.evidence_decision import EvidenceDecisionEngine
from agent_network.claim.registry import ClaimRegistry
from agent_network.evidence.offline_retrieval import RetrievalResult, SelectedEvidence


def make_claim(claim_id: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        text=f"Rancher supports {claim_id} integration",
        normalized_text=f"rancher supports {claim_id} integration",
    )


def make_retrieval(claim: Claim, *, with_evidence: bool = True) -> RetrievalResult:
    evidence = SelectedEvidence(
        chunk_id=f"chunk-{claim.claim_id}",
        document_id="doc-1",
        canonical_url="https://docs.example.test/doc-1",
        heading_path=["Rancher", "Support"],
        text_excerpt=claim.text,
        bm25_score=1.0,
        final_score=1.0,
        matched_terms=["rancher", "supports"],
        product_match=True,
        component_match=None,
        version_match=True,
        document_type="official",
        source_priority=1,
        selection_reason="test",
        evidence_limitations=[],
    )
    return RetrievalResult(
        claim_id=claim.claim_id,
        query_terms=["rancher", "supports"],
        candidate_count=1 if with_evidence else 0,
        filtered_candidate_count=1 if with_evidence else 0,
        selected_count=1 if with_evidence else 0,
        top_k=5,
        results=[evidence] if with_evidence else [],
        no_match_reason=None if with_evidence else "no_matching_chunk",
    )


class RecordingRetriever:
    model_call_count = 0
    network_request_count = 0

    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()
        self.calls: list[str] = []

    def retrieve(self, claim: Claim, *, top_k: int | None = None) -> RetrievalResult:
        self.calls.append(claim.claim_id)
        if claim.claim_id in self.failures:
            raise RuntimeError("test retrieval failure")
        return make_retrieval(claim)


class RecordingDecisionEngine(EvidenceDecisionEngine):
    def __init__(self) -> None:
        self.calls = 0

    def decide_batch(self, pairs):
        self.calls += 1
        return super().decide_batch(pairs)


def test_adapter_preserves_registry_order_and_claim_id_alignment() -> None:
    claims = [make_claim("c1"), make_claim("c2")]
    retriever = RecordingRetriever()
    engine = RecordingDecisionEngine()

    result = ClaimEvidenceAdapter(
        retriever, decision_engine=engine, config=EvidenceAdapterConfig(top_k=3)
    ).adapt(
        ClaimEvidenceAdapterRequest(
            registry=ClaimRegistry(claims),
            config=EvidenceAdapterConfig(top_k=3),
        )
    )

    assert result.claim_ids == ["c1", "c2"]
    assert [item.retrieval.claim_id for item in result.results if item.retrieval] == ["c1", "c2"]
    assert [item.decision.claim_id for item in result.results if item.decision] == ["c1", "c2"]
    assert retriever.calls == ["c1", "c2"]
    assert engine.calls == 1


def test_adapter_keeps_failure_slot_and_distinguishes_retrieval_failure() -> None:
    claims = [make_claim("c1"), make_claim("c2")]
    retriever = RecordingRetriever({"c2"})

    result = ClaimEvidenceAdapter(retriever).adapt(ClaimRegistry(claims))

    assert result.claim_ids == ["c1", "c2"]
    assert result.results[0].decision is not None
    assert result.results[1].retrieval is None
    assert result.results[1].failure is not None
    assert result.results[1].failure.stage == "retrieval"
    assert result.results[1].failure.code == "retrieval_failed"
    assert result.completed_claim_count == 1
    assert result.failed_claim_count == 1


def test_adapter_preserves_empty_evidence_as_decision() -> None:
    claim = make_claim("c1")

    class EmptyRetriever(RecordingRetriever):
        def retrieve(self, claim: Claim, *, top_k: int | None = None) -> RetrievalResult:
            self.calls.append(claim.claim_id)
            return make_retrieval(claim, with_evidence=False)

    result = ClaimEvidenceAdapter(EmptyRetriever()).adapt(ClaimRegistry([claim]))

    assert result.results[0].failure is None
    assert result.results[0].decision is not None
    assert result.results[0].decision.status.value == "insufficient_evidence"
    assert result.evidence_coverage_count == 0


def test_empty_registry_does_not_call_retriever_or_decision_engine() -> None:
    retriever = RecordingRetriever()
    engine = RecordingDecisionEngine()

    result = ClaimEvidenceAdapter(retriever, decision_engine=engine).adapt(ClaimRegistry())

    assert result.results == []
    assert result.total_claim_count == 0
    assert result.completed_claim_count == 0
    assert result.failed_claim_count == 0
    assert result.model_call_count == 0
    assert result.network_request_count == 0
    assert retriever.calls == []
    assert engine.calls == 0


def test_adapter_does_not_invoke_fact_review_and_tracks_zero_calls() -> None:
    retriever = RecordingRetriever()
    result = ClaimEvidenceAdapter(retriever).adapt(ClaimRegistry([make_claim("c1")]))

    assert result.model_call_count == 0
    assert result.network_request_count == 0
    assert not hasattr(retriever, "review_batch")
    assert result.results[0].decision is not None
