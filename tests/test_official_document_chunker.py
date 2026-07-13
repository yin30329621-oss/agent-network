from datetime import UTC, datetime

import pytest

from agent_network.evidence.document_chunker import (
    DocumentChunkingConfig,
    DocumentChunkingError,
    OfficialDocumentChunker,
)
from agent_network.evidence.document_cleaner import CleanedOfficialDocument, DocumentSection


FETCHED_AT = datetime(2026, 7, 13, tzinfo=UTC)


def cleaned_document(
    sections: list[DocumentSection], *, plain_text: str | None = None
) -> CleanedOfficialDocument:
    return CleanedOfficialDocument(
        document_id="chunk-fixture",
        canonical_url="https://ranchermanager.docs.rancher.com/fixture",
        final_url="https://ranchermanager.docs.rancher.com/fixture",
        product="Rancher Manager",
        component="Cluster Agent",
        document_type="reference",
        title="Chunk fixture",
        plain_text=plain_text if plain_text is not None else "\n\n".join(s.text for s in sections),
        headings=[section.heading for section in sections],
        sections=sections,
        source_fetched_at=FETCHED_AT,
        source_response_size_bytes=100,
    )


def section(text: str, *, heading: str = "Overview", order: int = 0) -> DocumentSection:
    return DocumentSection(heading=heading, heading_level=2, text=text, order=order)


def test_default_configuration_is_sized_for_technical_documents() -> None:
    config = DocumentChunkingConfig()

    assert config.max_characters == 1200
    assert config.overlap_characters == 0
    assert config.min_chunk_characters == 200


def test_short_section_creates_one_serializable_chunk() -> None:
    chunks = OfficialDocumentChunker().chunk(cleaned_document([section("Short section.")]))

    assert len(chunks) == 1
    assert chunks[0].text == "Short section."
    assert chunks[0].chunk_order == 0
    assert chunks[0].section_order == 0
    assert chunks[0].character_count == len(chunks[0].text)
    assert chunks[0].to_dict()["source_fetched_at"] == FETCHED_AT.isoformat()


def test_sections_are_never_merged() -> None:
    document = cleaned_document(
        [section("First section.", order=0), section("Second section.", heading="Setup", order=1)]
    )

    chunks = OfficialDocumentChunker().chunk(document)

    assert [chunk.section_heading for chunk in chunks] == ["Overview", "Setup"]
    assert [chunk.text for chunk in chunks] == ["First section.", "Second section."]


def test_boundaries_prefer_paragraph_then_sentence_then_space_and_hard_cut() -> None:
    config = DocumentChunkingConfig(max_characters=24, min_chunk_characters=0)
    paragraph = OfficialDocumentChunker(config).chunk(
        cleaned_document([section("First paragraph.\n\nSecond paragraph is longer.")])
    )
    sentence = OfficialDocumentChunker(config).chunk(
        cleaned_document([section("One sentence ends. Another sentence is long.")])
    )
    words = OfficialDocumentChunker(config).chunk(
        cleaned_document([section("alpha beta gamma delta epsilon zeta")])
    )
    hard = OfficialDocumentChunker(config).chunk(cleaned_document([section("x" * 50)]))

    assert paragraph[0].text == "First paragraph."
    assert sentence[0].text == "One sentence ends."
    assert words[0].text.endswith("delta")
    assert all(chunk.character_count <= 24 for chunk in hard)
    assert "".join(chunk.text for chunk in hard) == "x" * 50


def test_chinese_punctuation_and_code_text_are_preserved() -> None:
    config = DocumentChunkingConfig(max_characters=14, min_chunk_characters=0)
    source = "第一句结束。第二句继续！第三句。\n\nkubectl get pods\n  --namespace cattle-system"

    chunks = OfficialDocumentChunker(config).chunk(cleaned_document([section(source)]))

    assert any(chunk.text.endswith("。") or chunk.text.endswith("！") for chunk in chunks[:-1])
    assert "kubectl" in "".join(chunk.text for chunk in chunks)
    assert "--namespace" in "".join(chunk.text for chunk in chunks)


def test_last_short_chunk_is_retained_when_merging_would_exceed_limit() -> None:
    config = DocumentChunkingConfig(max_characters=15, min_chunk_characters=10)
    chunks = OfficialDocumentChunker(config).chunk(cleaned_document([section("1234567890 12345")]))

    assert [chunk.text for chunk in chunks] == ["1234567890", "12345"]


def test_overlap_is_deterministic_and_bounded_to_section() -> None:
    config = DocumentChunkingConfig(max_characters=20, overlap_characters=5, min_chunk_characters=0)
    chunks = OfficialDocumentChunker(config).chunk(
        cleaned_document([section("alpha beta gamma delta epsilon zeta eta theta")])
    )

    assert len(chunks) > 1
    assert all(chunk.character_count <= 20 for chunk in chunks)
    assert all(chunk.section_order == 0 for chunk in chunks)
    assert chunks == OfficialDocumentChunker(config).chunk(
        cleaned_document([section("alpha beta gamma delta epsilon zeta eta theta")])
    )


def test_ids_and_order_are_stable_and_unique() -> None:
    config = DocumentChunkingConfig(max_characters=12, min_chunk_characters=0)
    document = cleaned_document([section("one two three four five six seven")])
    first = OfficialDocumentChunker(config).chunk(document)
    second = OfficialDocumentChunker(config).chunk(document)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert len({chunk.chunk_id for chunk in first}) == len(first)
    assert [chunk.chunk_order for chunk in first] == list(range(len(first)))


def test_plain_text_is_used_when_sections_are_missing() -> None:
    chunks = OfficialDocumentChunker().chunk(cleaned_document([], plain_text="Fallback body text."))

    assert chunks[0].section_heading == "Chunk fixture"
    assert chunks[0].section_heading_level == 0
    assert chunks[0].text == "Fallback body text."


@pytest.mark.parametrize(
    "config",
    [
        {"max_characters": 0},
        {"max_characters": 10, "overlap_characters": 10},
        {"max_characters": 10, "overlap_characters": -1},
        {"max_characters": 10, "min_chunk_characters": 11},
    ],
)
def test_invalid_config_is_rejected(config: dict[str, int]) -> None:
    with pytest.raises(DocumentChunkingError) as error:
        DocumentChunkingConfig(**config)

    assert error.value.code == "invalid_config"


def test_empty_document_and_counts_are_safe() -> None:
    chunker = OfficialDocumentChunker()

    with pytest.raises(DocumentChunkingError) as error:
        chunker.chunk(cleaned_document([], plain_text=""))

    assert error.value.code == "empty_document"
    assert chunker.network_request_count == 0
    assert chunker.model_call_count == 0
