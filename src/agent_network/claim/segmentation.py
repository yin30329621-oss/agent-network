"""Small deterministic Markdown structural segmenter."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class DocumentSegment:
    kind: str
    text: str
    start_line: int
    end_line: int
    order: int
    heading_level: int | None = None
    heading_path: tuple[str, ...] = ()


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+(.+?)\s*$")
_FENCE = re.compile(r"^\s*(```+|~~~+)")


def segment_markdown(document_text: str) -> list[DocumentSegment]:
    lines = document_text.splitlines()
    segments: list[DocumentSegment] = []
    heading_stack: list[tuple[int, str]] = []
    paragraph: list[tuple[int, str]] = []
    in_fence = False
    order = 0

    def current_path() -> tuple[str, ...]:
        return tuple(item[1] for item in heading_stack)

    def flush_paragraph() -> None:
        nonlocal order
        if not paragraph:
            return
        start = paragraph[0][0]
        end = paragraph[-1][0]
        text = "\n".join(item[1] for item in paragraph).strip()
        if text:
            segments.append(
                DocumentSegment("paragraph", text, start, end, order, None, current_path())
            )
            order += 1
        paragraph.clear()

    for line_number, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            flush_paragraph()
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            segments.append(
                DocumentSegment(
                    "heading", title, line_number, line_number, order, level, current_path()
                )
            )
            order += 1
            continue

        list_item = _LIST.match(line)
        if list_item:
            flush_paragraph()
            segments.append(
                DocumentSegment(
                    "list_item",
                    list_item.group(1),
                    line_number,
                    line_number,
                    order,
                    None,
                    current_path(),
                )
            )
            order += 1
            continue

        if line.lstrip().startswith(">"):
            flush_paragraph()
            quoted = line.lstrip()[1:].strip()
            if quoted:
                segments.append(
                    DocumentSegment(
                        "quote", quoted, line_number, line_number, order, None, current_path()
                    )
                )
                order += 1
            continue

        if "|" in line and line.strip().startswith("|"):
            flush_paragraph()
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and not all(set(cell) <= {"-", ":", " "} for cell in cells):
                segments.append(
                    DocumentSegment(
                        "table_row",
                        " | ".join(cells),
                        line_number,
                        line_number,
                        order,
                        None,
                        current_path(),
                    )
                )
                order += 1
            continue

        if line.strip():
            paragraph.append((line_number, line))
        else:
            flush_paragraph()

    flush_paragraph()
    return segments
