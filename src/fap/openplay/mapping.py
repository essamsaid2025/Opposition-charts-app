"""Open Play column-mapping controller.

Translates between Open Play's field vocabulary (x2/y2) and the platform's
canonical schema (end_x/end_y), and drives the mapping preview. The alias table,
normalizer, candidate ranking and detection all live in fap.pipeline.columns -
there is no second alias list here. Streamlit-free: the import service is
resolved through fap.openplay.runtime.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from fap.core.exceptions import FAPError
from fap.openplay.config import (
    APP_TO_PLATFORM, CANONICAL_LABELS, PLATFORM_TO_APP, REQUIRED_CANONICAL,
)
from fap.openplay.runtime import import_service
from fap.pipeline.columns import (
    CONFIDENCE_THRESHOLD,
    alias_candidates as platform_alias_candidates,
    detect_columns,
    normalize_name,
)

# the platform's normalizer, re-exported under the historical Open Play name
_norm_key = normalize_name


def alias_candidates(df: pd.DataFrame) -> Dict[str, List[str]]:
    """Platform alias candidates, expressed in Open Play's field names.
    Best match first; used for the preview log and the mapping dialog."""
    platform = platform_alias_candidates(df)
    return {app_field: list(platform[plat_field])
            for app_field, plat_field in APP_TO_PLATFORM.items()
            if platform.get(plat_field)}


def platform_detect(df: pd.DataFrame) -> Tuple[object, Optional[str]]:
    """Platform detection for this file shape: a saved mapping template wins,
    otherwise the alias engine. Returns (ColumnMapping, template_name)."""
    try:
        return import_service().detect(df)
    except FAPError:
        # no template store available (e.g. read-only deployment) -> aliases only
        return detect_columns(df), None


def auto_map_columns(df: pd.DataFrame) -> Dict[str, str]:
    """Best-match auto detection via the platform. Returns {canonical: source}
    for the fields Open Play maps; every rule behind it belongs to the platform."""
    detected, _template = platform_detect(df)
    mapping: Dict[str, str] = {}
    for source, plat_field in detected.mapping.items():
        app_field = PLATFORM_TO_APP.get(plat_field)
        if app_field:
            mapping[app_field] = source
    return mapping


def mapping_confidence(df: pd.DataFrame) -> float:
    """Platform confidence for the fields Open Play requires. Below the
    platform's CONFIDENCE_THRESHOLD the mapping dialog opens."""
    detected, _template = platform_detect(df)
    return detected.confidence_for([APP_TO_PLATFORM[c] for c in REQUIRED_CANONICAL])


def save_mapping_template(name: str, df: pd.DataFrame, mapping: Dict[str, str],
                          filename: str) -> None:
    """Persist the confirmed mapping through the platform TemplateRepository so
    the next file with this column shape maps itself."""
    svc = import_service()
    source_to_canonical = {src: APP_TO_PLATFORM[canon]
                           for canon, src in mapping.items() if src}
    svc.save_template(name, svc.pick_provider(filename).info.id,
                      [str(c) for c in df.columns], source_to_canonical)


def mapping_log(df: pd.DataFrame, mapping: Dict[str, str]) -> List[str]:
    """Human-readable notes for cases where several aliases were present and a
    best match had to be chosen (requirement: 'use the best match and log it')."""
    cands = alias_candidates(df)
    logs: List[str] = []
    for canon, chosen in mapping.items():
        others = [c for c in cands.get(canon, []) if c != chosen]
        if others:
            logs.append(f"{CANONICAL_LABELS.get(canon, canon)}: using '{chosen}' "
                        f"(also matched: {', '.join(others)})")
    return logs


def resolve_column_mapping(df: pd.DataFrame,
                           manual: Optional[Dict[str, str]] = None
                           ) -> Tuple[Dict[str, str], List[str]]:
    """Auto detection combined with a user/session manual map (manual wins).
    Returns (mapping {canonical: source}, unresolved_required_canonicals)."""
    mapping = auto_map_columns(df)
    for canon, src in (manual or {}).items():
        if src and src in df.columns:
            for other in [k for k, v in mapping.items() if v == src and k != canon]:
                del mapping[other]            # free the source from any auto claim
            mapping[canon] = src
    unresolved = [c for c in REQUIRED_CANONICAL if c not in mapping]
    return mapping, unresolved


def apply_column_mapping(df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
    """Rename detected/selected source columns to their canonical names."""
    rename = {src: canon for canon, src in mapping.items()
              if src in df.columns and src != canon and canon not in df.columns}
    return df.rename(columns=rename) if rename else df


def mapping_preview_table(df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
    """Original column -> mapped canonical field, for every uploaded column."""
    inv = {src: canon for canon, src in mapping.items()}
    rows = [{"Original column": col,
             "Mapped to": CANONICAL_LABELS.get(inv[col], inv[col]) if col in inv else "—"}
            for col in df.columns]
    return pd.DataFrame(rows, columns=["Original column", "Mapped to"])
