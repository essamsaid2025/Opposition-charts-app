"""Comparison charts (non-pitch): percentile radars, comparison bars and
rolling form trends, all through the chart builder.

These sit next to distributions.py and follow the same house style: theme
colors only (never hardcoded), football semantics borrowed from
fap.visuals.analysis, and graceful early-returns on empty/degenerate data.

The metric definitions mirror the Opponent Analysis engine's scouting cards
(app.compute_metrics / CARD_METRICS, surfaced by
fap.ui.builtin.opponent_analysis) - progressive passes/carries, final-third
and box entries, shots, crosses, defensive actions, pass accuracy - so a team
radar reads the same numbers a scout already sees on that page.
"""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np
import pandas as pd
from matplotlib.patches import Polygon

from fap.core.types import Control
from fap.visuals import analysis as A
from fap.visuals.maps._builders import chart

Metric = tuple[str, Callable[[pd.DataFrame], float]]

# too few entities makes a percentile rank meaningless; below these we fall
# back to scaling each metric against the peer maximum (and say so on the chart).
_MIN_PLAYERS_FOR_PCTILE = 5
_MIN_TEAMS_FOR_PCTILE = 4


# ------------------------------------------------------------------ metrics
def _pass_accuracy(d: pd.DataFrame) -> float:
    p = A.passes(d)
    return len(A.successful(p)) / len(p) * 100 if len(p) else 0.0


def _possession_pct(d: pd.DataFrame) -> float:
    teams = d["team"].astype(str).str.strip()
    teams = teams[teams.ne("")]
    return float(teams.value_counts(normalize=True).iloc[0] * 100) if len(teams) else 0.0


# Player profile - honest event-data proxies for the classic scouting radar
# (progressive passing, shot volume, dribbling, pressing, tackling, territory).
PLAYER_RADAR_METRICS: tuple[Metric, ...] = (
    ("Prog Passes", lambda d: float(len(A.progressive(A.passes(d))))),
    ("Shots", lambda d: float(len(A.shots(d)))),
    ("Dribbles", lambda d: float(len(A.carries(d)))),
    ("Pressures", lambda d: float(len(A.defensive(d, ("pressure",))))),
    ("Tackles", lambda d: float(len(A.defensive(d, ("tackle",))))),
    ("Final 3rd", lambda d: float(len(A.entries_into(d, A.FINAL_THIRD)))),
)

# Team profile - the Opponent Analysis scouting-card metrics.
TEAM_RADAR_METRICS: tuple[Metric, ...] = (
    ("Shots", lambda d: float(len(A.shots(d)))),
    ("Prog Passes", lambda d: float(len(A.progressive(A.passes(d))))),
    ("Final 3rd", lambda d: float(len(A.entries_into(d, A.FINAL_THIRD)))),
    ("Box Entries", lambda d: float(len(A.entries_into(d, A.PENALTY_AREA)))),
    ("Crosses", lambda d: float(len(A.crosses(d)))),
    ("Def Actions", lambda d: float(len(A.defensive(d)))),
    ("Pass Acc %", _pass_accuracy),
)

# Counting metrics for the head-to-head bars (normalized per-90 where minutes
# can be estimated).
COMPARISON_METRICS: tuple[Metric, ...] = (
    ("Prog Passes", lambda d: float(len(A.progressive(A.passes(d))))),
    ("Shots", lambda d: float(len(A.shots(d)))),
    ("Dribbles", lambda d: float(len(A.carries(d)))),
    ("Crosses", lambda d: float(len(A.crosses(d)))),
    ("Def Actions", lambda d: float(len(A.defensive(d)))),
)

# Per-match/sequence metrics for the form trend.
FORM_METRICS: dict[str, Callable[[pd.DataFrame], float]] = {
    "Shots": lambda g: float(len(A.shots(g))),
    "Progressive Passes": lambda g: float(len(A.progressive(A.passes(g)))),
    "Final Third Entries": lambda g: float(len(A.entries_into(g, A.FINAL_THIRD))),
    "Passes": lambda g: float(len(A.passes(g))),
    "Possession %": _possession_pct,
}

FORM_METRIC_CONTROL = Control("form_metric", "Form metric", "select",
                              default="Shots", options=tuple(FORM_METRICS))
FORM_WINDOW_CONTROL = Control("form_window", "Rolling window", "int_slider",
                              default=3, min_value=2, max_value=8,
                              help="Matches/sequences averaged for the trend line.")


# ------------------------------------------------------------------ helpers
def _palette(ctx) -> list[str]:
    c = ctx.theme.colors
    return [ctx.controls.get("primary_color") or c["accent"],
            ctx.controls.get("secondary_color") or c["accent_2"],
            c["success"]]


def _population_table(d: pd.DataFrame, col: str, metrics: Sequence[Metric],
                      min_events: int = 1) -> pd.DataFrame:
    """Per-entity metric table over every value of *col* with enough events.

    The last column ``_events`` carries each entity's volume so callers can
    pick who to plot while keeping the full population for percentiles.
    """
    sub = d[d[col].astype(str).str.strip().ne("")]
    if sub.empty:
        return pd.DataFrame()
    counts = sub[col].value_counts()
    keep = counts[counts >= min_events].index
    rows = {name: {label: fn(sub[sub[col] == name]) for label, fn in metrics}
            for name in keep}
    tbl = pd.DataFrame(rows).T.reindex(columns=[label for label, _ in metrics])
    if tbl.empty:
        return tbl
    tbl["_events"] = counts.reindex(tbl.index)
    return tbl


def _radial_values(table: pd.DataFrame, n_min: int) -> tuple[pd.DataFrame, str]:
    """Normalize a raw metric table to the 0-1 radius used by the radar.

    Percentile rank when the population is large enough, otherwise scaled to
    the peer maximum so the shape still renders instead of crashing."""
    if len(table) >= n_min:
        return table.rank(pct=True).clip(0, 1), "percentile rank vs dataset"
    mx = table.max().replace(0, np.nan)
    return (table / mx).fillna(0.0).clip(0, 1), "scaled to peer max (too few for percentiles)"


def _minutes_span(g: pd.DataFrame) -> float:
    m = pd.to_numeric(g["minute"], errors="coerce").dropna()
    return float(m.max() - m.min()) if len(m) else 0.0


# ------------------------------------------------------------------ radar
def _draw_radar(ax, ctx, labels: Sequence[str],
                entities: Sequence[tuple[str, np.ndarray, str]], note: str = "") -> None:
    """Draw a spider/radar chart on a cartesian axis (custom_artist gives us a
    normal Axes, not a polar one), so we place everything by hand."""
    n = len(labels)
    if n < 3 or not entities:
        return
    c = ctx.theme.colors
    angles = np.pi / 2 - np.arange(n) * 2 * np.pi / n            # start top, clockwise

    for ring in (0.25, 0.5, 0.75, 1.0):
        ax.add_patch(Polygon([(ring * np.cos(a), ring * np.sin(a)) for a in angles],
                             closed=True, fill=False, edgecolor=c["grid"],
                             lw=0.8, alpha=0.5, zorder=1))
    for a, label in zip(angles, labels):
        ca, sa = float(np.cos(a)), float(np.sin(a))
        ax.plot([0, ca], [0, sa], color=c["grid"], lw=0.8, alpha=0.5, zorder=1)
        ax.text(1.18 * ca, 1.18 * sa, label, color=c["text"],
                fontsize=ctx.style("label_size"),
                ha="center" if abs(ca) < 0.3 else ("left" if ca > 0 else "right"),
                va="center" if abs(sa) < 0.3 else ("bottom" if sa > 0 else "top"))

    for name, values, color in entities:
        pts = [(v * np.cos(a), v * np.sin(a)) for v, a in zip(values, angles)]
        loop = pts + pts[:1]
        ax.add_patch(Polygon(pts, closed=True, facecolor=color, edgecolor=color,
                             alpha=0.22, lw=2, zorder=2, label=name))
        ax.plot([p[0] for p in loop], [p[1] for p in loop], color=color, lw=2, zorder=3)
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], color=color,
                   s=22, zorder=4, edgecolors=c["panel"])

    ax.set_xlim(-1.4, 1.4)
    ax.set_ylim(-1.4, 1.4)
    ax.set_aspect("equal")
    ax.axis("off")
    if note:
        ax.text(0, -1.34, note, ha="center", va="top", color=c["muted"],
                fontsize=max(ctx.style("label_size") - 2, 6))
    if ctx.controls.get("legend", True) and len(entities) > 1:
        ax.legend(loc="upper right", facecolor=c["panel"], edgecolor=c["grid"],
                  labelcolor=c["text"], fontsize=ctx.style("legend_size"))


def _player_percentile_radar(ax, ctx) -> None:
    table = _population_table(ctx.df, "player", PLAYER_RADAR_METRICS, min_events=3)
    if table.empty:
        return
    events = table.pop("_events")
    radial, note = _radial_values(table, _MIN_PLAYERS_FOR_PCTILE)
    top = events.astype(float).idxmax()                          # most-involved player
    labels = [label for label, _ in PLAYER_RADAR_METRICS]
    _draw_radar(ax, ctx, labels,
                [(str(top), radial.loc[top, labels].to_numpy(dtype=float), _palette(ctx)[0])],
                note=f"{top} - {note} (n={len(table)})")


def _team_radar(ax, ctx) -> None:
    table = _population_table(ctx.df, "team", TEAM_RADAR_METRICS, min_events=1)
    if table.empty:
        return
    events = table.pop("_events")
    radial, note = _radial_values(table, _MIN_TEAMS_FOR_PCTILE)
    order = events.astype(float).sort_values(ascending=False).index[:3]   # scout up to 3 sides
    labels = [label for label, _ in TEAM_RADAR_METRICS]
    palette = _palette(ctx)
    entities = [(str(name), radial.loc[name, labels].to_numpy(dtype=float),
                 palette[i % len(palette)]) for i, name in enumerate(order)]
    _draw_radar(ax, ctx, labels, entities, note=note)


# ------------------------------------------------------------------ comparison bars
def _player_comparison_bars(ax, ctx) -> None:
    table = _population_table(ctx.df, "player", COMPARISON_METRICS, min_events=3)
    if table.empty:
        return
    c = ctx.theme.colors
    events = table.pop("_events")
    players = events.astype(float).sort_values(ascending=False).index[:3]   # top 2-3
    labels = [label for label, _ in COMPARISON_METRICS]

    # per-90 where a minute span can be estimated, raw counts otherwise
    per90 = {}
    for name in players:
        mins = _minutes_span(ctx.df[ctx.df["player"] == name])
        factor = 90.0 / mins if mins >= 20 else 1.0
        per90[name] = table.loc[name, labels].to_numpy(dtype=float) * factor
    normalized = bool(all(_minutes_span(ctx.df[ctx.df["player"] == n]) >= 20 for n in players))

    matrix = np.vstack([per90[n] for n in players])              # players x metrics
    col_max = np.where(matrix.max(axis=0) > 0, matrix.max(axis=0), 1.0)
    y = np.arange(len(labels))
    height = 0.8 / len(players)
    palette = _palette(ctx)
    for i, name in enumerate(players):
        offset = (i - (len(players) - 1) / 2) * height
        bar_len = matrix[i] / col_max                            # scale each metric to group max
        ax.barh(y + offset, bar_len, height=height * 0.92, color=palette[i % len(palette)],
                label=str(name))
        for j, val in enumerate(matrix[i]):
            ax.text(bar_len[j] + 0.01, y[j] + offset, f"{val:.1f}", va="center",
                    ha="left", color=c["muted"], fontsize=max(ctx.style("label_size") - 2, 6))

    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlim(0, 1.18)
    ax.set_xticks([])
    ax.set_xlabel(("Per 90" if normalized else "Totals") + " (bar scaled to group max)")
    if ctx.controls.get("legend", True):
        ax.legend(facecolor=c["panel"], edgecolor=c["grid"], labelcolor=c["text"],
                  fontsize=ctx.style("legend_size"))


# ------------------------------------------------------------------ rolling form
def _rolling_form(ax, ctx) -> None:
    metric_name = ctx.controls.get("form_metric", "Shots")
    fn = FORM_METRICS.get(metric_name, FORM_METRICS["Shots"])
    d = ctx.df
    matches = d["match_id"].astype(str).str.strip()
    col = "match_id" if matches[matches.ne("")].nunique() > 1 else "sequence_id"
    xlabel = "Match" if col == "match_id" else "Sequence"

    groups = [(k, g) for k, g in d[d[col].astype(str).str.strip().ne("")]
              .groupby(col, sort=False)]
    if not groups:
        return
    groups.sort(key=lambda kg: kg[1].index.min())               # chronological order
    values = [fn(g) for _, g in groups]
    if not values:
        return
    xs = np.arange(1, len(values) + 1)
    c = ctx.theme.colors
    ax.plot(xs, values, marker="o", lw=2.2,
            color=ctx.controls.get("primary_color") or c["accent"], label=metric_name)
    window = int(ctx.controls.get("form_window", 3))
    if len(values) >= window:
        roll = pd.Series(values).rolling(window, min_periods=1).mean()
        ax.plot(xs, roll, lw=2.0, ls="--",
                color=ctx.controls.get("fail_color") or c["danger"],
                label=f"{window}-game avg")
    ax.set_xlabel(f"{xlabel} (chronological)")
    ax.set_ylabel(metric_name)
    if col == "match_id" and len(xs) <= 20:
        ax.set_xticks(xs)
    if ctx.controls.get("legend", True):
        ax.legend(facecolor=c["panel"], edgecolor=c["grid"], labelcolor=c["text"],
                  fontsize=ctx.style("legend_size"))


# ------------------------------------------------------------------ registration
chart("player_percentile_radar", "Player Percentile Radar",
      lambda ctx, ax: _player_percentile_radar(ax, ctx), category="Comparison",
      description="Percentile profile of the most-involved player vs everyone else "
                  "in the dataset (falls back to peer-scaled when too few players).")
chart("player_comparison_bars", "Player Comparison Bars",
      lambda ctx, ax: _player_comparison_bars(ax, ctx), category="Comparison",
      description="Head-to-head bars for the top 2-3 players, per-90 where minutes "
                  "can be estimated, each metric scaled to the group max.")
chart("team_radar", "Team Radar (Opponent Scouting)",
      lambda ctx, ax: _team_radar(ax, ctx), category="Comparison",
      description="Team-level scouting radar reusing the Opponent Analysis card "
                  "metrics; overlays up to three teams in the dataset.")
chart("rolling_form_trend", "Rolling Form Trend",
      lambda ctx, ax: _rolling_form(ax, ctx), category="Comparison",
      description="A metric over consecutive matches (or sequences) with a rolling "
                  "average for spotting form.",
      extra_controls=(FORM_METRIC_CONTROL, FORM_WINDOW_CONTROL))
