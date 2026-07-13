"""Deterministic, in-memory BM25 retrieval over official document chunks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log
import re
import unicodedata

from agent_network.evidence.document_chunker import DocumentChunk
from agent_network.evidence.vocabulary import components_match, products_match


_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "of",
        "to",
        "and",
        "in",
        "for",
        "with",
        "through",
        "used",
        "this",
        "that",
        "from",
        "into",
        "about",
        "by",
        "as",
    }
)
_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\ufeff]")
_TOKEN_PATTERN = re.compile(
    r"cve-\d{4}-\d+|v?\d+(?:\.\d+){1,3}|[a-z][a-z0-9]*(?:-[a-z0-9]+)*|\d+|[\u4e00-\u9fff]+"
)


class Bm25Error(RuntimeError):
    """A safe, categorical failure while indexing or searching document chunks."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Bm25Config:
    k1: float = 1.5
    b: float = 0.75
    include_zero_scores: bool = False

    def __post_init__(self) -> None:
        if self.k1 <= 0 or not 0 <= self.b <= 1:
            raise Bm25Error("invalid_config", "BM25 configuration is invalid")


@dataclass(frozen=True, slots=True)
class Bm25SearchQuery:
    query_text: str
    top_k: int = 5
    product: str | None = None
    component: str | None = None
    document_type: str | None = None
    document_id: str | None = None


@dataclass(slots=True)
class Bm25SearchResult:
    rank: int
    score: float
    chunk: DocumentChunk
    matched_terms: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "score": self.score,
            "chunk": self.chunk.to_dict(),
            "matched_terms": self.matched_terms,
        }


class OfficialDocumentBm25Index:
    """Small, deterministic BM25Okapi index with fixed document-field weights."""

    def __init__(self, chunks: list[DocumentChunk], config: Bm25Config | None = None) -> None:
        self.config = config or Bm25Config()
        self.network_request_count = 0
        self.model_call_count = 0
        self._chunks = tuple(sorted(chunks, key=_chunk_sort_key))
        _validate_unique_chunk_ids(self._chunks)
        try:
            self._token_counts = tuple(Counter(_chunk_tokens(chunk)) for chunk in self._chunks)
            self._document_frequency = Counter(
                token for counts in self._token_counts for token in counts.keys()
            )
            self._average_document_length = (
                sum(sum(counts.values()) for counts in self._token_counts) / len(self._token_counts)
                if self._token_counts
                else 0.0
            )
        except Bm25Error:
            raise
        except Exception as exc:
            raise Bm25Error("indexing_error", "BM25 index construction failed") from exc

    def search(self, query: Bm25SearchQuery) -> list[Bm25SearchResult]:
        if not self._chunks:
            raise Bm25Error("empty_index", "BM25 index has no document chunks")
        if query.top_k <= 0:
            raise Bm25Error("invalid_top_k", "BM25 top_k must be positive")
        query_tokens = _query_tokens(query.query_text)
        if not query_tokens:
            raise Bm25Error("empty_query", "BM25 query has no searchable terms")

        try:
            candidates = [
                (chunk, counts)
                for chunk, counts in zip(self._chunks, self._token_counts, strict=True)
                if _matches_filters(chunk, query)
            ]
            scored = [
                (self._score(query_tokens, counts), chunk, counts) for chunk, counts in candidates
            ]
            if not self.config.include_zero_scores:
                scored = [item for item in scored if item[0] > 0]
            scored.sort(key=lambda item: (-item[0], *_chunk_sort_key(item[1])))
            return [
                Bm25SearchResult(
                    rank=rank,
                    score=score,
                    chunk=chunk,
                    matched_terms=[token for token in query_tokens if token in counts],
                )
                for rank, (score, chunk, counts) in enumerate(scored[: query.top_k], start=1)
            ]
        except Bm25Error:
            raise
        except Exception as exc:
            raise Bm25Error("search_error", "BM25 search failed") from exc

    def _score(self, query_tokens: list[str], counts: Counter[str]) -> float:
        document_length = sum(counts.values())
        score = 0.0
        for token in dict.fromkeys(query_tokens):
            frequency = counts.get(token, 0)
            if not frequency:
                continue
            inverse_frequency = log(
                1
                + (len(self._chunks) - self._document_frequency[token] + 0.5)
                / (self._document_frequency[token] + 0.5)
            )
            denominator = frequency + self.config.k1 * (
                1 - self.config.b + self.config.b * document_length / self._average_document_length
            )
            score += inverse_frequency * frequency * (self.config.k1 + 1) / denominator
        return score


def tokenize(text: str) -> list[str]:
    """Normalize text and produce stable English, technical, and Chinese tokens."""

    normalized = _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text).lower())
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        value = match.group(0)
        if _contains_chinese(value):
            tokens.extend(value)
            tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
        elif value not in _STOPWORDS:
            tokens.append(value)
    return tokens


def _chunk_tokens(chunk: DocumentChunk) -> list[str]:
    # Fixed weights: title and section heading twice; body, product, component once.
    return (
        tokenize(chunk.document_title) * 2
        + tokenize(chunk.section_heading) * 2
        + tokenize(chunk.text)
        + tokenize(chunk.product)
        + tokenize(chunk.component)
    )


def _query_tokens(query_text: str) -> list[str]:
    return list(dict.fromkeys(tokenize(query_text)))


def _matches_filters(chunk: DocumentChunk, query: Bm25SearchQuery) -> bool:
    if query.product is not None and not products_match(chunk.product, query.product):
        return False
    if query.component is not None and not components_match(chunk.component, query.component):
        return False
    if query.document_type is not None and chunk.document_type != query.document_type:
        return False
    return query.document_id is None or chunk.document_id == query.document_id


def _validate_unique_chunk_ids(chunks: tuple[DocumentChunk, ...]) -> None:
    identifiers = [chunk.chunk_id for chunk in chunks]
    if len(identifiers) != len(set(identifiers)):
        raise Bm25Error("duplicate_chunk_id", "BM25 index received duplicate chunk identifiers")


def _chunk_sort_key(chunk: DocumentChunk) -> tuple[str, int, int, str]:
    return (chunk.document_id, chunk.section_order, chunk.chunk_order, chunk.chunk_id)


def _contains_chinese(value: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in value)
