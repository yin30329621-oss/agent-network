"""Standalone public-CVE pilot helpers."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_network import __version__
from agent_network.evidence.schemas import Claim, ClaimType, Evidence


def public_cve_claim(cve_id: str) -> Claim:
    normalized = cve_id.strip().upper()
    if not re.fullmatch(r"CVE-\d{4}-\d{4,}", normalized):
        raise ValueError("CVE ID must use the form CVE-YYYY-NNNN")
    return Claim(
        claim_id=f"pilot-{normalized.lower()}",
        source_file="public-cve-pilot",
        section="Public CVE Pilot",
        line_start=1,
        line_end=1,
        original_text=f"{normalized} exists as a published CVE record.",
        normalized_claim=f"{normalized} exists as a published CVE record",
        claim_type=ClaimType.CVE_EXISTENCE,
        entities=[{"type": "cve", "value": normalized}],
        product="Rancher Manager",
        component="CVE",
        version_scope={"raw": "unknown"},
        verification_priority="high",
        requires_external_evidence=True,
        status="pending",
    )


def write_pilot_output(
    *,
    output_dir: str | Path,
    cve_id: str,
    source_name: str,
    evidence: list[Evidence],
    audit: dict[str, Any] | None,
    network_request_count: int,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evidence_path = output / "evidence.json"
    audit_path = output / "audit.json"
    run_path = output / "run.json"
    evidence_path.write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in evidence], ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    audit_path.write_text(json.dumps(audit or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    run = {
        "run_id": f"evidence-pilot-{uuid4().hex[:12]}",
        "version": __version__,
        "mode": "public_cve_pilot",
        "source": source_name,
        "query": cve_id.upper(),
        "completed_at": datetime.now(UTC).isoformat(),
        "evidence_count": len(evidence),
        "network_request_count": network_request_count,
        "model_call_count": 0,
        "output_files": {
            "evidence": str(evidence_path),
            "audit": str(audit_path),
        },
    }
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"evidence": evidence_path, "audit": audit_path, "run": run_path}
