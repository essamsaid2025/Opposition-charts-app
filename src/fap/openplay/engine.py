"""Open Play engine — the stable PUBLIC INTERFACE (Phase 16.0).

The Open Play visualization engine (chart registry, render functions, pitch/marker/
heatmap studios, export) lives in ``app.py``. Historically its only consumer was
``app.run_app`` — a monolith that also owned the layout. To let a second UI (the new
Open Play Studio) drive the *exact same* engine, this module defines a small, stable
public interface that both UIs consume:

* the **default visualization context** (``default_ctx``) — the single source of the
  ``ctx`` structure + default values every render function reads;
* the **Open Play filter definitions** (``OPEN_PLAY_FILTERS``) + a single ``apply_filters``
  used to turn selections into the filtered frame;
* an injected ``OpenPlayEngine`` holder carrying the live registry, render entrypoint,
  export helper, pitch/transform helpers and engine metadata.

This is an *architectural extraction, not a refactor*: it defines the interface and the
single source of the defaults/filters; it changes no analytics, no visualization, no
rendering, no calculation, no provider and no export behavior. ``app.py`` registers the
running engine here at startup (``register_engine``) and becomes the FIRST consumer
(``run_app`` builds its ctx from ``default_ctx`` and filters via ``apply_filters``); the
Studio is the SECOND consumer via ``get_engine`` — never importing ``app`` at runtime.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from fap.openplay.config import SUCCESS_WORDS

# Nested ctx groups are deep-merged (a consumer may override a subset of a group); every
# other key is a plain override. Keep this list in sync with the groups below.
_CTX_GROUPS = ("marker", "arrow", "labels", "legend", "heat", "colors", "aux")


def default_ctx(vt: dict, spec: Any, **overrides: Any) -> dict:
    """Return the full default render context for a given visualization theme (``vt``)
    and ``PitchSpec`` (``spec``), with any ``overrides`` applied (nested groups merged).

    This is the SINGLE SOURCE of the ctx structure and its default values. ``run_app``
    and the Studio both build their ctx from here, so both feed the render functions an
    identical contract — guaranteeing byte-identical output for identical selections.
    The literal defaults below mirror the engine's control defaults exactly (marker
    size 80, arrow width 1.6, legend position 'Bottom', heat preset 'All selected
    events', …); they are asserted against the engine in the Phase 16.0 tests.
    """
    base: dict = {
        "vt": vt, "spec": spec,
        "title": "", "show_title": True,
        "title_size": 20, "label_size": 11, "legend_size": 10,
        "respect_filter": False,
        "marker": {"shape": "Circle", "size": 80, "edge_width": 1.1, "edge_color": vt["line"],
                   "alpha": 0.85, "rotation": 0, "jitter": 0.0, "zorder": 6,
                   "shadow": False, "glow": False, "glow_color": vt["accent"]},
        "arrow": {"kind": "Straight", "width": 1.6, "head": 10, "curvature": 0.18,
                  "alpha": 0.72, "linecap": "round", "shadow": False, "glow": False,
                  "cmap": "viridis"},
        "labels": {"show": True, "show_players": False, "smart": True, "hide_overlapping": True,
                   "halo": True, "halo_color": vt["pitch"], "box": False, "leader_lines": True,
                   "size": 9, "offset": 1.6, "rotation": 0, "max_labels": 0},
        "legend": {"show": True, "position": "Bottom", "orientation": "Horizontal",
                   "frame": True, "title": "", "renames": "", "hide": "", "order": ""},
        "heat": {"type": "Gaussian KDE", "preset": "All selected events", "cmap": "Greens",
                 "alpha": 0.65, "bandwidth": 3.0, "levels": 10, "bins": 13, "gridsize": 22,
                 "cell_size": 10, "interpolation": "bilinear", "normalization": "Count",
                 "threshold": 0, "percentile_scale": False, "log_scale": False,
                 "cell_labels": False},
        "colors": {"arrow": vt["accent"], "unsuccess": vt["danger"], "start": vt["accent"],
                   "end": vt["accent2"], "shot": vt["panel"], "goal": vt["danger"],
                   "zone": vt["warning"], "bar": vt["accent"], "line": vt["accent"],
                   "trend": vt["danger"], "carry": vt["grey"], "cross": vt["accent2"]},
        "aux": {"df_all": None, "top_n": 10, "zone_mode": "Pitch Thirds",
                "start_end_event": "pass", "timeline_focus": "All", "trend_metric": "All Events",
                "sequence_mode": "Specific sequence", "sequence_id": "",
                "show_sequence_numbers": True, "line_width": 2.4, "dashboard_layout": None},
    }
    for key, value in overrides.items():
        if key in _CTX_GROUPS and isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


# --------------------------------------------------------------- Open Play filters
# The single description of the Open Play filter surface. The Studio renders widgets
# from this spec; ``apply_filters`` (below) is the single apply both UIs use. Option
# sources are column names on the derived frame; "kind" drives the widget type.
OPEN_PLAY_FILTERS: tuple[dict[str, Any], ...] = (
    {"id": "team", "label": "Team", "kind": "select", "column": "team"},
    {"id": "opponent", "label": "Opponent", "kind": "select", "column": "opponent"},
    {"id": "match", "label": "Match", "kind": "select", "column": "match_id"},
    {"id": "event_types", "label": "Event type", "kind": "multiselect", "column": "event_type"},
    {"id": "phases", "label": "Phase", "kind": "multiselect", "column": "phase"},
    {"id": "players", "label": "Player", "kind": "multiselect", "column": "player"},
    {"id": "minute_range", "label": "Minute range", "kind": "range", "column": "time_min"},
    {"id": "only_success", "label": "Only successful outcome", "kind": "bool", "column": "outcome"},
)


def apply_filters(df, selections: dict) -> Any:
    """Apply Open Play selections to a derived frame and return the filtered frame.

    This is the SINGLE apply both ``run_app`` and the Studio call — the exact logic that
    previously lived inline in ``run_app`` (unchanged), so the filtered frame is
    identical. ``selections`` keys mirror ``OPEN_PLAY_FILTERS`` ids; missing keys mean
    "no constraint" ("All" / empty / full range / off)."""
    f = df.copy()
    team = selections.get("team", "All")
    opp = selections.get("opponent", "All")
    match = selections.get("match", "All")
    events = selections.get("event_types") or []
    phases = selections.get("phases") or []
    players = selections.get("players") or []
    minute_range = selections.get("minute_range", (0, 120))
    only_success = bool(selections.get("only_success", False))

    if team != "All":
        f = f[f["team"] == team]
    if opp != "All":
        f = f[f["opponent"] == opp]
    if match != "All":
        f = f[f["match_id"].astype(str) == match]
    if events:
        f = f[f["event_type"].str.lower().isin(events)]
    if phases:
        f = f[f["phase"].str.lower().isin(phases)]
    if players:
        f = f[f["player"].isin(players)]
    f = f[(f["time_min"] >= minute_range[0]) & (f["time_min"] <= minute_range[1])]
    if only_success:
        f = f[f["outcome"].str.lower().isin(SUCCESS_WORDS)]
    return f


# --------------------------------------------------------------- engine holder
@dataclass(frozen=True)
class OpenPlayEngine:
    """Injected handle to the running Open Play engine. ``app.py`` fills this at startup
    with references to its existing objects; consumers (run_app, Studio) read it. Holds
    NO copies of analytics — only references + metadata for building UIs."""
    version: str
    viz_registry: dict                       # name -> {"category", "render", "uses_pitch"}
    render: Callable[[str, Any, dict], Any]  # (viz_name, frame, ctx) -> matplotlib Figure
    export: Callable[..., bytes]             # (fig, fmt, dpi, transparent) -> bytes
    default_ctx: Callable[..., dict]         # == default_ctx above
    apply_filters: Callable[[Any, dict], Any]  # == apply_filters above
    filters: Sequence[dict]                  # == OPEN_PLAY_FILTERS
    pitch_spec_cls: Any                      # app.PitchSpec
    apply_pitch_transforms: Callable         # app.apply_pitch_transforms
    build_insights: Callable                 # app.build_insights
    metadata: dict = field(default_factory=dict)  # themes, marker_shapes, heat_*, legend_positions, pitch_views, categories, …

    def categories(self) -> list[str]:
        return sorted({str(v.get("category", "")) for v in self.viz_registry.values() if v.get("category")})

    def viz_names(self, category: str | None = None) -> list[str]:
        return [n for n, v in self.viz_registry.items()
                if category in (None, "All") or v.get("category") == category]


_ENGINE: OpenPlayEngine | None = None


def register_engine(engine: OpenPlayEngine) -> None:
    """Publish the running engine (called once by app.py at startup). Idempotent."""
    global _ENGINE
    _ENGINE = engine


def get_engine() -> OpenPlayEngine | None:
    """Return the injected engine, or ``None`` if it has not been registered yet.
    Consumers must handle ``None`` with a professional empty state — never import app."""
    return _ENGINE


def engine_available() -> bool:
    return _ENGINE is not None
