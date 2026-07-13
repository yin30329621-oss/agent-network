"""Lightweight language helpers for report output."""

from __future__ import annotations

import re

ZH_REVIEW_INSTRUCTION = (
    "The input document is written in Simplified Chinese. Return all human-readable "
    "review content in Simplified Chinese. Keep JSON field names, severity enum values, "
    "CVE identifiers, commands, code, URLs, API paths, Kubernetes object names, "
    "Namespaces, product names, model names, provider names, and technical identifiers "
    "unchanged. Do not output English explanatory prose unless a technical term should "
    "remain in English. Do not output analysis, a thinking process, Markdown, or JSON "
    "code fences."
)


def detect_language(text: str) -> str:
    """Return zh-CN for likely Simplified Chinese input, otherwise en."""

    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    return "zh-CN" if len(cjk_chars) >= 8 else "en"


def is_chinese_language(language: str | None) -> bool:
    return bool(language and language.lower().startswith("zh"))
