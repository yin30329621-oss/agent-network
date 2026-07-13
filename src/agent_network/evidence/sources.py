"""Offline evidence source interface and fixture implementation."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from agent_network.evidence.schemas import Claim, DocumentCatalog, Evidence
from agent_network.evidence.vocabulary import components_match, products_match


class EvidenceSource(Protocol):
    def search(self, claim: Claim) -> list[Evidence]:
        """Return deterministic evidence candidates for a claim."""


class OfficialDocumentEvidenceSource(EvidenceSource, ABC):
    """Port for catalog-backed official documentation sources.

    Phase 2B can add fetching and chunk retrieval behind this interface without
    changing the evidence verifier or agent workflow.
    """

    source_name: str
    allowed_domains: frozenset[str]
    network_request_count: int = 0

    def __init__(self, source_name: str, allowed_domains: set[str]) -> None:
        self.source_name = source_name
        self.allowed_domains = frozenset(allowed_domains)

    def validate_catalog(self, document: DocumentCatalog) -> None:
        if document.source_name != self.source_name:
            raise ValueError("document source_name does not match source")
        if document.official_domain not in self.allowed_domains:
            raise ValueError("document domain is not configured for this source")

    @abstractmethod
    def search(self, claim: Claim) -> list[Evidence]:
        """Return evidence from an official document catalog."""


@dataclass(slots=True)
class DocumentCatalogFixture:
    fixture_id: str
    fixture_notice: str
    documents: list[DocumentCatalog]

    @classmethod
    def load(cls, path: str | Path) -> "DocumentCatalogFixture":
        root = Path(path)
        metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        documents = [
            DocumentCatalog.model_validate(item)
            for item in json.loads((root / "catalog.json").read_text(encoding="utf-8"))
        ]
        return cls(
            fixture_id=str(metadata["fixture_id"]),
            fixture_notice=str(metadata["fixture_notice"]),
            documents=documents,
        )


class FixtureOfficialDocumentEvidenceSource(OfficialDocumentEvidenceSource):
    """Catalog-only source for tests; it performs no document retrieval."""

    def __init__(
        self, source_name: str, allowed_domains: set[str], documents: list[DocumentCatalog]
    ):
        super().__init__(source_name, allowed_domains)
        self.documents = list(documents)
        for document in self.documents:
            self.validate_catalog(document)

    def search(self, claim: Claim) -> list[Evidence]:
        evidence: list[Evidence] = []
        for document in self.documents:
            if claim.claim_id not in document.supported_claim_ids:
                continue
            if not products_match(claim.product, document.product):
                continue
            if document.components and not any(
                components_match(claim.component, component) for component in document.components
            ):
                continue
            evidence.append(
                Evidence(
                    evidence_id=f"document-{document.document_id}",
                    claim_id=claim.claim_id,
                    source_type="official_document_catalog_fixture",
                    source_title=document.title,
                    source_url=document.canonical_url,
                    official_domain=document.official_domain,
                    retrieved_at=datetime.now(UTC),
                    published_at=document.published_at,
                    updated_at=document.updated_at,
                    product_version=document.product_version,
                    excerpt=document.fixture_excerpt or document.title,
                    relevance_score=1.0,
                    source_priority=document.source_priority,
                    supports_claim=True,
                    contradicts_claim=False,
                    notes="Catalog-only fixture evidence; no document content was fetched.",
                    product=document.product,
                    component=claim.component,
                    claim_types=[claim.claim_type],
                    keywords=document.tags,
                    fixture_only=True,
                    source_metadata={
                        "document_id": document.document_id,
                        "documentation_version": document.documentation_version,
                        "catalog_only": True,
                    },
                )
            )
        return evidence


@dataclass(slots=True)
class EvidenceFixture:
    fixture_id: str
    fixture_notice: str
    claims: list[Claim]
    evidence: list[Evidence]

    @classmethod
    def load(cls, path: str | Path) -> "EvidenceFixture":
        root = Path(path)
        metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        claims = [
            Claim.model_validate(item)
            for item in json.loads((root / "claims.json").read_text(encoding="utf-8"))
        ]
        evidence = [
            Evidence.model_validate(item)
            for item in json.loads((root / "evidence.json").read_text(encoding="utf-8"))
        ]
        return cls(
            fixture_id=str(metadata["fixture_id"]),
            fixture_notice=str(metadata["fixture_notice"]),
            claims=claims,
            evidence=evidence,
        )


class FakeEvidenceSource:
    """Local deterministic source backed only by fixture evidence."""

    def __init__(self, evidence: list[Evidence]) -> None:
        self._evidence = list(evidence)
        self.network_request_count = 0

    def search(self, claim: Claim) -> list[Evidence]:
        claim_terms = _terms(claim.normalized_claim)
        candidates: list[Evidence] = []
        for evidence in self._evidence:
            direct = evidence.claim_id == claim.claim_id
            same_scope = products_match(claim.product, evidence.product) and components_match(
                claim.component, evidence.component
            )
            keyword_match = bool(claim_terms & _terms(" ".join(evidence.keywords)))
            if direct or (same_scope and keyword_match):
                candidates.append(evidence)
        return sorted(candidates, key=lambda item: (-item.source_priority, item.evidence_id))


def _terms(value: str) -> set[str]:
    return {term.lower() for term in value.replace("/", " ").replace("-", " ").split() if term}
