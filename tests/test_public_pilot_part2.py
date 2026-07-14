import importlib.util
from pathlib import Path


_SPEC = importlib.util.spec_from_file_location(
    "public_pilot_part2", Path("benchmarks/public_pilot_part2.py")
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
audit_part1_disagreements = _MODULE.audit_part1_disagreements


PART1 = Path("artifacts/public-pilot/part1")


def test_part2_audit_is_offline_and_classifies_all_disagreements() -> None:
    report = audit_part1_disagreements(PART1)

    assert report["model_call_count"] == 0
    assert report["network_request_count"] == 0
    assert [item["claim_id"] for item in report["audits"]] == [
        "cluster-tunnel",
        "cluster-absolute",
        "cluster-v213",
    ]
    assert report["audits"][0]["disagreement_type"] == "evidence_interpretation"
    assert report["audits"][0]["recommended_status"] == "manual_review"
    assert report["audits"][1]["disagreement_type"] == "insufficient_evidence_threshold"
    assert report["audits"][1]["recommended_status"] == "insufficient_evidence"
    assert report["audits"][2]["disagreement_type"] == "status_mapping"
    assert report["audits"][2]["recommended_status"] == "insufficient_evidence"


def test_part2_audit_preserves_citation_identity_and_same_evidence() -> None:
    report = audit_part1_disagreements(PART1)

    assert all(item["same_evidence"] for item in report["audits"])
    assert all(
        item["fact_a"]["cited_chunk_ids"] == item["fact_b"]["cited_chunk_ids"]
        for item in report["audits"]
    )
    assert report["local_rule_resolved_count"] == 2
    assert report["manual_review_count"] == 1
