from __future__ import annotations

import re


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "untitled"


def pct(numerator: float, denominator: float) -> str:
    return "0%" if denominator == 0 else f"{numerator / denominator * 100:.0f}%"
