"""Deterministic evidence matching without embeddings or external services."""

from __future__ import annotations

import re

from agent_network.evidence.schemas import Claim, Evidence, EvidenceMatch, VersionScope
from agent_network.evidence.vocabulary import components_match, products_match


class DeterministicEvidenceMatcher:
    def match(self, claim: Claim, evidence: Evidence) -> EvidenceMatch:
        product_match = products_match(claim.product, evidence.product)
        component_match = components_match(claim.component, evidence.component)
        claim_type_match = not evidence.claim_types or claim.claim_type in evidence.claim_types
        version_match = _version_matches(claim.version_scope, evidence.product_version)
        keyword_overlap = _keyword_overlap(claim, evidence)
        effective_relevance = min(1.0, (evidence.relevance_score * 0.8) + (keyword_overlap * 0.2))
        reasons = [
            f"product_match={str(product_match).lower()}",
            f"component_match={str(component_match).lower()}",
            f"claim_type_match={str(claim_type_match).lower()}",
            f"version_match={_optional_bool(version_match)}",
            f"keyword_overlap={keyword_overlap:.2f}",
            f"source_priority={evidence.source_priority}",
            f"relevance_score={evidence.relevance_score:.2f}",
        ]
        eligible = (
            product_match and component_match and claim_type_match and version_match is not False
        )
        if not product_match:
            reasons.append("rejected:wrong_product")
        if not component_match:
            reasons.append("rejected:wrong_component")
        if not claim_type_match:
            reasons.append("rejected:wrong_claim_type")
        if version_match is False:
            reasons.append("rejected:version_mismatch")
        return EvidenceMatch(
            evidence_id=evidence.evidence_id,
            eligible=eligible,
            product_match=product_match,
            component_match=component_match,
            claim_type_match=claim_type_match,
            version_match=version_match,
            keyword_overlap=keyword_overlap,
            effective_relevance=effective_relevance,
            reasons=reasons,
        )


def _keyword_overlap(claim: Claim, evidence: Evidence) -> float:
    claim_terms = _terms(claim.normalized_claim)
    evidence_terms = _terms(" ".join([evidence.excerpt, *evidence.keywords]))
    if not claim_terms:
        return 0.0
    return len(claim_terms & evidence_terms) / len(claim_terms)


def _terms(value: str) -> set[str]:
    return {
        term
        for term in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", value.lower())
        if len(term) > 1
    }


def _version_matches(scope: VersionScope, product_version: str | None) -> bool | None:
    if scope.raw.lower() in {"", "unknown", "any", "not_applicable"} and not any(
        [scope.exact, scope.minimum, scope.maximum]
    ):
        return None
    if not product_version:
        return None
    version = _version_tuple(product_version)
    if version is None:
        return None
    if scope.exact:
        exact = _version_tuple(scope.exact)
        return exact is not None and version == exact
    if scope.minimum:
        minimum = _version_tuple(scope.minimum)
        if minimum is not None and (
            version < minimum or (version == minimum and not scope.include_minimum)
        ):
            return False
    if scope.maximum:
        maximum = _version_tuple(scope.maximum)
        if maximum is not None and (
            version > maximum or (version == maximum and not scope.include_maximum)
        ):
            return False
    return True


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = re.search(r"\d+(?:\.\d+){0,3}", value)
    if not match:
        return None
    return tuple(int(part) for part in match.group(0).split("."))


def _optional_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return str(value).lower()
