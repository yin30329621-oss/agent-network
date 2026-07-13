from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_network.evidence.document_cleaner import (
    DocumentCleaningError,
    OfficialDocumentCleaner,
)
from agent_network.evidence.document_fetcher import OfficialDocumentFetchResult
from agent_network.evidence.schemas import DocumentCatalog


FIXTURES = Path("benchmarks/fixtures/document-cleaner-v1")
FETCHED_AT = datetime(2026, 7, 13, tzinfo=UTC)


def document() -> DocumentCatalog:
    return DocumentCatalog(
        document_id="cleaner-fixture",
        source_name="rancher",
        title="Catalog fallback",
        canonical_url="https://ranchermanager.docs.rancher.com/fixture",
        official_domain="ranchermanager.docs.rancher.com",
        document_type="reference",
        product="Rancher Manager",
        components=["Cluster Agent"],
    )


def fetched(name: str) -> OfficialDocumentFetchResult:
    html = (FIXTURES / name).read_text(encoding="utf-8")
    return OfficialDocumentFetchResult(
        requested_url="https://ranchermanager.docs.rancher.com/fixture",
        final_url="https://ranchermanager.docs.rancher.com/fixture",
        status_code=200,
        content_type="text/html",
        html=html,
        fetched_at=FETCHED_AT,
        response_size_bytes=len(html.encode()),
        redirect_count=0,
    )


def test_main_is_preferred_and_noise_is_removed() -> None:
    cleaner = OfficialDocumentCleaner()

    result = cleaner.clean(fetched("main-page.html"), document())

    assert result.title == "Cluster Agent & Access"
    assert result.headings == ["Cluster Agent & Access - Rancher", "Setup", "Details"]
    assert "Navigation title" not in result.plain_text
    assert "Menu entry" not in result.plain_text
    assert "Sidebar" not in result.plain_text
    assert "alert" not in result.plain_text
    assert result.sections[1].heading == "Setup"
    assert result.sections[1].heading_level == 2
    assert "- Check status" in result.sections[1].text
    assert cleaner.network_request_count == 0
    assert cleaner.model_call_count == 0


@pytest.mark.parametrize(
    ("fixture", "title", "body"),
    [
        ("article-page.html", "Article Guide", "Article body."),
        ("role-main-page.html", "Role Main", "Role content."),
        ("body-page.html", "Catalog fallback", "Body fallback content."),
    ],
)
def test_container_fallbacks_are_deterministic(fixture: str, title: str, body: str) -> None:
    result = OfficialDocumentCleaner().clean(fetched(fixture), document())

    assert result.title == title
    assert body in result.plain_text


def test_sections_lists_code_and_normalization_are_preserved() -> None:
    result = OfficialDocumentCleaner().clean(fetched("main-page.html"), document())

    assert "First paragraph with spaces." in result.plain_text
    assert "- Install chart\n\n- Check status" in result.plain_text
    assert "kubectl get pods\n  --namespace cattle-system" in result.plain_text
    assert [section.order for section in result.sections] == [0, 1, 2]
    assert result.to_dict()["source_fetched_at"] == FETCHED_AT.isoformat()


def test_repeated_headings_and_fallback_section_are_kept() -> None:
    body_result = OfficialDocumentCleaner().clean(fetched("body-page.html"), document())
    article_result = OfficialDocumentCleaner().clean(fetched("article-page.html"), document())

    assert body_result.headings == ["Repeated", "Repeated"]
    assert [section.heading for section in body_result.sections] == [
        "Catalog fallback",
        "Repeated",
        "Repeated",
    ]
    assert article_result.sections[0].heading == "Article Guide"
    assert article_result.sections[0].heading_level == 0


def test_cleaning_is_deterministic_and_does_not_change_counts() -> None:
    cleaner = OfficialDocumentCleaner()
    first = cleaner.clean(fetched("main-page.html"), document())
    second = cleaner.clean(fetched("main-page.html"), document())

    assert first.to_dict() == second.to_dict()
    assert cleaner.network_request_count == 0
    assert cleaner.model_call_count == 0


@pytest.mark.parametrize(
    ("html", "code"),
    [
        ("", "empty_html"),
        ("<html><body><nav>menu</nav></body></html>", "no_extractable_content"),
    ],
)
def test_empty_or_unextractable_html_is_rejected(html: str, code: str) -> None:
    result = fetched("empty-page.html")
    result.html = html

    with pytest.raises(DocumentCleaningError) as error:
        OfficialDocumentCleaner().clean(result, document())

    assert error.value.code == code


def test_oversized_html_is_rejected_before_parsing() -> None:
    result = fetched("main-page.html")

    with pytest.raises(DocumentCleaningError, match="exceeds limit") as error:
        OfficialDocumentCleaner(maximum_html_characters=5).clean(result, document())

    assert error.value.code == "input_too_large"
