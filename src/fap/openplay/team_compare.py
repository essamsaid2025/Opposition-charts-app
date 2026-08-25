"""Team-comparison chart renderers for team-match-stats datasets.

The Open Play counterpart of ``fap.scouting.charts``: matplotlib figures driven
entirely by the existing FAP theme (``fap.themes.Theme`` via
``fap.scouting.charts.palette``) — no hardcoded colours, no second theme system.
These charts consume a ``TeamComparison`` built from a team-match-stats dataset's
persisted semantic schema (``fap.datahub.team_stats_schema.TeamStatsSchema``); they
NEVER touch event data (no x/y/event_type) and never run the Open Play event
engine. Each function returns a matplotlib ``Figure`` for the caller to export
(via the existing ``ExportEngine``) and then close — figures are never held in
state.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import matplotlib
matplotlib.use("Agg")                       # headless; never opens a window
import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Polygon

from fap.datahub.team_stats_schema import PERCENT, TeamStat, TeamStatsSchema
from fap.scouting.charts import palette


# ---------------------------------------------------------------- comparison model
@dataclass(frozen=True, slots=True)
class TeamComparison:
    """A selectable view over a team-match-stats table: the teams being compared,
    the ordered statistics (each with a value per team and a unit), and the
    category groups. Built from the persisted schema, so it is active-dataset
    independent and requires no re-inference."""
    dataset_name: str
    teams: tuple[str, ...]
    stats: tuple[TeamStat, ...]
    categories: tuple[str, ...]

    @staticmethod
    def from_schema(schema: TeamStatsSchema, *, dataset_name: str = "",
                    teams: Sequence[str] | None = None) -> "TeamComparison":
        chosen = [t for t in (teams or schema.teams) if t in schema.teams]
        if not chosen:
            chosen = list(schema.teams)
        return TeamComparison(
            dataset_name=dataset_name, teams=tuple(chosen),
            stats=tuple(schema.stats), categories=tuple(schema.categories))

    @staticmethod
    def from_document(doc: dict[str, Any], *, dataset_name: str = "",
                      teams: Sequence[str] | None = None) -> "TeamComparison":
        schema = TeamStatsSchema.from_dict(doc.get("team_stats_schema", {}) or {})
        return TeamComparison.from_schema(schema, dataset_name=dataset_name, teams=teams)

    # -- selection helpers -------------------------------------------------
    def stat(self, name: str, category: str | None = None) -> TeamStat | None:
        for s in self.stats:
            if s.name == name and (category is None or s.category == category):
                return s
        return None

    def in_category(self, category: str) -> list[TeamStat]:
        return [s for s in self.stats if s.category == category]

    def stat_labels(self) -> list[str]:
        """Unique statistic labels in order (category-qualified when a label repeats
        across categories, e.g. 'Shots in total')."""
        counts: dict[str, int] = {}
        for s in self.stats:
            counts[s.name] = counts.get(s.name, 0) + 1
        out: list[str] = []
        seen: set[str] = set()
        for s in self.stats:
            label = f"{s.name} ({s.category})" if counts[s.name] > 1 and s.category else s.name
            if label not in seen:
                out.append(label)
                seen.add(label)
        return out

    def resolve(self, label: str) -> TeamStat | None:
        """Resolve a label produced by ``stat_labels`` back to its TeamStat."""
        if label.endswith(")") and " (" in label:
            name, cat = label[:-1].rsplit(" (", 1)
            hit = self.stat(name, cat)
            if hit is not None:
                return hit
        return self.stat(label)


# ---------------------------------------------------------------- figure scaffolding
def _new_fig(pal: Any, figsize=(8.5, 6.0)) -> tuple[Figure, Any]:
    fig = Figure(figsize=figsize, dpi=150, facecolor=pal.bg)
    ax = fig.add_subplot(111)
    ax.set_facecolor(pal.bg)
    for spine in ax.spines.values():
        spine.set_color(pal.grid)
    ax.tick_params(colors=pal.muted, labelsize=8)
    return fig, ax


def _titles(fig: Figure, pal: Any, title: str, subtitle: str = "", footer: str = "") -> None:
    fam = {"fontfamily": pal.font} if pal.font else {}
    fig.text(0.06, 0.955, title, color=pal.text, fontsize=15, fontweight="bold",
             ha="left", va="top", **fam)
    if subtitle:
        fig.text(0.06, 0.905, subtitle, color=pal.muted, fontsize=9.5, ha="left",
                 va="top", **fam)
    if footer:
        fig.text(0.06, 0.02, footer, color=pal.muted, fontsize=7.5, ha="left",
                 va="bottom", **fam)


def _team_colors(pal: Any, teams: Sequence[str]) -> list[str]:
    wheel = [pal.accent, pal.warning, pal.success, pal.danger, pal.accent_2, pal.grey]
    return [wheel[i % len(wheel)] for i in range(len(teams))]


def _footer(cmp: TeamComparison) -> str:
    return (f"Dataset: {cmp.dataset_name or 'team stats'}  ·  "
            f"{len(cmp.teams)} teams  ·  {len(cmp.stats)} statistics")


def _empty(pal: Any, title: str, reason: str, cmp: TeamComparison) -> Figure:
    fig, ax = _new_fig(pal, (8.5, 5.0))
    ax.axis("off")
    _titles(fig, pal, title, reason, _footer(cmp))
    return fig


def _select(cmp: TeamComparison, labels: Sequence[str] | None, limit: int) -> list[TeamStat]:
    if labels:
        picked = [s for lbl in labels if (s := cmp.resolve(lbl)) is not None]
    else:
        picked = list(cmp.stats)
    return picked[:limit]


def _fmt(stat: TeamStat, team: str) -> str:
    raw = stat.raw.get(team, "")
    if raw:
        return raw
    v = stat.value(team)
    return "-" if v is None else (f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}")


# ---------------------------------------------------------------- charts
def comparison_bars(cmp: TeamComparison, labels: Sequence[str] | None, theme: Any) -> Figure:
    """Grouped horizontal bars: raw statistic values, one bar per team."""
    pal = palette(theme)
    stats = _select(cmp, labels, 14)
    teams = list(cmp.teams)
    if not stats or not teams:
        return _empty(pal, "Team comparison", "select at least one statistic", cmp)
    fig, ax = _new_fig(pal, (9.2, max(4.5, 0.62 * len(stats) + 2)))
    fig.subplots_adjust(left=0.40, right=0.94, top=0.82, bottom=0.10)
    colors = _team_colors(pal, teams)
    base = np.arange(len(stats))[::-1].astype(float)
    h = 0.8 / max(len(teams), 1)
    for i, team in enumerate(teams):
        vals = [(s.value(team) or 0.0) for s in stats]
        y = base + (i - (len(teams) - 1) / 2) * h
        ax.barh(y, vals, height=h, color=colors[i], edgecolor=pal.bg, label=team)
        for yi, s in zip(y, stats):
            ax.text((s.value(team) or 0.0), yi, "  " + _fmt(s, team), va="center",
                    ha="left", color=pal.text, fontsize=7.5)
    ax.set_yticks(base)
    ax.set_yticklabels([s.name for s in stats], color=pal.text, fontsize=8)
    ax.grid(axis="x", color=pal.grid, lw=0.6, alpha=0.5); ax.set_axisbelow(True)
    ax.legend(loc="lower right", facecolor=pal.panel, edgecolor=pal.grid,
              labelcolor=pal.text, fontsize=8)
    _titles(fig, pal, "Team comparison", "raw statistic values", _footer(cmp))
    return fig


def diverging_bars(cmp: TeamComparison, labels: Sequence[str] | None, theme: Any) -> Figure:
    """Back-to-back bars for exactly two teams — the classic match-stats layout:
    one team's values extend left, the other's right, each normalized to the row's
    max so counts and percents stay legible side by side."""
    pal = palette(theme)
    teams = list(cmp.teams)
    if len(teams) != 2:
        return _empty(pal, "Head to head", "pick exactly two teams", cmp)
    stats = _select(cmp, labels, 16)
    if not stats:
        return _empty(pal, "Head to head", "select at least one statistic", cmp)
    left_t, right_t = teams
    fig, ax = _new_fig(pal, (9.6, max(4.5, 0.55 * len(stats) + 2)))
    fig.subplots_adjust(left=0.28, right=0.72, top=0.82, bottom=0.08)
    colors = _team_colors(pal, teams)
    y = np.arange(len(stats))[::-1].astype(float)
    for yi, s in zip(y, stats):
        lv, rv = (s.value(left_t) or 0.0), (s.value(right_t) or 0.0)
        denom = max(abs(lv), abs(rv), 1e-9)
        ax.barh(yi, -lv / denom, height=0.66, color=colors[0], edgecolor=pal.bg)
        ax.barh(yi, rv / denom, height=0.66, color=colors[1], edgecolor=pal.bg)
        ax.text(-0.02, yi, _fmt(s, left_t), va="center", ha="right",
                color=pal.text, fontsize=8)
        ax.text(0.02, yi, _fmt(s, right_t), va="center", ha="left",
                color=pal.text, fontsize=8)
        ax.text(0, yi + 0.5, s.name, va="center", ha="center", color=pal.muted, fontsize=7.5)
    ax.axvline(0, color=pal.grid, lw=1.0)
    ax.set_xlim(-1.25, 1.25)
    ax.set_yticks([]); ax.set_xticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fam = {"fontfamily": pal.font} if pal.font else {}
    fig.text(0.40, 0.90, left_t, color=colors[0], fontsize=11, fontweight="bold",
             ha="right", va="center", **fam)
    fig.text(0.44, 0.90, "vs", color=pal.muted, fontsize=9, ha="center", va="center", **fam)
    fig.text(0.48, 0.90, right_t, color=colors[1], fontsize=11, fontweight="bold",
             ha="left", va="center", **fam)
    _titles(fig, pal, "Head to head", "", _footer(cmp))
    return fig


def share_bars(cmp: TeamComparison, labels: Sequence[str] | None, theme: Any) -> Figure:
    """100%-stacked horizontal bars: each team's share of every statistic. Reads at
    a glance who dominates each area; works for any number of teams."""
    pal = palette(theme)
    stats = _select(cmp, labels, 16)
    teams = list(cmp.teams)
    if not stats or not teams:
        return _empty(pal, "Statistic share", "select at least one statistic", cmp)
    fig, ax = _new_fig(pal, (9.4, max(4.5, 0.5 * len(stats) + 2)))
    fig.subplots_adjust(left=0.40, right=0.95, top=0.82, bottom=0.08)
    colors = _team_colors(pal, teams)
    y = np.arange(len(stats))[::-1].astype(float)
    for yi, s in zip(y, stats):
        vals = np.array([max(s.value(t) or 0.0, 0.0) for t in teams], dtype=float)
        total = vals.sum()
        shares = vals / total if total > 0 else np.zeros_like(vals)
        left = 0.0
        for i, team in enumerate(teams):
            w = shares[i] * 100.0
            ax.barh(yi, w, left=left, height=0.66, color=colors[i], edgecolor=pal.bg)
            if w >= 12:
                ax.text(left + w / 2, yi, f"{w:.0f}%", va="center", ha="center",
                        color=pal.bg, fontsize=7.5, fontweight="bold")
            left += w
    ax.set_xlim(0, 100)
    ax.set_yticks(y); ax.set_yticklabels([s.name for s in stats], color=pal.text, fontsize=8)
    ax.set_xticks([0, 25, 50, 75, 100])
    handles = [matplotlib.patches.Patch(color=colors[i], label=t) for i, t in enumerate(teams)]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.005),
              ncol=min(len(teams), 4), facecolor=pal.panel, edgecolor=pal.grid,
              labelcolor=pal.text, fontsize=8, framealpha=0.9)
    _titles(fig, pal, "Statistic share", "each team's share of the row total", _footer(cmp))
    return fig


def donut(cmp: TeamComparison, label: str | None, theme: Any) -> Figure:
    """A single statistic's split between the teams as a donut — ideal for
    possession / field tilt and other percentage rows."""
    pal = palette(theme)
    teams = list(cmp.teams)
    stat = cmp.resolve(label) if label else (cmp.stats[0] if cmp.stats else None)
    if stat is None or not teams:
        return _empty(pal, "Split", "select a statistic", cmp)
    vals = np.array([max(stat.value(t) or 0.0, 0.0) for t in teams], dtype=float)
    if vals.sum() <= 0:
        return _empty(pal, stat.name, "no values to split", cmp)
    pal_colors = _team_colors(pal, teams)
    fig = Figure(figsize=(7.6, 7.2), dpi=150, facecolor=pal.bg)
    ax = fig.add_subplot(111); ax.set_facecolor(pal.bg)
    wedges, _ = ax.pie(vals, colors=pal_colors, startangle=90, counterclock=False,
                       wedgeprops=dict(width=0.36, edgecolor=pal.bg, linewidth=2))
    shares = vals / vals.sum() * 100.0
    for w, team, sh in zip(wedges, teams, shares):
        ang = math.radians((w.theta1 + w.theta2) / 2)
        r = 0.82
        ax.text(r * math.cos(ang), r * math.sin(ang), f"{sh:.0f}%",
                ha="center", va="center", color=pal.bg, fontsize=12, fontweight="bold")
    leader = teams[int(np.argmax(vals))]
    fam = {"fontfamily": pal.font} if pal.font else {}
    ax.text(0, 0.08, stat.name, ha="center", va="center", color=pal.text,
            fontsize=12, fontweight="bold", **fam)
    ax.text(0, -0.1, leader, ha="center", va="center", color=pal.muted, fontsize=10, **fam)
    ax.set_aspect("equal")
    ax.legend(wedges, [f"{t}  {_fmt(stat, t)}" for t in teams], loc="lower center",
              ncol=min(len(teams), 3), facecolor=pal.panel, edgecolor=pal.grid,
              labelcolor=pal.text, fontsize=9, bbox_to_anchor=(0.5, -0.08))
    _titles(fig, pal, "Statistic split", stat.name, _footer(cmp))
    return fig


def radar(cmp: TeamComparison, labels: Sequence[str] | None, theme: Any) -> Figure:
    """Radar of team share per statistic (each axis normalized to the row total),
    one polygon per team — a compact whole-match fingerprint."""
    pal = palette(theme)
    stats = _select(cmp, labels, 12)
    teams = list(cmp.teams)
    if len(stats) < 3 or not teams:
        return _empty(pal, "Radar", "select at least 3 statistics", cmp)
    fig = Figure(figsize=(7.8, 8.0), dpi=150, facecolor=pal.bg)
    ax = fig.add_subplot(111); ax.set_facecolor(pal.bg)
    n = len(stats)
    angles = np.pi / 2 - np.arange(n) * 2 * np.pi / n
    for ring in (0.25, 0.5, 0.75, 1.0):
        ax.add_patch(Polygon([(ring * math.cos(a), ring * math.sin(a)) for a in angles],
                             closed=True, fill=False, edgecolor=pal.grid, lw=0.8,
                             alpha=0.6, zorder=1))
    for a, s in zip(angles, stats):
        ca, sa = math.cos(a), math.sin(a)
        ax.plot([0, ca], [0, sa], color=pal.grid, lw=0.8, alpha=0.5, zorder=1)
        ax.text(1.18 * ca, 1.18 * sa, s.name, color=pal.text, fontsize=7.5,
                ha="center" if abs(ca) < 0.3 else ("left" if ca > 0 else "right"),
                va="center" if abs(sa) < 0.3 else ("bottom" if sa > 0 else "top"))
    # per-stat share so counts and percents live on one 0..1 scale
    shares: list[np.ndarray] = []
    for s in stats:
        vals = np.array([max(s.value(t) or 0.0, 0.0) for t in teams], dtype=float)
        total = vals.sum()
        shares.append(vals / total if total > 0 else np.zeros_like(vals))
    colors = _team_colors(pal, teams)
    for ti, team in enumerate(teams):
        vals = [shares[si][ti] for si in range(n)]
        pts = [(v * math.cos(a), v * math.sin(a)) for v, a in zip(vals, angles)]
        loop = pts + pts[:1]
        col = colors[ti]
        ax.add_patch(Polygon(pts, closed=True, facecolor=col, edgecolor=col,
                             alpha=0.20, lw=2, zorder=2, label=team))
        ax.plot([p[0] for p in loop], [p[1] for p in loop], color=col, lw=2, zorder=3)
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], color=col, s=20,
                   zorder=4, edgecolors=pal.panel)
    ax.set_xlim(-1.4, 1.4); ax.set_ylim(-1.35, 1.45); ax.set_aspect("equal"); ax.axis("off")
    ax.legend(loc="upper right", facecolor=pal.panel, edgecolor=pal.grid,
              labelcolor=pal.text, fontsize=8)
    _titles(fig, pal, "Match fingerprint", "team share of each statistic", _footer(cmp))
    return fig


# dispatch used by the UI / tests
RENDERERS = {
    "comparison": lambda cmp, theme, opts: comparison_bars(cmp, opts.get("stats"), theme),
    "diverging": lambda cmp, theme, opts: diverging_bars(cmp, opts.get("stats"), theme),
    "share": lambda cmp, theme, opts: share_bars(cmp, opts.get("stats"), theme),
    "donut": lambda cmp, theme, opts: donut(cmp, opts.get("stat"), theme),
    "radar": lambda cmp, theme, opts: radar(cmp, opts.get("stats"), theme),
}

# stable metadata for the UI picker (id, label, needs)
CHART_TYPES = (
    {"id": "comparison", "label": "Comparison bars", "multi": True},
    {"id": "diverging", "label": "Head to head", "multi": True},
    {"id": "share", "label": "Statistic share", "multi": True},
    {"id": "donut", "label": "Single split (donut)", "multi": False},
    {"id": "radar", "label": "Match fingerprint (radar)", "multi": True},
)


def render(chart_type: str, cmp: TeamComparison, theme: Any,
           options: dict | None = None) -> Figure:
    """Render any supported chart to a matplotlib Figure. The CALLER exports it
    (via ExportEngine) and closes it — figures are never returned into state."""
    fn = RENDERERS.get(chart_type)
    if fn is None:
        raise ValueError(f"unknown chart type {chart_type!r}")
    return fn(cmp, theme, options or {})


__all__ = [
    "TeamComparison", "comparison_bars", "diverging_bars", "share_bars", "donut",
    "radar", "render", "RENDERERS", "CHART_TYPES",
]
