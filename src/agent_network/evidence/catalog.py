"""Deterministic, catalog-only official document queries."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from agent_network.evidence.schemas import DocumentCatalog, DocumentType
from agent_network.evidence.vocabulary import (
    components_match,
    normalize_component,
    normalize_official_domain,
    normalize_product,
    products_match,
)


class DocumentCatalogQuery(BaseModel):
    """Exact, normalized filters for official document catalog records."""

    claim_id: str | None = None
    product: str | None = None
    component: str | None = None
    official_domain: str | None = None
    document_type: DocumentType | None = None

    @field_validator("claim_id", mode="before")
    @classmethod
    def normalize_claim_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("claim_id must not be empty")
        return normalized

    @field_validator("product", mode="before")
    @classmethod
    def normalize_query_product(cls, value: Any) -> str | None:
        return normalize_product(str(value)) if value is not None else None

    @field_validator("component", mode="before")
    @classmethod
    def normalize_query_component(cls, value: Any) -> str | None:
        return normalize_component(str(value)) if value is not None else None

    @field_validator("official_domain", mode="before")
    @classmethod
    def normalize_query_domain(cls, value: Any) -> str | None:
        return normalize_official_domain(str(value)) if value is not None else None


class DocumentCatalogRepository:
    """Validated in-memory catalog with stable, exact-match query semantics."""

    def __init__(
        self,
        documents: Iterable[DocumentCatalog | dict[str, Any]],
        *,
        allowed_domains: set[str] | None = None,
    ) -> None:
        validated = [DocumentCatalog.model_validate(document) for document in documents]
        if allowed_domains is not None:
            unexpected = [
                document.official_domain
                for document in validated
                if document.official_domain not in allowed_domains
            ]
            if unexpected:
                raise ValueError("catalog contains domains outside the configured source")
        self._documents = tuple(validated)
        self.network_request_count = 0
        self.model_call_count = 0

    def query(self, query: DocumentCatalogQuery | None = None) -> list[DocumentCatalog]:
        criteria = query or DocumentCatalogQuery()
        candidates = [document for document in self._documents if _matches(document, criteria)]
        ordered = sorted(candidates, key=lambda document: _sort_key(document, criteria))
        unique: list[DocumentCatalog] = []
        seen_urls: set[str] = set()
        for document in ordered:
            if document.canonical_url in seen_urls:
                continue
            seen_urls.add(document.canonical_url)
            unique.append(document)
        return unique


def _matches(document: DocumentCatalog, query: DocumentCatalogQuery) -> bool:
    if query.claim_id is not None and query.claim_id not in document.supported_claim_ids:
        return False
    if query.product is not None and not products_match(query.product, document.product):
        return False
    if query.component is not None and not any(
        components_match(query.component, component) for component in document.components
    ):
        return False
    if query.official_domain is not None and document.official_domain != query.official_domain:
        return False
    return query.document_type is None or document.document_type == query.document_type


def _sort_key(
    document: DocumentCatalog, query: DocumentCatalogQuery
) -> tuple[float | int | str, ...]:
    claim_match = query.claim_id is not None and query.claim_id in document.supported_claim_ids
    product_match = query.product is not None and products_match(query.product, document.product)
    component_match = query.component is not None and any(
        components_match(query.component, component) for component in document.components
    )
    return (
        -int(claim_match),
        -int(product_match and component_match),
        -int(product_match),
        -int(component_match),
        _descending_time(document.updated_at),
        _descending_time(document.published_at),
        document.canonical_url,
        document.document_id,
    )


def _descending_time(value: datetime | None) -> float:
    return -value.timestamp() if value is not None else float("inf")
