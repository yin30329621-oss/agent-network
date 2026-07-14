from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

from agent_network.claim.engine import (
    ClaimVerificationBatchResult,
    ClaimVerificationEngineResult,
)
from agent_network.claim.extractor import ClaimExtractionRequest, DeterministicClaimExtractor
from agent_network.claim.fact_integration import build_claim_verification_fact_context
from agent_network.claim.verification import EvidenceLink, VerificationResult
from agent_network.evidence.fact_evidence import FactEvidenceLimits
from agent_network.evidence.cached_official_evidence import CachedEvidenceIndexBuilder
from agent_network.prompts import PromptRegistry
from agent_network.schemas import ReviewRequest
from agent_network.workflow import ReviewWorkflow


FETCHED_AT = "2026-07-14T00:00:00+00:00"


def _stable_hash(value: dict) -> str:
    stable = {key: item for key, item in value.items() if key != "source_fetched_at"}
    raw = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    return sha256(raw).hexdigest()


def _write_cached_document(root: Path, document_id: str, text: str) -> None:
    document_root = root / "case" / "documents" / document_id
    document_root.mkdir(parents=True)
    url = f"https://ranchermanager.docs.rancher.com/fixture/{document_id}"
    cleaned = {
        "document_id": document_id,
        "canonical_url": url,
        "final_url": url,
        "product": "Rancher Manager",
        "component": "Cluster Agent",
        "document_type": "architecture",
        "title": "Cluster Agent connection",
        "plain_text": text,
        "headings": ["Connection"],
        "sections": [{"heading": "Connection", "heading_level": 2, "text": text, "order": 0}],
        "source_fetched_at": FETCHED_AT,
        "source_response_size_bytes": len(text.encode()),
    }
    raw = f"<main>{text}</main>".encode()
    metadata = {
        "document_id": document_id,
        "canonical_url": url,
        "final_url": url,
        "product": "Rancher Manager",
        "component": "Cluster Agent",
        "document_type": "architecture",
        "raw_content_sha256": sha256(raw).hexdigest(),
        "cleaned_content_sha256": _stable_hash(cleaned),
        "cleaner_version": "1",
    }
    (document_root / "raw.html").write_bytes(raw)
    (document_root / "cleaned.json").write_text(json.dumps(cleaned), encoding="utf-8")
    (document_root / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


class _StubLlm:
    def __init__(self, *, unknown_citation: bool = False) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.unknown_citation = unknown_citation
        self.last_response_audit = {
            "model_call_count": 1,
            "request_attempt_count": 1,
            "retry_count": 0,
            "timeout_count": 0,
        }

    def complete(self, **kwargs) -> str:
        self.calls += 1
        prompt = kwargs["user_prompt"]
        self.prompts.append(prompt)
        chunk_ids = re.findall(r'"chunk_id":"([^"]+)"', prompt)
        return json.dumps(
            {
                "summary": "review",
                "evidence_chunk_ids": ["unknown"] if self.unknown_citation else chunk_ids[:1],
                "evidence_relation": "direct_support",
                "findings": [
                    {
                        "severity": "low",
                        "location": "Architecture",
                        "issue": "Claim requires review.",
                        "reason": "Verification is candidate-only.",
                        "evidence_needed": "Official source.",
                        "reference": None,
                        "suggestion": "Add evidence.",
                        "confidence": 0.6,
                    }
                ],
            }
        )


def _workflow(root: Path, llm: _StubLlm, *, enabled: bool = True) -> ReviewWorkflow:
    workflow = ReviewWorkflow.from_llm(
        llm=llm,
        prompts=PromptRegistry("prompts"),
        fact_local_cache_builder=CachedEvidenceIndexBuilder(cache_root=root),
        fact_evidence_config={
            "enabled": enabled,
            "provider": "local_cache",
            "allow_network": False,
            "top_k": 5,
            "max_chars_per_evidence": 1600,
            "max_total_evidence_chars": 6000,
            "local_cache": {"cache_directory": "case", "max_documents": 1},
            "claim_verification": {
                "enabled": enabled,
                "max_claims": 4,
                "product": "Rancher Manager",
                "default_component": "Cluster Agent",
                "verification_mode": "candidate_only",
            },
        },
    )
    workflow.merge_agent.model = "test-merge"
    return workflow


def _request() -> ReviewRequest:
    return ReviewRequest(
        markdown=(
            "# Architecture\n\n"
            "Cluster Agent connects to Rancher Server through a tunnel.\n\n"
            "Rancher Server manages downstream clusters through the connection."
        ),
        source_name="report.md",
    )


def test_claim_verification_bundle_uses_one_fact_call_and_preserves_four_call_workflow(
    tmp_path: Path,
) -> None:
    _write_cached_document(
        tmp_path,
        "cluster",
        "Cluster Agent connects to Rancher Server through a tunnel for downstream clusters. " * 4,
    )
    llm = _StubLlm()

    result = _workflow(tmp_path, llm).run(_request())
    fact = result.agent_reviews[0]

    assert llm.calls == 4
    assert "<claim_verification_bundle>" in llm.prompts[0]
    bundle_text = llm.prompts[0].split("<claim_verification_bundle>", 1)[1]
    assert bundle_text.count('"claim_id"') == 2
    assert fact.claim_verification_claim_count == 2
    assert fact.claim_verification_model_call_count == 0
    assert fact.claim_verification_network_request_count == 0
    assert (
        fact.evidence_relation is not None and fact.evidence_relation.value == "indirect_evidence"
    )
    assert fact.evidence_chunk_ids
    assert "raw.html" not in llm.prompts[0]
    extracted = DeterministicClaimExtractor().extract(
        ClaimExtractionRequest(document_text=_request().markdown, source_name="report.md")
    )
    expected_claims = {
        claim.claim_id: (claim.normalized_text, claim.claim_type.value)
        for claim in extracted.claims
    }
    assert fact.claim_verification_bundle
    for entry in fact.claim_verification_bundle:
        assert entry["normalized_text"] == expected_claims[entry["claim_id"]][0]
        assert entry["claim_type"] == expected_claims[entry["claim_id"]][1]


def test_claim_bundle_degrades_and_keeps_citation_validation_without_extra_calls(
    tmp_path: Path,
) -> None:
    llm = _StubLlm(unknown_citation=True)

    result = _workflow(tmp_path, llm).run(_request())
    fact = result.agent_reviews[0]

    assert llm.calls == 4
    assert fact.claim_verification_claim_count == 2
    assert fact.claim_verification_failed_count == 2
    assert fact.evidence_chunk_ids == []
    assert "unknown_evidence_chunk_id:unknown" in fact.evidence_warnings
    assert fact.evidence_network_request_count == 0
    serialized = fact.to_dict()
    assert serialized["claim_verification_unavailable_count"] == 2
    assert serialized["claim_verification_bundle"]


def test_claim_verification_disabled_preserves_existing_fact_request(tmp_path: Path) -> None:
    llm = _StubLlm()

    _workflow(tmp_path, llm, enabled=False).run(_request())

    assert llm.calls == 4
    assert "<claim_verification_bundle>" not in llm.prompts[0]


def _verification_result(
    claim_id: str,
    status: str,
    relation: str,
    *,
    with_evidence: bool,
) -> ClaimVerificationEngineResult:
    link = (
        EvidenceLink(
            evidence_id=f"evidence-{claim_id}",
            claim_id=claim_id,
            chunk_id=f"chunk-{claim_id}",
            document_id=f"document-{claim_id}",
            canonical_url=f"https://ranchermanager.docs.rancher.com/{claim_id}",
            rank=1,
            relation=relation,
            matched_terms=["claim"],
            score=1.5,
        )
        if with_evidence
        else None
    )
    verification = VerificationResult(
        claim_id=claim_id,
        claim_text=f"Claim {claim_id}",
        normalized_text=f"claim {claim_id}",
        claim_type="technical_behavior",
        verification_status=status,
        evidence_relation=relation,
        evidence_links=[link] if link else [],
        evidence_limitations=["Human review remains required."] if with_evidence else [],
        limitations=["Human review remains required."] if with_evidence else [],
        explanation="Fixture verification result.",
    )
    candidate_evidences = (
        [
            {
                "rank": 1,
                "score": 1.5,
                "matched_terms": ["claim"],
                "chunk_id": link.chunk_id,
                "document_id": link.document_id,
                "canonical_url": link.canonical_url,
                "product": "Rancher Manager",
                "component": "Cluster Agent",
                "document_type": "architecture",
                "document_title": "Fixture",
                "section_heading": "Evidence",
                "text": "Controlled evidence text.",
                "source_fetched_at": FETCHED_AT,
            }
        ]
        if link
        else []
    )
    return ClaimVerificationEngineResult(
        verification=verification,
        candidate_evidences=candidate_evidences,
    )


def test_claim_verification_bundle_serializes_audit_and_evidence_links() -> None:
    fixture_path = Path("benchmarks/fixtures/claim-verification-v1/bundle-statuses.json")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    status_pairs = [(item["verification_status"], item["evidence_relation"]) for item in fixture]
    results = [
        _verification_result("bundle-supported", *status_pairs[0], with_evidence=True),
        _verification_result("bundle-insufficient", *status_pairs[1], with_evidence=True),
        _verification_result("bundle-unavailable", *status_pairs[2], with_evidence=False),
        _verification_result("bundle-time-sensitive", *status_pairs[3], with_evidence=True),
    ]
    batch = ClaimVerificationBatchResult(
        total_claim_count=4,
        completed_claim_count=4,
        failed_claim_count=0,
        status_distribution={status: 1 for status, _ in status_pairs},
        relation_distribution={"direct_support": 1, "indirect_evidence": 2, "unavailable": 1},
        evidence_coverage_count=3,
        zero_evidence_count=1,
        results=results,
        failures=[],
    )

    context = build_claim_verification_fact_context(
        batch,
        FactEvidenceLimits(),
        cache_directory="phase8b/multi-doc",
    )

    assert (
        json.loads(json.dumps(context["claim_verification_bundle"]))
        == context["claim_verification_bundle"]
    )
    assert context["claim_verification_claim_count"] == 4
    assert context["claim_verification_status_distribution"] == {
        status: 1 for status, _ in status_pairs
    }
    assert context["claim_verification_relation_distribution"]["indirect_evidence"] == 2
    assert context["claim_verification_evidence_coverage_count"] == 3
    assert context["claim_verification_unavailable_count"] == 1
    assert context["claim_verification_insufficient_evidence_count"] == 1
    assert context["claim_verification_extraction_failed_count"] == 0
    supported = context["claim_verification_bundle"][0]
    assert supported["claim_id"] == "bundle-supported"
    assert supported["verification_status"] == "verified_supported"
    assert supported["evidence_links"] == [
        {
            "evidence_id": "evidence-bundle-supported",
            "chunk_id": "chunk-bundle-supported",
            "document_id": "document-bundle-supported",
            "canonical_url": "https://ranchermanager.docs.rancher.com/bundle-supported",
            "relation": "direct_support",
        }
    ]
    assert supported["evidence_limitations"] == ["Human review remains required."]
    assert context["claim_verification_model_call_count"] == 0
    assert context["claim_verification_network_request_count"] == 0
