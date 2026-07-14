"""Deterministic text normalization and Claim identity helpers."""

from __future__ import annotations

import re
import unicodedata
from hashlib import sha256


_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_claim_text(value: str) -> str:
    """Return comparison text without changing the stored original statement."""

    return clean_claim_text(value).lower()


def clean_claim_text(value: str) -> str:
    """Remove Markdown wrappers while preserving display-text casing."""

    text = unicodedata.normalize("NFKC", value)
    text = _ZERO_WIDTH.sub("", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[`*_~]", "", text)
    text = _CONTROL.sub(" ", text)
    return " ".join(text.split())


def claim_id_for(source_name: str, heading_path: list[str], normalized_text: str) -> str:
    """Create a stable ID from source identity, heading context, and normalized text."""

    identity = "\x1f".join([source_name.strip(), " / ".join(heading_path), normalized_text])
    digest = sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"claim-{digest}"


def slugify_heading(value: str) -> str:
    normalized = normalize_claim_text(value)
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", normalized).strip("-")
    return slug or "section"
