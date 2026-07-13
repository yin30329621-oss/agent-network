import json

from agent_network.evidence.reporting import to_json, to_markdown, write_report
from agent_network.evidence.sources import EvidenceFixture, FakeEvidenceSource
from agent_network.evidence.verifier import OfflineEvidenceVerifier


def fixture_report():
    dataset = EvidenceFixture.load("benchmarks/fixtures/evidence-v1")
    return OfflineEvidenceVerifier(FakeEvidenceSource(dataset.evidence)).verify_all(
        dataset.claims,
        fixture_id=dataset.fixture_id,
        fixture_notice=dataset.fixture_notice,
    )


def test_json_output_contains_required_sections() -> None:
    payload = json.loads(to_json(fixture_report()))

    assert set(payload) == {
        "metadata",
        "claim_count",
        "evidence_count",
        "status_counts",
        "claims",
        "evidence",
        "verification_results",
        "execution_notes",
    }
    assert payload["metadata"]["model_call_count"] == 0
    assert payload["evidence"][0]["excerpt"].startswith("FIXTURE ONLY")
    assert payload["evidence"][0]["excerpt_hash"].startswith("sha256:")


def test_markdown_output_is_explicitly_fixture_only() -> None:
    markdown = to_markdown(fixture_report())

    assert markdown.startswith("# 离线证据核验报告")
    assert "本次使用离线 fixture，并非真实官方核验结果" in markdown
    assert "## 状态统计" in markdown
    assert "证据片段" in markdown
    assert "未核验" in markdown
    assert "未验证不等于错误" in markdown


def test_write_report_creates_json_markdown_and_run_audit(tmp_path) -> None:
    paths = write_report(
        fixture_report(),
        tmp_path,
        output_format="both",
        fixture_path="benchmarks/fixtures/evidence-v1",
    )

    assert paths["json"].exists()
    assert paths["markdown"].exists()
    run = json.loads(paths["run"].read_text(encoding="utf-8"))
    assert run["mode"] == "offline_fixture"
    assert run["model_call_count"] == 0
    assert run["network_request_count"] == 0
