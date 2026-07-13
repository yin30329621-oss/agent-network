"""Deterministic, offline chunking for cleaned official documents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
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

    def __post_init__(self) -> None:
        if (
            self.max_characters <= 0
            or self.overlap_characters < 0
            or self.overlap_characters >= self.max_characters
            or self.min_chunk_characters < 0
            or self.min_chunk_characters > self.max_characters
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
        for section_index, section in enumerate(sections):
            text = section.text.strip()
            if not text:
                continue
            parts = _split_section(text, self.config)
            for part_index, part in enumerate(parts):
                chunk_order = len(chunks)
                chunks.append(
                    DocumentChunk(
                        chunk_id=_chunk_id(document.document_id, section.order, part_index, part),
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
    return parts


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


def _chunk_id(document_id: str, section_order: int, chunk_order: int, text: str) -> str:
    digest = sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{document_id}:{section_order}:{chunk_order}:{digest}"
