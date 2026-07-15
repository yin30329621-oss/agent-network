import json

import pytest

from agent_network.claim import Claim, ClaimType
from agent_network.claim.evidence_decision import EvidenceDecisionEngine
from agent_network.claim.fact_model_adapter import (
    FactModelAdapter,
    fact_a_adapter_config,
    fact_b_adapter_config,
)
from agent_network.config import load_config
from agent_network.claim.fact_review import (
    DualFactReviewCoordinator,
    DualReviewBudget,
    ReconciliationStatus,
)
from agent_network.evidence.offline_retrieval import RetrievalResult, SelectedEvidence


class RecordingMockProvider:
    def __init__(self, *, fail: bool = False, invalid_citation: bool = False) -> None:
        self.fail = fail
        self.invalid_citation = invalid_citation
        self.calls: list[dict[str, object]] = []
        self.last_response_audit: dict[str, object] = {"provider_success": True}

    def complete(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("mock provider failure")
        inputs = json.loads(str(kwargs["user_prompt"]))["review_inputs"]
        reviews = [
            {
                "decision": "verified_candidate",
                "recommended_status": "verified_candidate",
                "cited_chunk_ids": ["unknown"] if self.invalid_citation else ["chunk-1"],
                "reasoning_summary": "fixture",
                "limitations": [],
                "canonical_url": "https://model.invalid/not-allowed",
            }
            for _ in inputs
        ]
        return json.dumps({"reviews": reviews})


def _input():
    claim = Claim(claim_id="c1", text="Cluster Agent connects", claim_type=ClaimType.ARCHITECTURE)
    evidence = SelectedEvidence(
        "chunk-1",
        "doc-1",
        "https://ranchermanager.docs.rancher.com/doc",
        ["Cluster Agent"],
        "Cluster Agent connects",
        1.0,
        1.0,
        ["cluster", "agent"],
        True,
        True,
        True,
        "reference",
        100,
        "fixture",
        [],
    )
    retrieval = RetrievalResult("c1", ["cluster", "agent"], 1, 1, 1, 3, [evidence])
    return EvidenceDecisionEngine().decide_batch([(claim, retrieval)]).review_inputs[0]


def _fact_adapters():
    config = load_config("configs/default.yaml")
    return (
        config,
        config.dual_fact_reviewer_config("fact_a"),
        config.dual_fact_reviewer_config("fact_b"),
    )


def test_fact_a_and_b_are_isolated_but_receive_identical_payloads() -> None:
    a_provider, b_provider = RecordingMockProvider(), RecordingMockProvider()
    config = load_config("configs/default.yaml")
    from agent_network.claim.fact_model_adapter import fact_a_adapter_config, fact_b_adapter_config

    fact_a = FactModelAdapter.fact_a(a_provider, fact_a_adapter_config(config))
    fact_b = FactModelAdapter.fact_b(b_provider, fact_b_adapter_config(config))

    result = DualFactReviewCoordinator(fact_a, fact_b).review_batch([_input()])

    assert a_provider.calls[0]["user_prompt"] == b_provider.calls[0]["user_prompt"]
    assert a_provider.calls[0]["system_prompt"] != b_provider.calls[0]["system_prompt"]
    assert "fact-b" not in str(a_provider.calls[0]["user_prompt"])
    assert "fact-a" not in str(b_provider.calls[0]["user_prompt"])
    assert result[0].status == ReconciliationStatus.CONSENSUS
    assert result[0].fact_a and "model_url_ignored" in result[0].fact_a.audit_warnings


def test_adapter_failure_and_invalid_citation_are_fail_soft_and_audited() -> None:
    from agent_network.claim.fact_model_adapter import fact_a_adapter_config, fact_b_adapter_config

    config = load_config("configs/default.yaml")
    successful = FactModelAdapter.fact_b(RecordingMockProvider(), fact_b_adapter_config(config))
    failed = FactModelAdapter.fact_a(
        RecordingMockProvider(fail=True), fact_a_adapter_config(config)
    )
    single = DualFactReviewCoordinator(failed, successful).review_batch([_input()])[0]
    invalid = DualFactReviewCoordinator(
        FactModelAdapter.fact_a(
            RecordingMockProvider(invalid_citation=True), fact_a_adapter_config(config)
        ),
        successful,
    ).review_batch([_input()])[0]
    both_failed = DualFactReviewCoordinator(
        FactModelAdapter.fact_a(RecordingMockProvider(fail=True), fact_a_adapter_config(config)),
        FactModelAdapter.fact_b(RecordingMockProvider(fail=True), fact_b_adapter_config(config)),
    ).review_batch([_input()])[0]

    assert single.status == ReconciliationStatus.SINGLE_REVIEWER_AVAILABLE
    assert invalid.status == ReconciliationStatus.INVALID_CITATION
    assert invalid.fact_a and invalid.fact_a.cited_chunk_ids == []
    assert both_failed.status == ReconciliationStatus.MANUAL_REVIEW_REQUIRED


def test_batch_calls_and_budget_are_deterministic_with_mock_provider() -> None:
    a_provider, b_provider = RecordingMockProvider(), RecordingMockProvider()
    from agent_network.claim.fact_model_adapter import fact_a_adapter_config, fact_b_adapter_config

    config = load_config("configs/default.yaml")
    coordinator = DualFactReviewCoordinator(
        FactModelAdapter.fact_a(a_provider, fact_a_adapter_config(config)),
        FactModelAdapter.fact_b(b_provider, fact_b_adapter_config(config)),
        DualReviewBudget(claims_per_batch=1, max_batches=2, max_output_tokens_per_call=10),
    )
    inputs = [_input(), _input()]
    estimate = coordinator.estimate(inputs)
    result = coordinator.review_batch(inputs)

    assert estimate.estimated_fact_a_calls == estimate.estimated_fact_b_calls == 2
    assert estimate.estimated_total_calls == 4
    assert estimate.estimated_tokens > 0 and not estimate.budget_exceeded
    assert len(a_provider.calls) == len(b_provider.calls) == 2
    assert len(result) == 2
    assert coordinator.network_request_count == coordinator.model_call_count == 0


def test_limitations_normalize_string_null_and_list_without_character_splitting() -> None:
    provider = RecordingMockProvider()
    from agent_network.claim.fact_model_adapter import fact_a_adapter_config

    adapter = FactModelAdapter.fact_a(
        provider, fact_a_adapter_config(load_config("configs/default.yaml"))
    )
    input_value = _input().to_dict()

    def response(value: object) -> str:
        return json.dumps(
            {
                "reviews": [
                    {
                        "decision": "candidate_only",
                        "recommended_status": "candidate_only",
                        "cited_chunk_ids": [],
                        "reasoning_summary": "compact",
                        "limitations": value,
                    }
                ]
            }
        )

    provider.complete = lambda **_: response("single limitation")
    assert adapter.review_batch([input_value])[0].limitations == ["single limitation"]
    provider.complete = lambda **_: response(None)
    assert adapter.review_batch([input_value])[0].limitations == []
    provider.complete = lambda **_: response(["one", 2, "two"])
    assert adapter.review_batch([input_value])[0].limitations == ["one", "two"]


def _valid_fact_response() -> str:
    return json.dumps(
        {
            "reviews": [
                {
                    "claim_id": "c1",
                    "decision": "verified_candidate",
                    "recommended_status": "verified_candidate",
                    "cited_chunk_ids": ["chunk-1"],
                    "reasoning_summary": "fixture",
                    "limitations": [],
                }
            ]
        }
    )


@pytest.mark.parametrize(
    "response",
    [
        (chr(96) * 3 + "json\n" + _valid_fact_response() + "\n" + chr(96) * 3),
        ("Here is the JSON response:\n" + _valid_fact_response() + "\nDone."),
    ],
)
def test_parser_extracts_one_json_object_from_wrapped_response(response: str) -> None:
    provider = RecordingMockProvider()
    provider.complete = lambda **_: response
    adapter = FactModelAdapter.fact_a(
        provider,
        fact_a_adapter_config(load_config("configs/default.yaml")),
    )

    result = adapter.review_batch([_input().to_dict()])[0]

    assert result.parse_status == "parsed"
    assert result.response_metadata["content_length"] == len(response)
    assert result.response_metadata["starts_with_json"] is False


@pytest.mark.parametrize(
    "response",
    [
        ("{invalid json}"),
        (_valid_fact_response() + _valid_fact_response()),
    ],
)
def test_parser_rejects_invalid_or_multiple_json_objects(response: str) -> None:
    provider = RecordingMockProvider()
    provider.complete = lambda **_: response
    adapter = FactModelAdapter.fact_a(
        provider,
        fact_a_adapter_config(load_config("configs/default.yaml")),
    )

    result = adapter.review_batch([_input().to_dict()])[0]

    assert result.parse_status == "parse_failed"
    assert result.response_metadata["content_length"] == len(response)
    assert result.response_metadata["json_extraction_error"] in {
        "json_object_not_found",
        "multiple_json_objects",
    }


def test_fact_b_prompt_is_compact_and_budget_is_bounded() -> None:
    provider = RecordingMockProvider()
    from agent_network.claim.fact_model_adapter import fact_b_adapter_config

    adapter = FactModelAdapter.fact_b(
        provider, fact_b_adapter_config(load_config("configs/default.yaml"))
    )
    result = adapter.review_batch([_input().to_dict()])

    assert result[0].audit_status.value == "completed"
    assert "Do not restate the Evidence" in adapter.system_prompt
    assert adapter.config.max_tokens == 2200


def test_official_fact_reviewers_are_configured_independently() -> None:
    config = load_config("configs/default.yaml")
    from agent_network.claim.fact_model_adapter import (
        fact_a_adapter_config,
        fact_b_adapter_config,
        fact_model_adapter_from_config,
    )

    fact_a = fact_a_adapter_config(config)
    fact_b = fact_b_adapter_config(config)

    assert (fact_a.provider, fact_b.provider) == ("deepseek_official", "dashscope_official")
    assert fact_a.model == "deepseek-v4-pro"
    assert fact_b.model == "qwen3.7-plus"
    assert fact_a.max_tokens == 4000
    assert fact_b.max_tokens == 2200
    assert fact_a.provider != fact_b.provider

    adapter_a = fact_model_adapter_from_config(config, "fact_a")
    adapter_b = fact_model_adapter_from_config(config, "fact_b")

    assert adapter_a.llm is not adapter_b.llm
    assert adapter_a.llm.model_options[adapter_a.config.model]["provider"] == "deepseek_official"
    assert adapter_b.llm.model_options[adapter_b.config.model]["provider"] == "dashscope_official"
    assert adapter_a.llm.retry_attempts == adapter_b.llm.retry_attempts == 0


@pytest.mark.parametrize("value", [True, False])
def test_dashscope_enable_thinking_is_forwarded_as_extra_body(value: bool) -> None:
    config = load_config("configs/default.yaml")
    config.raw["fact_review"]["reviewers"]["fact_b"]["request_options"] = {"enable_thinking": value}
    provider = RecordingMockProvider()
    adapter = FactModelAdapter.fact_b(
        provider,
        fact_b_adapter_config(config),
    )

    adapter.review_batch([_input().to_dict()])

    assert provider.calls[0]["extra_body"] == {"enable_thinking": value}


def test_dashscope_null_or_missing_thinking_option_keeps_provider_default() -> None:
    for request_options in ({"enable_thinking": None}, {}):
        config = load_config("configs/default.yaml")
        config.raw["fact_review"]["reviewers"]["fact_b"]["request_options"] = request_options
        provider = RecordingMockProvider()
        adapter = FactModelAdapter.fact_b(provider, fact_b_adapter_config(config))

        adapter.review_batch([_input().to_dict()])

        assert "extra_body" not in provider.calls[0]


def test_non_dashscope_provider_never_forwards_request_options() -> None:
    config = load_config("configs/default.yaml")
    config.raw["fact_review"]["reviewers"]["fact_a"]["request_options"] = {"enable_thinking": True}
    provider = RecordingMockProvider()
    adapter = FactModelAdapter.fact_a(provider, fact_a_adapter_config(config))

    adapter.review_batch([_input().to_dict()])

    assert "extra_body" not in provider.calls[0]


def test_fact_a_uses_confirmed_json_response_format() -> None:
    config = load_config("configs/default.yaml")
    provider = RecordingMockProvider()
    adapter = FactModelAdapter.fact_a(provider, fact_a_adapter_config(config))

    adapter.review_batch([_input().to_dict()])

    assert provider.calls[0]["response_format"] == {"type": "json_object"}
    assert "extra_body" not in provider.calls[0]
    assert "chain-of-thought" in adapter.system_prompt
    assert "reasoning_summary" in adapter.system_prompt
