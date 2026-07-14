"""Deterministic, offline chunking for cleaned official documents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from hashlib import sha256
import re

from agent_network.evidence.document_cleaner import CleanedOfficialDocument, DocumentSection


_SENTENCE_BOUNDARY = re.compile(r"[.!?;。！？；](?:\s+|$)")


class DocumentChunkingError(RuntimeError):
    """A safe, categorical failure while chunking a cleaned document."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DocumentChunkingConfig:
    max_characters: int = 1200
    overlap_characters: int = 0
    min_chunk_characters: int = 200
    max_code_block_characters: int = 4000

    def __post_init__(self) -> None:
        if (
            self.max_characters <= 0
            or self.overlap_characters < 0
            or self.overlap_characters >= self.max_characters
            or self.min_chunk_characters < 0
            or self.min_chunk_characters > self.max_characters
            or self.max_code_block_characters < self.max_characters
        ):
            raise DocumentChunkingError(
                "invalid_config", "Document chunking configuration is invalid"
            )


@dataclass(slots=True)
class DocumentChunk:
    chunk_id: str
    document_id: str
    canonical_url: str
    final_url: str
    product: str
    component: str
    document_type: str
    document_title: str
    section_heading: str
    section_heading_level: int
    section_order: int
    chunk_order: int
    text: str
    character_count: int
    source_fetched_at: datetime
    heading_path: list[str] = field(default_factory=list)
    start_offset: int = 0
    end_offset: int = 0
    chunk_index: int = 0
    chunk_hash: str = ""
    token_estimate: int = 0
    product_version: str | None = None
    contains_code: bool = False
    contains_table: bool = False
    untrusted_document_content: bool = True
    prompt_injection_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.chunk_hash:
            self.chunk_hash = f"sha256:{sha256(self.text.encode('utf-8')).hexdigest()}"
        if not self.token_estimate:
            self.token_estimate = _token_estimate(self.text)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["source_fetched_at"] = self.source_fetched_at.isoformat()
        return data


class OfficialDocumentChunker:
    """Split cleaned text by section with deterministic local boundaries only."""

    def __init__(self, config: DocumentChunkingConfig | None = None) -> None:
        self.config = config or DocumentChunkingConfig()
        self.network_request_count = 0
        self.model_call_count = 0

    def chunk(self, document: CleanedOfficialDocument) -> list[DocumentChunk]:
        sections = _usable_sections(document)
        if not sections:
            if not document.plain_text.strip():
                raise DocumentChunkingError("empty_document", "Cleaned document has no text")
            sections = [
                DocumentSection(
                    heading=document.title,
                    heading_level=0,
                    text=document.plain_text,
                    order=0,
                )
            ]

        chunks: list[DocumentChunk] = []
        document_cursor = 0
        for section_index, section in enumerate(sections):
            text = section.text.strip()
            if not text:
                continue
            section_start = document.plain_text.find(text, document_cursor)
            if section_start < 0:
                section_start = document_cursor
            document_cursor = section_start + len(text)
            parts, warnings = _split_section_with_warnings(text, section, self.config)
            part_cursor = 0
            for part_index, part in enumerate(parts):
                chunk_order = len(chunks)
                local_start = text.find(part, part_cursor)
                if local_start < 0:
                    local_start = part_cursor
                part_cursor = max(
                    local_start + 1, local_start + len(part) - self.config.overlap_characters
                )
                start_offset = section_start + local_start
                end_offset = start_offset + len(part)
                chunks.append(
                    DocumentChunk(
                        chunk_id=_chunk_id(
                            document.document_id,
                            document.product_version,
                            section.order,
                            part_index,
                            part,
                        ),
                        document_id=document.document_id,
                        canonical_url=document.canonical_url,
                        final_url=document.final_url,
                        product=document.product,
                        component=document.component,
                        document_type=document.document_type,
                        document_title=document.title,
                        section_heading=section.heading,
                        section_heading_level=section.heading_level,
                        section_order=section.order if section.order >= 0 else section_index,
                        chunk_order=chunk_order,
                        text=part,
                        character_count=len(part),
                        source_fetched_at=document.source_fetched_at,
                        heading_path=list(section.heading_path) or [section.heading],
                        start_offset=start_offset,
                        end_offset=end_offset,
                        chunk_index=chunk_order,
                        product_version=document.product_version,
                        contains_code=section.contains_code,
                        contains_table=section.contains_table,
                        untrusted_document_content=document.untrusted_document_content,
                        prompt_injection_flags=_flags_for_range(
                            document.prompt_injection_flags, start_offset, end_offset
                        ),
                        warnings=list(warnings),
                    )
                )
        if not chunks:
            raise DocumentChunkingError(
                "no_chunkable_content", "Cleaned document has no chunkable content"
            )
        return chunks


def _usable_sections(document: CleanedOfficialDocument) -> list[DocumentSection]:
    return [section for section in document.sections if section.text.strip()]


def _split_section(text: str, config: DocumentChunkingConfig) -> list[str]:
    return _split_section_with_warnings(text, None, config)[0]


def _split_section_with_warnings(
    text: str, section: DocumentSection | None, config: DocumentChunkingConfig
) -> tuple[list[str], list[str]]:
    if (
        section is not None
        and section.contains_code
        and len(text) > config.max_characters
        and len(text) <= config.max_code_block_characters
    ):
        return [text], ["code_block_exceeds_max_chunk_chars"]
    parts: list[str] = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + config.max_characters, len(text))
        if end < len(text):
            end = _boundary_before(text, cursor, end)
        if end <= cursor:
            end = min(cursor + config.max_characters, len(text))
        part = text[cursor:end].strip()
        if part:
            parts.append(part)
        if end >= len(text):
            break
        cursor = _next_cursor(text, cursor, end, config.overlap_characters)

    if len(parts) > 1 and len(parts[-1]) < config.min_chunk_characters:
        merged = f"{parts[-2]}\n\n{parts[-1]}"
        if len(merged) <= config.max_characters:
            parts[-2:] = [merged]
    return parts, []


def _boundary_before(text: str, start: int, limit: int) -> int:
    for marker in ("\n\n", "\n"):
        boundary = text.rfind(marker, start + 1, limit + 1)
        if boundary > start:
            return boundary + len(marker)

    sentence_end = max(
        (match.end() for match in _SENTENCE_BOUNDARY.finditer(text, start, limit + 1)),
        default=0,
    )
    if sentence_end > start:
        return sentence_end

    boundary = text.rfind(" ", start + 1, limit + 1)
    if boundary > start:
        return boundary + 1
    return limit


def _next_cursor(text: str, start: int, end: int, overlap: int) -> int:
    if overlap == 0:
        return end
    candidate = max(start + 1, end - overlap)
    boundary = text.find(" ", candidate, end)
    return boundary + 1 if boundary >= candidate else candidate


def _chunk_id(
    document_id: str,
    product_version: str | None,
    section_order: int,
    chunk_order: int,
    text: str,
) -> str:
    digest = sha256(
        f"{document_id}\x1f{product_version or ''}\x1f{section_order}\x1f{chunk_order}\x1f{text}".encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    return f"{document_id}:{section_order}:{chunk_order}:{digest}"


def _token_estimate(text: str) -> int:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]*|[\u4e00-\u9fff]", text)
    return max(1, len(words)) if text else 0


def _flags_for_range(flags: list[str], start_offset: int, end_offset: int) -> list[str]:
    selected: list[str] = []
    for flag in flags:
        _name, separator, offset_value = flag.rpartition("@")
        if separator and offset_value.isdigit() and start_offset <= int(offset_value) < end_offset:
            selected.append(flag)
    return selected
