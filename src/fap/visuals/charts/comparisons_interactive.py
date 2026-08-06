"""OPTIONAL interactive (Plotly) equivalents of the four Comparison charts.

This module is purely additive: it registers NO visualization, touches no
existing render/export/report path, and is only ever called from the opt-in
"Interactive preview (Plotly)" toggle in the Players/Scouting workspace. The
static matplotlib chart remains the single source used for export and report
assignment.

To guarantee the numbers are identical to the static version, every builder
reuses the EXACT pure-data helpers from ``comparisons.py`` (``_population_table``,
``_radial_values``, the metric tables, ``_minutes_span``, ``_palette``) - only
the rendering technology differs. Colours come from the same
``ctx.theme.colors`` dict the matplotlib charts read, so the interactive view
matches the app's theme rather than Plotly's generic defaults.

``plotly`` is imported lazily inside the builders, so importing this module
(e.g. during plugin discovery) never requires Plotly and never affects the
default, Plotly-free code path.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

from fap.visuals.charts import comparisons as CMP
from fap.visuals.charts.comparisons import (  # reused, NOT reimplemented
    COMPARISON_METRICS, FORM_METRICS, PLAYER_RADAR_METRICS, TEAM_RADAR_METRICS,
    _minutes_span, _palette, _population_table, _radial_values,
)

# the only visualizations this optional view supports
INTERACTIVE_CHART_IDS: tuple[str, ...] = (
    "player_percentile_radar", "player_comparison_bars",
    "team_radar", "rolling_form_trend",
)


def _go():
    """Lazy Plotly import: keeps module import (and plugin discovery) Plotly-free."""
    import plotly.graph_objects as go
    return go


# ------------------------------------------------------------------ theming
def _rgba(color: str, alpha: float) -> str:
    """Theme hex -> rgba() string for translucent fills; pass through on failure."""
    try:
        h = str(color).lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    except Exception:
        return color


def _base_layout(fig, ctx, note: str = "") -> None:
    c = ctx.theme.colors
    fig.update_layout(
        paper_bgcolor=c["bg"], plot_bgcolor=c["panel"],
        font=dict(color=c["text"]),
        legend=dict(bgcolor=c["panel"], bordercolor=c["grid"], font=dict(color=c["text"])),
        margin=dict(l=50, r=25, t=30, b=55))
    if note:
        fig.add_annotation(text=note, xref="paper", yref="paper", x=0.5, y=-0.16,
                           showarrow=False, font=dict(color=c["muted"], size=11))


def _empty_fig(ctx, msg: str = "No data for this selection"):
    fig = _go().Figure()
    _base_layout(fig, ctx)
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(color=ctx.theme.colors["muted"], size=14))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return fig


# ------------------------------------------------------------------ radar
def _radar_fig(ctx, labels: Sequence[str],
               entities: Sequence[tuple[str, np.ndarray, str]], note: str = ""):
    if len(labels) < 3 or not entities:
        return _empty_fig(ctx, "Not enough metrics for a radar")
    go = _go()
    c = ctx.theme.colors
    theta = list(labels) + [labels[0]]                       # close the loop
    fig = go.Figure()
    for name, values, color in entities:
        r = list(np.asarray(values, dtype=float)) + [float(values[0])]
        fig.add_trace(go.Scatterpolar(
            r=r, theta=theta, fill="toself", name=str(name),
            line=dict(color=color, width=2), fillcolor=_rgba(color, 0.25),
            hovertemplate="%{theta}: %{r:.2f}<extra>" + str(name) + "</extra>"))
    _base_layout(fig, ctx, note)
    fig.update_layout(
        showlegend=len(entities) > 1,
        polar=dict(
            bgcolor=c["panel"],
            radialaxis=dict(range=[0, 1], showticklabels=False, gridcolor=c["grid"],
                            linecolor=c["grid"]),
            angularaxis=dict(gridcolor=c["grid"], linecolor=c["grid"], color=c["text"])))
    return fig


def build_player_percentile_radar(ctx):
    table = _population_table(ctx.df, "player", PLAYER_RADAR_METRICS, min_events=3)
    if table.empty:
        return _empty_fig(ctx, "No player data")
    events = table.pop("_events")
    radial, note = _radial_values(table, CMP._MIN_PLAYERS_FOR_PCTILE)
    top = events.astype(float).idxmax()                      # most-involved player
    labels = [label for label, _ in PLAYER_RADAR_METRICS]
    values = radial.loc[top, labels].to_numpy(dtype=float)
    return _radar_fig(ctx, labels, [(str(top), values, _palette(ctx)[0])],
                      note=f"{top} - {note} (n={len(table)})")


def build_team_radar(ctx):
    table = _population_table(ctx.df, "team", TEAM_RADAR_METRICS, min_events=1)
    if table.empty:
        return _empty_fig(ctx, "No team data")
    events = table.pop("_events")
    radial, note = _radial_values(table, CMP._MIN_TEAMS_FOR_PCTILE)
    order = events.astype(float).sort_values(ascending=False).index[:3]
    labels = [label for label, _ in TEAM_RADAR_METRICS]
    palette = _palette(ctx)
    entities = [(str(name), radial.loc[name, labels].to_numpy(dtype=float),
                 palette[i % len(palette)]) for i, name in enumerate(order)]
    return _radar_fig(ctx, labels, entities, note=note)


# ------------------------------------------------------------------ comparison bars
def build_player_comparison_bars(ctx):
    table = _population_table(ctx.df, "player", COMPARISON_METRICS, min_events=3)
    if table.empty:
        return _empty_fig(ctx, "No player data")
    go = _go()
    events = table.pop("_events")
    players = events.astype(float).sort_values(ascending=False).index[:3]
    labels = [label for label, _ in COMPARISON_METRICS]

    # identical per-90 computation to the static chart
    per90 = {}
    for name in players:
        mins = _minutes_span(ctx.df[ctx.df["player"] == name])
        factor = 90.0 / mins if mins >= 20 else 1.0
        per90[name] = table.loc[name, labels].to_numpy(dtype=float) * factor
    normalized = bool(all(_minutes_span(ctx.df[ctx.df["player"] == n]) >= 20 for n in players))
    matrix = np.vstack([per90[n] for n in players])          # players x metrics
    col_max = np.where(matrix.max(axis=0) > 0, matrix.max(axis=0), 1.0)

    palette = _palette(ctx)
    c = ctx.theme.colors
    fig = go.Figure()
    for i, name in enumerate(players):
        bar_len = matrix[i] / col_max                        # bar scaled to group max
        fig.add_trace(go.Bar(
            y=labels, x=bar_len, orientation="h", name=str(name),
            marker_color=palette[i % len(palette)],
            text=[f"{v:.1f}" for v in matrix[i]], textposition="outside",
            textfont=dict(color=c["text"]),
            customdata=matrix[i],
            hovertemplate="%{y}: %{customdata:.1f}<extra>" + str(name) + "</extra>"))
    _base_layout(fig, ctx)
    xlabel = ("Per 90" if normalized else "Totals") + " (bar scaled to group max)"
    fig.update_layout(barmode="group",
                      xaxis=dict(title=xlabel, range=[0, 1.25], showticklabels=False,
                                 gridcolor=c["grid"], zerolinecolor=c["grid"]),
                      yaxis=dict(autorange="reversed", color=c["text"]))
    return fig


# ------------------------------------------------------------------ rolling form
def build_rolling_form_trend(ctx):
    metric_name = ctx.controls.get("form_metric", "Shots")
    fn = FORM_METRICS.get(metric_name, FORM_METRICS["Shots"])
    d = ctx.df
    matches = d["match_id"].astype(str).str.strip()
    col = "match_id" if matches[matches.ne("")].nunique() > 1 else "sequence_id"
    xlabel = "Match" if col == "match_id" else "Sequence"

    groups = [(k, g) for k, g in d[d[col].astype(str).str.strip().ne("")]
              .groupby(col, sort=False)]
    if not groups:
        return _empty_fig(ctx, "No matches / sequences to trend")
    groups.sort(key=lambda kg: kg[1].index.min())            # chronological order
    values = [fn(g) for _, g in groups]
    if not values:
        return _empty_fig(ctx, "No matches / sequences to trend")

    go = _go()
    c = ctx.theme.colors
    xs = list(range(1, len(values) + 1))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs, y=values, mode="lines+markers", name=metric_name,
        line=dict(color=ctx.controls.get("primary_color") or c["accent"], width=2.4)))
    window = int(ctx.controls.get("form_window", 3))
    if len(values) >= window:
        roll = pd.Series(values).rolling(window, min_periods=1).mean().tolist()
        fig.add_trace(go.Scatter(
            x=xs, y=roll, mode="lines", name=f"{window}-game avg",
            line=dict(color=ctx.controls.get("fail_color") or c["danger"], width=2, dash="dash")))
    _base_layout(fig, ctx)
    fig.update_layout(
        xaxis=dict(title=f"{xlabel} (chronological)", gridcolor=c["grid"],
                   zerolinecolor=c["grid"], color=c["text"]),
        yaxis=dict(title=metric_name, gridcolor=c["grid"], zerolinecolor=c["grid"],
                   color=c["text"]))
    return fig


# viz id -> Plotly builder
BUILDERS: dict[str, Any] = {
    "player_percentile_radar": build_player_percentile_radar,
    "player_comparison_bars": build_player_comparison_bars,
    "team_radar": build_team_radar,
    "rolling_form_trend": build_rolling_form_trend,
}


def build(viz_id: str, ctx):
    """Return a Plotly Figure for one of the four comparison charts, or None."""
    builder = BUILDERS.get(viz_id)
    return builder(ctx) if builder is not None else None
