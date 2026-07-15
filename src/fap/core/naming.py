"""Name normalization shared by every layer.

These two helpers are needed by both the domain (the mapping engine, mapping
templates) and infrastructure (provider intelligence, custom providers). They
live in fap.core so that providers never have to import the pipeline: the
layering rule is that dependencies point downward only, and a second copy of
either function would be worse than the import.

Both are re-exported from their historical homes - fap.pipeline.columns and
fap.pipeline.templates - so existing imports keep working.
"""
from __future__ import annotations

import hashlib
import re


def normalize_name(name: str) -> str:
    """Comparison key: lowercase, alphanumerics only - so 'Start X', 'start_x',
    'startX' and 'startx' all compare equal. The one normalizer every caller
    (platform and Open Play alike) must use."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def column_signature(columns: list[str]) -> str:
    """Stable fingerprint of a file's column shape, order-independent."""
    normalized = sorted(str(c).strip().lower() for c in columns)
    return hashlib.sha256("|".join(normalized).encode()).hexdigest()[:24]
