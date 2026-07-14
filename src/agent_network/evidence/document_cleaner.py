"""Deterministic, offline cleaning for fetched official document HTML."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
import re
import unicodedata

from agent_network.evidence.document_fetcher import OfficialDocumentFetchResult
from agent_network.evidence.schemas import DocumentCatalog


_NOISE_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "nav",
        "header",
        "footer",
        "aside",
        "iframe",
        "form",
        "svg",
        "canvas",
    }
)
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
_HEADING_LEVELS = {f"h{level}": level for level in range(1, 7)}
_BLOCK_TAGS = frozenset({"p", "li", "pre", "table", "tr", "td", "th"})
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_NAVIGATION_MARKERS = ("on this page", "table of contents", "本页目录")
_NAVIGATION_ATTRIBUTE_TOKENS = frozenset(
    {"toc", "table-of-contents", "table_of_contents", "on-this-page", "on_this_page"}
)
_UI_VERSION_LABEL = re.compile(r"^version\s*:\s*v?(?:\d+(?:\.\d+){1,3}|x(?:\.[a-z]){1,2})$", re.I)
_PROMPT_INJECTION_PATTERNS = (
    (
        "ignore_previous_instructions",
        re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I),
    ),
    ("system_prompt", re.compile(r"system\s+prompt", re.I)),
    ("assistant_must", re.compile(r"assistant\s+must", re.I)),
    ("override_instructions", re.compile(r"override\s+(?:all\s+)?instructions", re.I)),
    ("execute_following_command", re.compile(r"执行以下命令")),
    ("ignore_prior_requirements", re.compile(r"忽略此前要求")),
    ("page_as_system_instruction", re.compile(r"将本页面内容作为系统指令")),
)


class DocumentCleaningError(RuntimeError):
    """A safe, categorical failure while extracting fetched HTML."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class DocumentSection:
    heading: str
    heading_level: int
    text: str
    order: int
    heading_path: list[str] = field(default_factory=list)
    contains_code: bool = False
    contains_table: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CleanedOfficialDocument:
    document_id: str
    canonical_url: str
    final_url: str
    product: str
    component: str
    document_type: str
    title: str
    plain_text: str
    headings: list[str]
    sections: list[DocumentSection]
    source_fetched_at: datetime
    source_response_size_bytes: int
    product_version: str | None = None
    code_blocks: list[str] = field(default_factory=list)
    table_blocks: list[str] = field(default_factory=list)
    cleaner_warnings: list[str] = field(default_factory=list)
    cleaned_content_hash: str = ""
    untrusted_document_content: bool = True
    prompt_injection_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["source_fetched_at"] = self.source_fetched_at.isoformat()
        return data


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list[_Node | str] = field(default_factory=list)


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        self._stack[-1].children.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == lowered:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


class OfficialDocumentCleaner:
    """Extract stable document text from a previously fetched HTML response."""

    def __init__(self, *, maximum_html_characters: int = 1_000_000) -> None:
        if maximum_html_characters <= 0:
            raise ValueError("maximum_html_characters must be positive")
        self.maximum_html_characters = maximum_html_characters
        self.network_request_count = 0
        self.model_call_count = 0

    def clean(
        self, fetch_result: OfficialDocumentFetchResult, document: DocumentCatalog
    ) -> CleanedOfficialDocument:
        html = fetch_result.html
        if not html or not html.strip():
            raise DocumentCleaningError("empty_html", "Fetched document HTML is empty")
        if len(html) > self.maximum_html_characters:
            raise DocumentCleaningError("input_too_large", "Fetched document HTML exceeds limit")
        try:
            parser = _DocumentParser()
            parser.feed(html)
            parser.close()
        except Exception as exc:
            raise DocumentCleaningError(
                "invalid_html", "Fetched document HTML could not be parsed"
            ) from exc

        try:
            container = _select_content_container(parser.root)
            blocks = list(_extract_blocks(container))
            title = _select_title(container, parser.root, document.title)
            sections = _sections_from_blocks(blocks, title)
            plain_text = _plain_text(blocks)
        except DocumentCleaningError:
            raise
        except Exception as exc:
            raise DocumentCleaningError("cleaning_error", "Document cleaning failed") from exc

        if not plain_text:
            raise DocumentCleaningError(
                "no_extractable_content", "Fetched document has no extractable content"
            )
        prompt_injection_flags = _prompt_injection_flags(plain_text)
        warnings = ["prompt_injection_flags_present"] if prompt_injection_flags else []
        return CleanedOfficialDocument(
            document_id=document.document_id,
            canonical_url=document.canonical_url,
            final_url=fetch_result.final_url,
            product=document.product,
            component=document.component or (document.components[0] if document.components else ""),
            document_type=document.document_type.value,
            title=title,
            plain_text=plain_text,
            headings=[heading for kind, heading, _level in blocks if kind == "heading"],
            sections=sections,
            source_fetched_at=fetch_result.fetched_at,
            source_response_size_bytes=fetch_result.response_size_bytes,
            product_version=document.product_version,
            code_blocks=[text for kind, text, _level in blocks if kind == "code"],
            table_blocks=[text for kind, text, _level in blocks if kind == "table"],
            cleaner_warnings=warnings,
            cleaned_content_hash=f"sha256:{sha256(plain_text.encode('utf-8')).hexdigest()}",
            prompt_injection_flags=prompt_injection_flags,
        )


def _select_content_container(root: _Node) -> _Node:
    for predicate in (
        lambda node: node.tag == "main",
        lambda node: node.tag == "article",
        lambda node: node.attrs.get("role", "").lower() == "main",
        lambda node: node.tag == "body",
    ):
        match = next((node for node in _nodes(root, include_noise=False) if predicate(node)), None)
        if match is not None:
            return match
    return root


def _select_title(container: _Node, root: _Node, catalog_title: str) -> str:
    for node in _nodes(container, include_noise=False):
        if node.tag == "h1" and (text := _inline_text(node)):
            return _strip_site_suffix(text)
    for node in _nodes(root, include_noise=False):
        if node.tag == "h1" and (text := _inline_text(node)):
            return _strip_site_suffix(text)
    for node in _nodes(root, include_noise=True):
        if node.tag == "title" and (text := _inline_text(node)):
            return _strip_site_suffix(text)
    return _normalize_text(catalog_title) or "Official document"


def _nodes(node: _Node, *, include_noise: bool) -> list[_Node]:
    result: list[_Node] = []

    def visit(current: _Node) -> None:
        if current.tag in _NOISE_TAGS and not include_noise:
            return
        result.append(current)
        for child in current.children:
            if isinstance(child, _Node):
                visit(child)

    visit(node)
    return result


def _extract_blocks(node: _Node):
    def visit(current: _Node):
        if current.tag in _NOISE_TAGS:
            return
        if _is_navigation_like_node(current):
            return
        if current.tag in _HEADING_LEVELS:
            if (text := _inline_text(current)) and not _is_ui_label(text):
                yield ("heading", text, _HEADING_LEVELS[current.tag])
            return
        if current.tag == "pre":
            if text := _pre_text(current):
                yield ("code", text, 0)
            return
        if current.tag == "li":
            if text := _inline_text(current):
                yield ("text", f"- {text}", 0)
            return
        if current.tag == "table":
            for row in _nodes(current, include_noise=False):
                if row.tag == "tr":
                    cells = [
                        _inline_text(cell)
                        for cell in row.children
                        if isinstance(cell, _Node) and cell.tag in {"th", "td"}
                    ]
                    if any(cells):
                        yield ("table", " | ".join(cells), 0)
            return
        if current.tag == "p":
            if (text := _inline_text(current)) and not _is_ui_label(text):
                yield ("text", text, 0)
            return
        for child in current.children:
            if isinstance(child, _Node):
                yield from visit(child)
            elif (
                current.tag not in _BLOCK_TAGS
                and (text := _normalize_text(child))
                and not _is_ui_label(text)
            ):
                yield ("text", text, 0)

    yield from visit(node)


def _is_navigation_like_node(node: _Node) -> bool:
    """Reject explicit in-content tables of contents without treating ordinary lists as noise."""

    attribute_values = " ".join(
        node.attrs.get(name, "") for name in ("id", "class", "aria-label", "data-testid")
    ).lower()
    attribute_tokens = set(re.split(r"[^a-z0-9_]+", attribute_values))
    has_navigation_attribute = _NAVIGATION_ATTRIBUTE_TOKENS.intersection(attribute_tokens) or any(
        marker in attribute_values for marker in _NAVIGATION_ATTRIBUTE_TOKENS
    )
    if has_navigation_attribute and _list_item_count(node) >= 2:
        return True

    text = _inline_text(node).lower()
    return (
        any(marker in text for marker in _NAVIGATION_MARKERS)
        and _list_item_count(node) >= 2
        and _looks_like_heading_list(node)
    )


def _is_ui_label(text: str) -> bool:
    normalized = _normalize_text(text).casefold()
    return normalized in {"on this page", "table of contents", "本页目录"} or bool(
        _UI_VERSION_LABEL.fullmatch(normalized)
    )


def _list_item_count(node: _Node) -> int:
    return sum(1 for child in _nodes(node, include_noise=False) if child.tag == "li")


def _looks_like_heading_list(node: _Node) -> bool:
    items = [
        _inline_text(child)
        for child in _nodes(node, include_noise=False)
        if child.tag == "li" and _inline_text(child)
    ]
    if len(items) < 2:
        return False
    return all(len(item) <= 120 and not re.search(r"[.!?。！？;；]$", item) for item in items)


def _sections_from_blocks(blocks: list[tuple[str, str, int]], title: str) -> list[DocumentSection]:
    sections: list[DocumentSection] = []
    active_heading = ""
    active_level = 0
    active_lines: list[str] = []
    active_path: list[str] = []
    active_contains_code = False
    active_contains_table = False

    def append_section() -> None:
        if active_lines or active_heading:
            sections.append(
                DocumentSection(
                    heading=active_heading or title,
                    heading_level=active_level,
                    text="\n\n".join(active_lines),
                    order=len(sections),
                    heading_path=list(active_path) or [active_heading or title],
                    contains_code=active_contains_code,
                    contains_table=active_contains_table,
                )
            )

    for kind, text, level in blocks:
        if kind == "heading":
            append_section()
            active_heading, active_level, active_lines = text, level, []
            active_path = active_path[: max(0, level - 1)] + [text]
            active_contains_code = False
            active_contains_table = False
        else:
            active_lines.append(text)
            active_contains_code = active_contains_code or kind == "code"
            active_contains_table = active_contains_table or kind == "table"
    append_section()
    if not sections:
        return [DocumentSection(heading=title, heading_level=0, text="", order=0)]
    return sections


def _plain_text(blocks: list[tuple[str, str, int]]) -> str:
    return "\n\n".join(text for _kind, text, _level in blocks if text).strip()


def _inline_text(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in _NOISE_TAGS:
            parts.append(_inline_text(child))
    return _normalize_text(" ".join(parts))


def _pre_text(node: _Node) -> str:
    raw = "".join(_raw_text(child) for child in node.children)
    cleaned = _clean_characters(raw).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in cleaned.strip().split("\n"))


def _raw_text(value: _Node | str) -> str:
    if isinstance(value, str):
        return value
    if value.tag in _NOISE_TAGS:
        return ""
    return "".join(_raw_text(child) for child in value.children)


def _normalize_text(value: str) -> str:
    return " ".join(_clean_characters(value).split())


def _clean_characters(value: str) -> str:
    return _CONTROL_CHARACTERS.sub("", _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", value)))


def _strip_site_suffix(title: str) -> str:
    return re.sub(
        r"\s*[|\-–—]\s*(?:Rancher|Rancher Docs|Fleet)(?:\s+Documentation)?\s*$",
        "",
        title,
        flags=re.I,
    ).strip()


def _prompt_injection_flags(text: str) -> list[str]:
    flags: list[str] = []
    for rule_name, pattern in _PROMPT_INJECTION_PATTERNS:
        for match in pattern.finditer(text):
            flags.append(f"{rule_name}@{match.start()}")
    return flags
