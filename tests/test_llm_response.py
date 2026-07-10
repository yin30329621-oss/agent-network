from types import SimpleNamespace

from agent_network.agents.base import parse_agent_review
from agent_network.llm import extract_response_text


def response(choice, usage=None):
    return SimpleNamespace(choices=[choice], usage=usage or SimpleNamespace())


def test_extract_content_normal() -> None:
    text, audit = extract_response_text(
        response(SimpleNamespace(finish_reason="stop", message={"content": "hello"}))
    )

    assert text == "hello"
    assert audit["extracted_field"] == "message.content"
    assert audit["content_length"] == 5


def test_extract_content_none() -> None:
    text, audit = extract_response_text(
        response(SimpleNamespace(finish_reason="stop", message={"content": None}))
    )

    assert text == ""
    assert audit["content_is_none"] is True
    assert audit["extracted_field"] == "empty_response"


def test_extract_content_empty_string() -> None:
    text, audit = extract_response_text(
        response(SimpleNamespace(finish_reason="stop", message={"content": ""}))
    )

    assert text == ""
    assert audit["content_is_none"] is False
    assert audit["content_length"] == 0


def test_extract_compatible_text_field() -> None:
    text, audit = extract_response_text(
        response(SimpleNamespace(finish_reason="stop", message={"content": ""}, text="from text"))
    )

    assert text == "from text"
    assert audit["extracted_field"] == "choices[0].text"


def test_extract_empty_choices() -> None:
    text, audit = extract_response_text(SimpleNamespace(choices=[], usage=SimpleNamespace()))

    assert text == ""
    assert audit["choices_count"] == 0
    assert audit["extracted_field"] == "empty_choices"


def test_finish_reason_length_and_usage_are_audited() -> None:
    text, audit = extract_response_text(
        response(
            SimpleNamespace(finish_reason="length", message={"content": ""}),
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )
    )

    assert text == ""
    assert audit["finish_reason"] == "length"
    assert audit["usage"]["completion_tokens"] == 20


def test_completion_tokens_with_empty_content_stays_parse_failed() -> None:
    _, audit = extract_response_text(
        response(
            SimpleNamespace(finish_reason="stop", message={"content": ""}),
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )
    )
    review = parse_agent_review(
        "security",
        "",
        provider="siliconflow",
        model="Qwen/Qwen3.6-35B-A3B",
        provider_response_audit=audit,
    )

    assert review.status == "parse_failed"
    assert not review.findings
    assert review.provider_response_audit["usage"]["completion_tokens"] == 20
