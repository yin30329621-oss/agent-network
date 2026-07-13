"""GitHub Global Security Advisory API evidence source."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlparse

from agent_network.evidence.http import EvidenceHttpClient, SourceRequestAudit
from agent_network.evidence.online_common import api_datetime, claim_cve_id, now_utc
from agent_network.evidence.schemas import Claim, ClaimType, Evidence


class GitHubAdvisoryEvidenceSource:
    name = "github_advisory"

    def __init__(self, http: EvidenceHttpClient, token: str | None = None) -> None:
        self.http = http
        self.token = token
        self.last_audit: SourceRequestAudit | None = None

    @property
    def network_request_count(self) -> int:
        return self.http.network_request_count

    def search(self, claim: Claim) -> list[Evidence]:
        cve_id = claim_cve_id(claim)
        if not cve_id:
            return []
        url = f"https://api.github.com/advisories?cve_id={quote(cve_id)}&per_page=100"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-network/0.2.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        fetched = self.http.get(
            source_name=self.name,
            query=cve_id,
            url=url,
            headers=headers,
        )
        self.last_audit = self.http.last_audit
        if fetched is None:
            return []
        try:
            payload = json.loads(fetched.body.decode("utf-8"))
            if not isinstance(payload, list):
                raise TypeError("GitHub advisory response must be a list")
            return [
                _map_github_advisory(claim, item, cve_id, fetched.audit.response_hash)
                for item in payload
                if _has_cve(item, cve_id)
            ]
        except (
            AttributeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            _record_mapping_error(self.last_audit, exc)
            return []


def _map_github_advisory(
    claim: Claim,
    advisory: dict[str, Any],
    cve_id: str,
    response_hash: str | None,
) -> Evidence:
    ghsa_id = str(advisory.get("ghsa_id") or "unknown-ghsa")
    description = str(advisory.get("description") or advisory.get("summary") or ghsa_id)
    html_url = _github_advisory_url(advisory.get("html_url"), ghsa_id)
    cwes = [
        {"cwe_id": item.get("cwe_id"), "name": item.get("name")}
        for item in advisory.get("cwes") or []
    ]
    vulnerabilities = [
        {
            "ecosystem": (item.get("package") or {}).get("ecosystem"),
            "package": (item.get("package") or {}).get("name"),
            "vulnerable_version_range": item.get("vulnerable_version_range"),
            "first_patched_version": _first_patched_version(item.get("first_patched_version")),
        }
        for item in advisory.get("vulnerabilities") or []
    ]
    references = [url for item in advisory.get("references") or [] if (url := _reference_url(item))]
    return Evidence(
        evidence_id=f"github-{ghsa_id.lower()}",
        claim_id=claim.claim_id,
        source_type="github_global_security_advisory_api",
        source_title=f"GitHub Advisory {ghsa_id}",
        source_url=html_url,
        official_domain="github.com",
        retrieved_at=now_utc(),
        published_at=api_datetime(advisory.get("published_at")),
        updated_at=api_datetime(advisory.get("updated_at")),
        product_version=None,
        excerpt=description,
        relevance_score=1.0,
        source_priority=80,
        supports_claim=claim.claim_type == ClaimType.CVE_EXISTENCE,
        contradicts_claim=False,
        notes="GitHub returned a matching global advisory; no result is not a contradiction.",
        product=claim.product,
        component=claim.component,
        claim_types=[claim.claim_type],
        keywords=[cve_id, ghsa_id, "GHSA"],
        official_value=(
            f"{cve_id} / {ghsa_id}" if claim.claim_type == ClaimType.CVE_EXISTENCE else None
        ),
        fixture_only=False,
        response_hash=response_hash,
        source_metadata={
            "cve_id": cve_id,
            "ghsa_id": ghsa_id,
            "severity": advisory.get("severity"),
            "cvss": advisory.get("cvss"),
            "cwes": cwes,
            "description": description,
            "published_at": advisory.get("published_at"),
            "updated_at": advisory.get("updated_at"),
            "vulnerabilities": vulnerabilities,
            "references": references,
            "rate_limit_remaining": None,
        },
    )


def _has_cve(advisory: dict[str, Any], cve_id: str) -> bool:
    return str(advisory.get("cve_id") or "").upper() == cve_id


def _first_patched_version(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        identifier = value.get("identifier")
        return str(identifier) if identifier else None
    return None


def _reference_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        url = value.get("url")
        return str(url) if url else None
    return None


def _github_advisory_url(value: Any, ghsa_id: str) -> str:
    candidate = str(value or "")
    parsed = urlparse(candidate)
    if parsed.scheme == "https" and parsed.hostname == "github.com":
        return candidate
    return f"https://github.com/advisories/{ghsa_id}"


def _record_mapping_error(audit: SourceRequestAudit | None, exc: Exception) -> None:
    if audit is None:
        return
    audit.error_type = "response_mapping_error"
    audit.error_message = str(exc)[:500]
