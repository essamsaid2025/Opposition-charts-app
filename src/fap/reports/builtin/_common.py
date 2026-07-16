"""Shared helpers for built-in sections. All analytics are REUSED from the
platform (fap.metrics, fap.analytics, fap.visuals.analysis) - nothing here
recomputes what the platform already computes."""
from __future__ import annotations

from typing import Callable

import pandas as pd

from fap.reports.models import Insight, KPI, Table


def safe(fn: Callable, default=None):
    try:
        return fn()
    except Exception:
        return default


def pct(n: float, d: float) -> str:
    return "0%" if not d else f"{n / d * 100:.0f}%"


def count(df) -> int:
    return 0 if df is None else int(len(df))


def event_slice(df: pd.DataFrame, name: str) -> pd.DataFrame:
    if df is None or "event_type" not in df.columns:
        return df.iloc[0:0] if df is not None else df
    return df[df["event_type"].astype(str).str.lower() == name]


def platform_metric_kpis(df: pd.DataFrame, limit: int = 6) -> list[KPI]:
    """Reuse the platform Metric registry (compute_all) - no recomputation."""
    def _run():
        from fap.metrics.base import compute_all, load_builtin_metrics
        load_builtin_metrics()
        return [KPI(label=r.label, value=str(r.formatted)) for r in compute_all(df)][:limit]
    return safe(_run, []) or []


def platform_insights(df: pd.DataFrame, limit: int = 4) -> list[Insight]:
    """Reuse the platform InsightEngine - no recomputation."""
    def _run():
        from fap.analytics.insights import InsightEngine
        return [Insight(text=s) for s in InsightEngine().run(df)][:limit]
    return safe(_run, []) or []


def top_counts(df: pd.DataFrame, column: str, n: int = 5, title: str = "") -> Table:
    if df is None or column not in df.columns or df.empty:
        return Table(title=title, columns=[column.title(), "Count"], rows=[])
    vc = (df[column].astype(str).str.strip().replace("", pd.NA).dropna()
          .value_counts().head(n))
    return Table(title=title, columns=[column.title(), "Count"],
                 rows=[[k, int(v)] for k, v in vc.items()])
