"""NVD CVE API evidence source."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from agent_network.evidence.http import EvidenceHttpClient, SourceRequestAudit
from agent_network.evidence.online_common import api_datetime, claim_cve_id, now_utc
from agent_network.evidence.schemas import Claim, ClaimType, Evidence


class NvdEvidenceSource:
    name = "nvd"

    def __init__(self, http: EvidenceHttpClient, api_key: str | None = None) -> None:
        self.http = http
        self.api_key = api_key
        self.last_audit: SourceRequestAudit | None = None

    @property
    def network_request_count(self) -> int:
        return self.http.network_request_count

    def search(self, claim: Claim) -> list[Evidence]:
        cve_id = claim_cve_id(claim)
        if not cve_id:
            return []
        url = f"https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={quote(cve_id)}"
        headers = {"Accept": "application/json", "User-Agent": "agent-network/0.2.0"}
        if self.api_key:
            headers["apiKey"] = self.api_key
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
            vulnerabilities = payload.get("vulnerabilities") or []
            evidence = []
            for item in vulnerabilities:
                cve = item.get("cve") or {}
                if str(cve.get("id") or "").upper() != cve_id:
                    continue
                evidence.append(_map_nvd_record(claim, cve, fetched.audit.response_hash))
            return evidence
        except (
            AttributeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            _record_mapping_error(self.last_audit, exc)
            return []


def _map_nvd_record(claim: Claim, cve: dict[str, Any], response_hash: str | None) -> Evidence:
    cve_id = str(cve["id"]).upper()
    description = _english_description(cve.get("descriptions") or [])
    cvss = _cvss(cve.get("metrics") or {})
    references = [str(item.get("url")) for item in cve.get("references") or [] if item.get("url")]
    configurations = cve.get("configurations") or []
    source_identifier = cve.get("sourceIdentifier")
    return Evidence(
        evidence_id=f"nvd-{cve_id.lower()}",
        claim_id=claim.claim_id,
        source_type="nvd_cve_api",
        source_title=f"NVD record for {cve_id}",
        source_url=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
        official_domain="nvd.nist.gov",
        retrieved_at=now_utc(),
        published_at=api_datetime(cve.get("published")),
        updated_at=api_datetime(cve.get("lastModified")),
        product_version=None,
        excerpt=description or f"NVD record {cve_id}",
        relevance_score=1.0,
        source_priority=85,
        supports_claim=claim.claim_type == ClaimType.CVE_EXISTENCE,
        contradicts_claim=False,
        notes="NVD returned a matching CVE record; absence of a record is not a contradiction.",
        product=claim.product,
        component=claim.component,
        claim_types=[claim.claim_type],
        keywords=[cve_id, "NVD", "CVSS"],
        official_value=cve_id if claim.claim_type == ClaimType.CVE_EXISTENCE else None,
        fixture_only=False,
        response_hash=response_hash,
        source_metadata={
            "cve_id": cve_id,
            "description": description,
            "published": cve.get("published"),
            "last_modified": cve.get("lastModified"),
            "cvss": cvss,
            "references": references,
            "configurations": configurations,
            "source_identifier": source_identifier,
        },
    )


def _english_description(descriptions: list[dict[str, Any]]) -> str:
    for item in descriptions:
        if item.get("lang") == "en" and item.get("value"):
            return str(item["value"])
    return str(descriptions[0].get("value") or "") if descriptions else ""


def _cvss(metrics: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key) or []
        if not entries:
            continue
        entry = entries[0]
        data = entry.get("cvssData") or {}
        return {
            "version": data.get("version"),
            "base_score": data.get("baseScore"),
            "vector_string": data.get("vectorString"),
            "base_severity": data.get("baseSeverity") or entry.get("baseSeverity"),
            "source": entry.get("source"),
            "type": entry.get("type"),
        }
    return None


def _record_mapping_error(audit: SourceRequestAudit | None, exc: Exception) -> None:
    if audit is None:
        return
    audit.error_type = "response_mapping_error"
    audit.error_message = str(exc)[:500]
