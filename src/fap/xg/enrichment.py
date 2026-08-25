"""Centralized attachment of the internal xG column to an analysis frame.

This is the single helper the app's canonical enrichment
(``fap.openplay.transforms.add_derived_columns``) calls to add ``internal_xg``
to shot rows. It exists so no xG logic lives in the core transforms module — all
scoring still flows through ``fap.xg.services.xg_service`` -> frozen model.

Guarantees:
  * batched: one vectorized scoring call per frame (never per row),
  * shot-only: only ``event_type == 'shot'`` rows are scored; others -> NaN,
  * idempotent: ``attach_internal_xg`` skips work if the column already exists
    (unless ``force=True``); never creates ``internal_xg_x`` / duplicate columns,
  * failure-safe: if the frozen package/model can't load or any row is
    malformed, the affected values become NaN and a warning is logged — the app
    never crashes and no fake xG is substituted.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

COLUMN = "internal_xg"


def compute_internal_xg_series(df: pd.DataFrame, on_invalid: str = "nan") -> pd.Series:
    """Return an ``internal_xg`` Series aligned to ``df.index``.

    Non-shot rows and any unscoreable rows are NaN. Never raises.
    """
    result = pd.Series(np.nan, index=df.index, dtype=float)
    if len(df) == 0:
        return result

    if "event_type" in df.columns:
        shot_mask = df["event_type"].astype(str).str.lower().eq("shot")
    else:
        shot_mask = pd.Series(True, index=df.index)
    if not bool(shot_mask.any()):
        return result  # no shots -> fast path, model never loaded

    try:
        from fap.xg.services import xg_service  # lazy: keeps transforms import pure
        scored = xg_service.score_shots(df.loc[shot_mask], on_invalid=on_invalid)
        result.loc[shot_mask] = scored[xg_service.OUTPUT_COLUMN].to_numpy()
    except Exception:  # noqa: BLE001 - integration must never break the app
        log.warning("internal xG scoring unavailable; %s left as NaN", COLUMN, exc_info=True)
    return result


def sum_xg(shots: pd.DataFrame, column: str = COLUMN) -> float:
    """Team xG = Σ shot-level ``internal_xg`` (INCLUDING penalties).

    Pure aggregation of the canonical column — never recomputes the model and
    never derives xG from goals/shot counts/averages. Missing/NaN -> treated as
    0 (matching the app's existing xG summation convention).
    """
    s = pd.to_numeric(shots.get(column, pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    return float(s.sum())


def sum_npxg(shots: pd.DataFrame, column: str = COLUMN) -> float:
    """Non-penalty xG = Σ ``internal_xg`` over non-penalty shots only.

    Penalties are identified by ``set_piece == 'penalty'`` (the same rule the
    shot adapter uses); their xG is excluded. Pure aggregation.
    """
    s = pd.to_numeric(shots.get(column, pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    sp = shots.get("set_piece", pd.Series("", index=shots.index)).astype(str).str.strip().str.lower()
    return float(s.where(sp.ne("penalty"), 0.0).sum())


def attach_internal_xg(df: pd.DataFrame, *, force: bool = False,
                       on_invalid: str = "nan") -> pd.DataFrame:
    """Return a COPY of ``df`` with an ``internal_xg`` column.

    Idempotent: if ``internal_xg`` already exists it is preserved unless
    ``force=True``. The caller's dataframe is never mutated.
    """
    if COLUMN in df.columns and not force:
        return df.copy()
    out = df.copy()
    out[COLUMN] = compute_internal_xg_series(out, on_invalid=on_invalid)
    return out
