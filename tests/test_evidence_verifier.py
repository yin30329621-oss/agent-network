import pytest

from agent_network.evidence.schemas import VerificationStatus
from agent_network.evidence.sources import EvidenceFixture, FakeEvidenceSource
from agent_network.evidence.verifier import OfflineEvidenceVerifier


FIXTURE_PATH = "benchmarks/fixtures/evidence-v1"


@pytest.fixture
def verified_dataset():
    dataset = EvidenceFixture.load(FIXTURE_PATH)
    verifier = OfflineEvidenceVerifier(FakeEvidenceSource(dataset.evidence))
    results = {claim.claim_id: verifier.verify(claim) for claim in dataset.claims}
    return dataset, verifier, results


@pytest.mark.parametrize(
    ("claim_id", "expected"),
    [
        ("claim-cluster-agent-connect", VerificationStatus.VERIFIED),
        ("claim-websocket-polling", VerificationStatus.CONTRADICTED),
        ("claim-reverse-tunnel-role", VerificationStatus.PARTIALLY_VERIFIED),
        ("claim-registration-token-lifecycle", VerificationStatus.NOT_VERIFIED),
        ("claim-serviceaccount-token", VerificationStatus.CONFLICTING_SOURCES),
        ("claim-rbac-version", VerificationStatus.VERSION_MISMATCH),
        ("claim-cloud-credential-storage", VerificationStatus.INSUFFICIENT_EVIDENCE),
        ("claim-subjective-recommendation", VerificationStatus.NOT_APPLICABLE),
    ],
)
def test_deterministic_status_rules(verified_dataset, claim_id, expected) -> None:
    _, _, results = verified_dataset
    assert results[claim_id].verification_status == expected


def test_not_verified_is_never_reported_as_contradicted(verified_dataset) -> None:
    _, _, results = verified_dataset
    result = results["claim-registration-token-lifecycle"]
    assert result.verification_status == VerificationStatus.NOT_VERIFIED
    assert result.contradicting_evidence_ids == []
    assert "未验证不等于错误" in result.explanation


def test_low_relevance_evidence_does_not_verify_claim(verified_dataset) -> None:
    _, _, results = verified_dataset
    result = results["claim-cloud-credential-storage"]
    assert result.verification_status == VerificationStatus.INSUFFICIENT_EVIDENCE
    assert result.supporting_evidence_ids == []


def test_fake_source_is_deterministic_and_never_uses_network(verified_dataset) -> None:
    dataset, _, _ = verified_dataset
    source = FakeEvidenceSource(dataset.evidence)
    claim = next(item for item in dataset.claims if item.claim_id == "claim-fleet-bundle")

    first = source.search(claim)
    second = source.search(claim)

    assert [item.evidence_id for item in first] == [item.evidence_id for item in second]
    assert first[0].evidence_id == "evidence-fleet-bundle"
    assert source.network_request_count == 0


def test_full_fixture_report_has_zero_model_and_network_calls() -> None:
    dataset = EvidenceFixture.load(FIXTURE_PATH)
    source = FakeEvidenceSource(dataset.evidence)
    verifier = OfflineEvidenceVerifier(source)

    report = verifier.verify_all(
        dataset.claims,
        fixture_id=dataset.fixture_id,
        fixture_notice=dataset.fixture_notice,
    )

    assert report.claim_count == 11
    assert report.metadata["model_call_count"] == 0
    assert report.metadata["network_request_count"] == 0
    assert report.status_counts == {
        "verified": 3,
        "contradicted": 2,
        "partially_verified": 1,
        "not_verified": 1,
        "conflicting_sources": 1,
        "version_mismatch": 1,
        "insufficient_evidence": 1,
        "not_applicable": 1,
    }
