import json
from hashlib import sha256
from pathlib import Path

from agent_network.claim import (
    Claim,
    ClaimRegistry,
    ClaimType,
    ClaimVerificationBatchRequest,
    ClaimVerificationEngine,
    ClaimVerificationRequest,
    EvidenceRelation,
    VerificationStatus,
    query_for_claim,
)
from agent_network.evidence.cached_official_evidence import CachedEvidenceIndexBuilder


FETCHED_AT = "2026-07-14T00:00:00+00:00"


def _stable_hash(value: dict) -> str:
    stable = {key: item for key, item in value.items() if key != "source_fetched_at"}
    return sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_cache(root: Path, document_id: str, *, text: str, product: str, component: str) -> None:
    path = root / "case" / "documents" / document_id
    path.mkdir(parents=True)
    url = f"https://ranchermanager.docs.rancher.com/fixture/{document_id}"
    cleaned = {
        "document_id": document_id,
        "canonical_url": url,
        "final_url": url,
        "product": product,
        "component": component,
        "document_type": "architecture",
        "title": document_id,
        "plain_text": text,
        "headings": ["Overview"],
        "sections": [{"heading": "Overview", "heading_level": 2, "text": text, "order": 0}],
        "source_fetched_at": FETCHED_AT,
        "source_response_size_bytes": len(text),
    }
    raw = f"<main>{text}</main>".encode()
    metadata = {
        "document_id": document_id,
        "canonical_url": url,
        "final_url": url,
        "product": product,
        "component": component,
        "document_type": "architecture",
        "raw_content_sha256": sha256(raw).hexdigest(),
        "cleaned_content_sha256": _stable_hash(cleaned),
        "cleaner_version": "1",
    }
    (path / "raw.html").write_bytes(raw)
    (path / "cleaned.json").write_text(json.dumps(cleaned), encoding="utf-8")
    (path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def engine(root: Path) -> ClaimVerificationEngine:
    return ClaimVerificationEngine(CachedEvidenceIndexBuilder(cache_root=root))


def claim(**overrides) -> Claim:
    values = {
        "claim_id": "claim-001",
        "text": "Cluster Agent connects to Rancher Server through a tunnel.",
        "product": "Rancher Manager",
        "component": "Cluster Agent",
        "claim_type": ClaimType.ARCHITECTURE,
    }
    values.update(overrides)
    return Claim(**values)


def test_query_uses_claim_metadata_without_guessing_filters() -> None:
    derived = query_for_claim(claim(), document_ids=("doc-a", "doc-a", "doc-b"))
    unscoped = query_for_claim(claim(product=None, component=None))

    assert derived.query_text == "cluster agent connects to rancher server through a tunnel."
    assert derived.product == "Rancher Manager"
    assert derived.document_ids == ("doc-a", "doc-b")
    assert unscoped.product is None and unscoped.component is None


def test_candidates_are_indirect_and_never_auto_supported(tmp_path: Path) -> None:
    write_cache(
        tmp_path,
        "cluster",
        text="Cluster Agent connects to Rancher Server through a tunnel for downstream clusters. "
        * 4,
        product="Rancher Manager",
        component="Cluster Agent",
    )
    result = engine(tmp_path).verify(
        ClaimVerificationRequest(claim=claim(), cache_directory="case")
    )

    verification = result.verification
    assert verification.verification_status is VerificationStatus.INSUFFICIENT_EVIDENCE
    assert verification.evidence_relation is EvidenceRelation.INDIRECT_EVIDENCE
    assert verification.evidence_links[0].relation is EvidenceRelation.INDIRECT_EVIDENCE
    assert verification.model_call_count == verification.network_request_count == 0
    assert verification.evidence_links[0].canonical_url.endswith("/cluster")


def test_no_result_and_missing_cache_degrade_without_network(tmp_path: Path) -> None:
    write_cache(
        tmp_path,
        "cluster",
        text="Cluster Agent connects to Rancher Server.",
        product="Rancher Manager",
        component="Cluster Agent",
    )
    no_match = engine(tmp_path).verify(
        ClaimVerificationRequest(
            claim=claim(text="Fleet Bundle deploys GitOps resources.", component="Fleet Agent"),
            cache_directory="case",
        )
    )
    missing = engine(tmp_path).verify(
        ClaimVerificationRequest(claim=claim(), cache_directory="missing")
    )

    assert no_match.verification.verification_status is VerificationStatus.NOT_MENTIONED
    assert no_match.verification.evidence_relation is EvidenceRelation.ABSENCE_OF_SUPPORT
    assert missing.verification.verification_status is VerificationStatus.UNAVAILABLE
    assert missing.failure is not None and missing.failure.code == "cache_not_found"
    assert missing.verification.network_request_count == 0


def test_temporal_claim_requires_external_verification_and_stable_links(tmp_path: Path) -> None:
    write_cache(
        tmp_path,
        "release",
        text="CVE-2026-1234 is listed in a release advisory.",
        product="Rancher Manager",
        component="Release",
    )
    temporal = claim(
        claim_id="claim-cve",
        text="CVE-2026-1234 is fixed in the latest release.",
        component=None,
        claim_type=ClaimType.VERSION_SUPPORT,
    )
    first = engine(tmp_path).verify(
        ClaimVerificationRequest(claim=temporal, cache_directory="case")
    )
    second = engine(tmp_path).verify(
        ClaimVerificationRequest(claim=temporal, cache_directory="case")
    )

    assert first.verification.verification_status is VerificationStatus.NEEDS_EXTERNAL_VERIFICATION
    assert "may be stale" in first.verification.limitations[0]
    assert [link.evidence_id for link in first.verification.evidence_links] == [
        link.evidence_id for link in second.verification.evidence_links
    ]


def test_batch_is_stable_and_fail_soft_for_broken_documents(tmp_path: Path) -> None:
    write_cache(
        tmp_path,
        "good",
        text="Cluster Agent connects to Rancher Server through a tunnel." * 4,
        product="Rancher Manager",
        component="Cluster Agent",
    )
    broken = tmp_path / "case" / "documents" / "broken"
    broken.mkdir()
    (broken / "metadata.json").write_text("{", encoding="utf-8")
    registry = ClaimRegistry(
        [
            claim(),
            claim(
                claim_id="claim-missing",
                text="Fleet Bundle deploys GitOps resources.",
                component="Fleet Agent",
            ),
        ]
    )

    result = engine(tmp_path).verify_batch(
        ClaimVerificationBatchRequest(registry=registry, cache_directory="case", max_documents=2)
    )

    assert [item.claim_id for item in result.results] == ["claim-001", "claim-missing"]
    assert result.status_distribution["insufficient_evidence"] == 1
    assert result.status_distribution["unavailable"] == 1
    assert result.evidence_coverage_count == 1
    assert result.model_call_count == result.network_request_count == 0


def test_all_broken_cache_returns_safe_failure(tmp_path: Path) -> None:
    broken = tmp_path / "case" / "documents" / "broken"
    broken.mkdir(parents=True)
    (broken / "metadata.json").write_text("{", encoding="utf-8")

    result = engine(tmp_path).verify(
        ClaimVerificationRequest(claim=claim(), cache_directory="case")
    )

    assert result.verification.verification_status is VerificationStatus.UNAVAILABLE
    assert result.failure is not None and result.failure.code == "all_cache_failed"
    assert result.verification.network_request_count == result.verification.model_call_count == 0
