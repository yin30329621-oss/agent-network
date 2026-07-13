"""Local input sizing used before a review starts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

SMALL_CHARACTER_LIMIT = 8_000
MEDIUM_CHARACTER_LIMIT = 20_000


@dataclass(frozen=True, slots=True)
class InputAnalysis:
    input_characters: int
    input_lines: int
    estimated_input_tokens: int
    input_size_class: str

    def to_dict(self) -> dict[str, int | str]:
        return asdict(self)


def analyze_input(text: str) -> InputAnalysis:
    characters = len(text)
    lines = text.count("\n") + 1 if text else 0
    cjk_characters = sum("\u4e00" <= char <= "\u9fff" for char in text)
    non_cjk_characters = sum(
        not char.isspace() and not ("\u4e00" <= char <= "\u9fff") for char in text
    )
    estimated_tokens = math.ceil(cjk_characters / 1.5 + non_cjk_characters / 4)
    if characters < SMALL_CHARACTER_LIMIT:
        size_class = "small"
    elif characters <= MEDIUM_CHARACTER_LIMIT:
        size_class = "medium"
    else:
        size_class = "long"
    return InputAnalysis(
        input_characters=characters,
        input_lines=lines,
        estimated_input_tokens=estimated_tokens,
        input_size_class=size_class,
    )
