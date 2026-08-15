"""Player-scouting visualization ADAPTER (pure, no Streamlit, no matplotlib).

The bridge from a player-scouting dataset to the chart layer. It reads the
persisted scouting schema + the dataset frame and produces a ``ScoutingView`` -
per-metric values, units, transparently-inferred categories, and population
statistics (percentile / rank / min / max / median / mean) for the selected
player(s). It also decides which chart types make analytical sense and how a
pizza chart's slice values should be derived.

Two hard rules the whole feature depends on:
* It NEVER touches event data (no x/y/event_type) - it operates only on the
  scouting metric table.
* It NEVER re-normalizes a dataset that is already normalized. ``value_scale``
  from the schema decides whether a pizza/radar shows the raw normalized value or
  a percentile computed for visualization only; the source value is never
  overwritten.

Row-count agnostic: 1, 2, 33 or 500+ players go through the same code; only the
population-dependent statistics and chart availability change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- chart catalog
CHART_TYPES: tuple[str, ...] = (
    "bar", "ranking_bar", "percentile_bar", "radar", "pizza", "scatter",
    "histogram", "box", "lollipop", "comparison", "small_multiples", "heatmap",
)
CHART_LABELS: dict[str, str] = {
    "bar": "Metric Bar Chart", "ranking_bar": "Horizontal Ranking Bar",
    "percentile_bar": "Percentile Bar", "radar": "Radar Chart", "pizza": "Pizza Chart",
    "scatter": "Scatter Plot", "histogram": "Distribution / Histogram", "box": "Box Plot",
    "lollipop": "Lollipop Chart", "comparison": "Metric Comparison",
    "small_multiples": "Small Multiples", "heatmap": "Heatmap / Metric Matrix",
}

# value scales (mirror scouting_schema)
SCALE_NORMALIZED = "normalized"
SCALE_RAW = "raw"

# minimum populations for population-dependent charts (analytical sense, section 4)
_MIN_POP_RANK = 2
_MIN_POP_BOX = 5
_MIN_POP_HIST = 8
_MIN_POP_SCATTER = 3

# ---------------------------------------------------------------- categories
# Transparent, name-based category inference (section 18). Priority order resolves
# overlaps (e.g. "progressive passes" -> Progression, not Passing). No match -> Other.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Goalkeeping", ("save", "conceded", "prevented goal", "goals prevented",
                     "exits", "goalkeep", "shots against", " gk ")),
    ("Shooting", ("non-penalty goal", "npxg", "xg", "goal conversion", "goals per",
                  "goal per", "shots per", "shot per", "touches in box", "shots",
                  "finishing", "goals ")),
    ("Chance Creation", ("assist", "xa", "key pass", "shot assist", "smart pass",
                         "cross", "through ball", "chance")),
    ("Progression", ("progressive", "carr", "dribbl", "final third",
                     "deep completion", "accelerat")),
    ("Passing", ("pass", "long ball", "switch", "received", "distribution")),
    ("Possession", ("touch", "possession", "hold", "retention")),
    ("Defensive", ("tackle", "interception", "intercept", "block", "clearance",
                   "defensive", "recover", "duel", "aerial", "foul", "pressure",
                   "padj", "sliding")),
    ("Physical", ("sprint", "distance", "speed", "stamina", "physical", "intensity")),
)
OTHER = "Other"

# preset -> the categories whose metrics it collects (section 10). A preset only
# appears when enough matching metrics actually exist - never invented.
PRESET_CATEGORIES: dict[str, tuple[str, ...]] = {
    "Attacking": ("Shooting", "Chance Creation"),
    "Chance Creation": ("Chance Creation",),
    "Passing": ("Passing",),
    "Possession": ("Possession", "Progression"),
    "Defensive": ("Defensive",),
    "Physical": ("Physical",),
    "Goalkeeping": ("Goalkeeping",),
}
_PRESET_MIN = 3


def infer_category(name: str) -> str:
    key = str(name).lower()
    for category, tokens in _CATEGORY_RULES:
        if any(tok in key for tok in tokens):
            return category
    return OTHER


def display_name(source: str) -> str:
    """A clean label from the original header (multi-line headers collapsed)."""
    return " ".join(str(source).split())


# ---------------------------------------------------------------- data model
@dataclass(frozen=True, slots=True)
class MetricStat:
    source: str                       # original column header
    name: str                         # clean display name
    unit: str                         # PER_90 / PERCENT / RATE / RATIO / COUNT / ...
    category: str
    value_scale: str
    values: dict[str, float | None] = field(default_factory=dict)      # per player
    percentiles: dict[str, float | None] = field(default_factory=dict)
    ranks: dict[str, int | None] = field(default_factory=dict)
    count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    median: float | None = None
    mean: float | None = None

    def value(self, player: str) -> float | None:
        return self.values.get(player)

    def percentile(self, player: str) -> float | None:
        return self.percentiles.get(player)

    def rank(self, player: str) -> int | None:
        return self.ranks.get(player)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "name": self.name, "unit": self.unit,
            "category": self.category, "value_scale": self.value_scale,
            "values": dict(self.values), "percentiles": dict(self.percentiles),
            "ranks": dict(self.ranks), "count": self.count,
            "minimum": self.minimum, "maximum": self.maximum,
            "median": self.median, "mean": self.mean,
        }


@dataclass(frozen=True, slots=True)
class ScoutingView:
    dataset_id: str
    dataset_name: str
    players: tuple[str, ...]                 # selected players (1 = single mode)
    population: int                          # rows in the dataset
    value_scale: str
    metrics: tuple[MetricStat, ...] = ()
    dimensions: dict[str, dict[str, Any]] = field(default_factory=dict)  # player -> dims
    id_field: str = ""

    @property
    def primary(self) -> str:
        return self.players[0] if self.players else ""

    @property
    def is_comparison(self) -> bool:
        return len(self.players) > 1

    def metric(self, source: str) -> MetricStat | None:
        return next((m for m in self.metrics if m.source == source), None)

    def categories(self) -> list[str]:
        seen: list[str] = []
        for m in self.metrics:
            if m.category not in seen:
                seen.append(m.category)
        return seen

    def units(self) -> list[str]:
        seen: list[str] = []
        for m in self.metrics:
            if m.unit not in seen:
                seen.append(m.unit)
        return seen

    def sources(self) -> list[str]:
        return [m.source for m in self.metrics]

    def in_category(self, category: str) -> list[MetricStat]:
        return [m for m in self.metrics if m.category == category]


# ---------------------------------------------------------------- builder
def _numeric(frame: pd.DataFrame, source: str) -> pd.Series:
    return pd.to_numeric(frame[source], errors="coerce")


def _percentile_of(pop: np.ndarray, value: float) -> float:
    """Percentile of ``value`` within ``pop`` (mean rank, higher = better),
    0..100. Population-only; never mutates the source value."""
    if pop.size == 0:
        return 0.0
    below = float(np.count_nonzero(pop < value))
    equal = float(np.count_nonzero(pop == value))
    return round((below + 0.5 * equal) / pop.size * 100.0, 1)


def build_view(frame: pd.DataFrame, schema: dict[str, Any], players: list[str], *,
               dataset_id: str = "", dataset_name: str = "") -> ScoutingView:
    """Assemble a ``ScoutingView`` for the selected players from the scouting frame
    and its persisted schema. ``players`` are matched case-insensitively against the
    schema's id field. Deterministic and pure."""
    id_field = schema.get("id_field") or ""
    value_scale = schema.get("value_scale", SCALE_RAW)
    metric_defs = schema.get("metrics", []) or []
    if frame is None or id_field not in getattr(frame, "columns", []):
        return ScoutingView(dataset_id, dataset_name, tuple(players), 0, value_scale,
                            id_field=id_field)

    id_series = frame[id_field].astype(str).str.strip()
    id_lower = id_series.str.lower()
    # resolve each requested player to its first matching row index
    resolved: list[tuple[str, int]] = []
    for name in players:
        hits = frame.index[id_lower == str(name).lower().strip()]
        if len(hits):
            resolved.append((str(id_series.loc[hits[0]]), hits[0]))
    population = int(len(frame))

    dims_map: dict[str, dict[str, Any]] = {}
    dim_cols = schema.get("dimensions", {}) or {}
    for disp, idx in resolved:
        dims_map[disp] = {k: (None if pd.isna(frame.at[idx, v]) else frame.at[idx, v])
                          for k, v in dim_cols.items() if v in frame.columns}

    metrics: list[MetricStat] = []
    for md in metric_defs:
        src = md.get("source")
        if not src or src not in frame.columns:
            continue
        pop_series = _numeric(frame, src).dropna()
        pop = pop_series.to_numpy(dtype=float)
        vals: dict[str, float | None] = {}
        pcts: dict[str, float | None] = {}
        ranks: dict[str, int | None] = {}
        for disp, idx in resolved:
            raw = pd.to_numeric(pd.Series([frame.at[idx, src]]), errors="coerce").iloc[0]
            v = None if pd.isna(raw) else float(raw)
            vals[disp] = v
            if v is not None and pop.size >= _MIN_POP_RANK:
                pcts[disp] = _percentile_of(pop, v)
                ranks[disp] = int(np.count_nonzero(pop > v)) + 1
            else:
                pcts[disp] = None
                ranks[disp] = None
        metrics.append(MetricStat(
            source=str(src), name=display_name(src),
            unit=md.get("unit", ""), category=infer_category(src), value_scale=value_scale,
            values=vals, percentiles=pcts, ranks=ranks,
            count=int(pop.size),
            minimum=float(pop.min()) if pop.size else None,
            maximum=float(pop.max()) if pop.size else None,
            median=float(np.median(pop)) if pop.size else None,
            mean=float(pop.mean()) if pop.size else None))

    return ScoutingView(
        dataset_id=dataset_id, dataset_name=dataset_name,
        players=tuple(d for d, _ in resolved), population=population,
        value_scale=value_scale, metrics=tuple(metrics),
        dimensions=dims_map, id_field=id_field)


# ---------------------------------------------------------------- chart availability
def chart_availability(view: ScoutingView, *, selected: list[str] | None = None
                       ) -> dict[str, tuple[bool, str]]:
    """For each chart type: (available, reason-if-not). Encodes the analytical
    rules of section 4 - a chart is offered only when it makes sense."""
    n_players = len(view.players)
    n_metrics = len(view.metrics)
    pop = view.population
    n_sel = len(selected) if selected is not None else n_metrics
    out: dict[str, tuple[bool, str]] = {}

    def rule(ok: bool, reason: str) -> tuple[bool, str]:
        return (True, "") if ok else (False, reason)

    out["bar"] = rule(n_metrics >= 1, "needs at least one metric")
    out["percentile_bar"] = rule(
        n_metrics >= 1 and (view.value_scale == SCALE_NORMALIZED or pop >= _MIN_POP_RANK),
        "needs population data or a normalized dataset")
    out["ranking_bar"] = rule(pop >= _MIN_POP_RANK, "needs at least 2 players for a ranking")
    out["radar"] = rule(n_sel >= 3, "select at least 3 metrics")
    out["pizza"] = rule(
        n_sel >= 3 and (view.value_scale == SCALE_NORMALIZED or pop >= _MIN_POP_RANK),
        "select at least 3 metrics with percentile/normalized context")
    out["scatter"] = rule(n_metrics >= 2 and pop >= _MIN_POP_SCATTER,
                          "scatter requires two numeric metrics and enough players")
    out["histogram"] = rule(pop >= _MIN_POP_HIST,
                            f"histogram requires at least {_MIN_POP_HIST} players")
    out["box"] = rule(pop >= _MIN_POP_BOX, f"box plot requires at least {_MIN_POP_BOX} players")
    out["lollipop"] = rule(pop >= _MIN_POP_RANK, "needs at least 2 players for a ranking")
    out["comparison"] = rule(n_players >= 2, "select 2 or more players to compare")
    out["small_multiples"] = rule(n_metrics >= 1, "needs at least one metric")
    out["heatmap"] = rule(n_players >= 2 and n_metrics >= 2,
                          "needs 2+ players and 2+ metrics")
    return out


# ---------------------------------------------------------------- pizza semantics
def suggest_pizza_metrics(view: ScoutingView, n: int = 10) -> list[str]:
    """A balanced default of 6-12 metrics spread across categories (section 7).
    Deterministic (dataset order preserved within each category)."""
    n = max(6, min(n, 12))
    by_cat: dict[str, list[str]] = {}
    for m in view.metrics:
        by_cat.setdefault(m.category, []).append(m.source)
    picked: list[str] = []
    # round-robin across categories for a balanced profile
    cats = [c for c in view.categories()]
    while len(picked) < n and any(by_cat.get(c) for c in cats):
        for c in cats:
            bucket = by_cat.get(c)
            if bucket:
                picked.append(bucket.pop(0))
                if len(picked) >= n:
                    break
    return picked[:n]


def available_presets(view: ScoutingView) -> list[str]:
    """Presets that actually have >= _PRESET_MIN metrics in this dataset (section 10).
    'All-Round' is always available when there are enough metrics overall."""
    out: list[str] = []
    if len(view.metrics) >= _PRESET_MIN:
        out.append("All-Round")
    for preset, cats in PRESET_CATEGORIES.items():
        if len(preset_metrics(view, preset)) >= _PRESET_MIN:
            out.append(preset)
    return out


def preset_metrics(view: ScoutingView, preset: str) -> list[str]:
    if preset == "All-Round":
        return suggest_pizza_metrics(view, 10)
    cats = PRESET_CATEGORIES.get(preset, ())
    return [m.source for m in view.metrics if m.category in cats]


def pizza_values(view: ScoutingView, sources: list[str], player: str | None = None
                 ) -> dict[str, Any]:
    """Derive pizza slice values (0-100) for one player, honouring value_scale
    (section 9): a normalized dataset shows its values directly (x100); a raw
    dataset shows percentiles computed for visualization. Never re-normalizes.

    Returns {values, params, value_labels, categories, mode, note, available, reason}.
    """
    player = player or view.primary
    metrics = [m for s in sources if (m := view.metric(s)) is not None]
    if len(metrics) < 3:
        return {"available": False, "reason": "select at least 3 metrics",
                "values": [], "params": [], "value_labels": [], "categories": [],
                "mode": "", "note": ""}
    normalized = view.value_scale == SCALE_NORMALIZED
    if not normalized and view.population < _MIN_POP_RANK:
        return {"available": False,
                "reason": "raw metrics need population data for percentiles - add players "
                          "or use a normalized dataset",
                "values": [], "params": [], "value_labels": [], "categories": [],
                "mode": "", "note": ""}

    values: list[float] = []
    labels: list[str] = []
    params: list[str] = []
    cats: list[str] = []
    for m in metrics:
        v = m.value(player)
        if normalized:
            slice_v = 0.0 if v is None else float(np.clip(v * 100.0 if abs(v) <= 1.0 else v, 0, 100))
            label = "-" if v is None else (f"{v:.2f}" if abs(v) <= 1.0 else f"{v:.0f}")
        else:
            pct = m.percentile(player)
            slice_v = 0.0 if pct is None else float(pct)
            label = "-" if pct is None else f"{pct:.0f}"
        values.append(round(slice_v, 1))
        labels.append(label)
        params.append(m.name)
        cats.append(m.category)
    mode = "normalized" if normalized else "percentile"
    note = ("Values shown as normalized dataset values" if normalized
            else "Values shown as percentiles vs dataset")
    return {"available": True, "reason": "", "values": values, "params": params,
            "value_labels": labels, "categories": cats, "mode": mode, "note": note}


__all__ = [
    "CHART_TYPES", "CHART_LABELS", "SCALE_NORMALIZED", "SCALE_RAW", "OTHER",
    "PRESET_CATEGORIES", "infer_category", "display_name", "MetricStat",
    "ScoutingView", "build_view", "chart_availability", "suggest_pizza_metrics",
    "available_presets", "preset_metrics", "pizza_values",
]
