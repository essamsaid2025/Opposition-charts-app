"""Player-scouting chart renderers - matplotlib + mplsoccer, driven entirely by the
existing FAP theme (``fap.themes.Theme``). No hardcoded colors, no second theme
system; every colour comes from ``theme.colors`` so a chart responds to the same
themes the rest of the platform uses (opta_light/dark, athletic, hudl, …).

Each function returns a matplotlib ``Figure`` for the caller to export (via the
existing ``ExportEngine``) and then close - figures are never held in state. The
renderers read a ``ScoutingView`` from ``fap.scouting.viz`` and never touch event
data. The pizza uses mplsoccer's ``PyPizza`` (the project's football-analytics
visual language), the first and only pizza implementation.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

import matplotlib
matplotlib.use("Agg")                       # headless; never opens a window
import numpy as np
from matplotlib.figure import Figure
from matplotlib.patches import Polygon

from fap.scouting import viz
from fap.scouting.viz import ScoutingView

# the order categories are coloured in (stable, so a metric keeps its colour)
_CATEGORY_ORDER = ("Shooting", "Chance Creation", "Passing", "Progression",
                   "Possession", "Defensive", "Physical", "Goalkeeping", viz.OTHER)


class Palette:
    """A theme's colours, resolved once, with sensible fallbacks."""
    __slots__ = ("bg", "panel", "text", "muted", "grid", "lines", "accent",
                 "accent_2", "bar", "danger", "warning", "success", "grey", "font")

    def __init__(self, theme: Any) -> None:
        c = getattr(theme, "colors", {}) or {}
        g = lambda k, d: c.get(k, d)                                   # noqa: E731
        self.bg = g("bg", "#0E1117")
        self.panel = g("panel", "#141A22")
        self.text = g("text", "#FFFFFF")
        self.muted = g("muted", "#A0A7B4")
        self.grid = g("grid", "#2A3240")
        self.lines = g("lines", "#E6E6E6")
        self.accent = g("accent", "#00C2FF")
        self.accent_2 = g("accent_2", "#60A5FA")
        self.bar = g("bar", self.accent)
        self.danger = g("danger", "#FF5A5F")
        self.warning = g("warning", "#FACC15")
        self.success = g("success", "#22C55E")
        self.grey = g("grey", "#A0A7B4")
        fonts = getattr(theme, "fonts", {}) or {}
        self.font = fonts.get("body") or fonts.get("family") or fonts.get("base") or None

    def category_colors(self, categories: Sequence[str]) -> list[str]:
        wheel = [self.accent, self.accent_2, self.success, self.warning,
                 self.danger, self.grey, self.lines, self.muted, self.text]
        idx = {cat: i for i, cat in enumerate(_CATEGORY_ORDER)}
        return [wheel[idx.get(cat, len(_CATEGORY_ORDER) - 1) % len(wheel)] for cat in categories]


def palette(theme: Any) -> Palette:
    return Palette(theme)


# ---------------------------------------------------------------- figure scaffolding
def _new_fig(pal: Palette, figsize=(8.5, 6.0)) -> tuple[Figure, Any]:
    fig = Figure(figsize=figsize, dpi=150, facecolor=pal.bg)
    ax = fig.add_subplot(111)
    ax.set_facecolor(pal.bg)
    for spine in ax.spines.values():
        spine.set_color(pal.grid)
    ax.tick_params(colors=pal.muted, labelsize=8)
    if pal.font:
        for item in ([ax.title, ax.xaxis.label, ax.yaxis.label]):
            item.set_fontfamily(pal.font)
    return fig, ax


def _titles(fig: Figure, pal: Palette, title: str, subtitle: str = "",
            footer: str = "") -> None:
    fam = {"fontfamily": pal.font} if pal.font else {}
    fig.text(0.06, 0.955, title, color=pal.text, fontsize=15, fontweight="bold",
             ha="left", va="top", **fam)
    if subtitle:
        fig.text(0.06, 0.905, subtitle, color=pal.muted, fontsize=9.5, ha="left",
                 va="top", **fam)
    if footer:
        fig.text(0.06, 0.02, footer, color=pal.muted, fontsize=7.5, ha="left",
                 va="bottom", **fam)


def _score(view: ScoutingView, m, player: str) -> float:
    """A 0-100 comparable score honouring value_scale: normalized values shown
    directly (x100), raw values shown as percentile. Never re-normalizes."""
    if view.value_scale == viz.SCALE_NORMALIZED:
        v = m.value(player)
        if v is None:
            return 0.0
        return float(np.clip(v * 100.0 if abs(v) <= 1.0 else v, 0, 100))
    pct = m.percentile(player)
    return 0.0 if pct is None else float(pct)


def _score_label(view: ScoutingView) -> str:
    return ("normalized value" if view.value_scale == viz.SCALE_NORMALIZED
            else "percentile vs dataset")


def _sources_or_all(view: ScoutingView, sources: list[str] | None) -> list:
    if sources:
        return [m for s in sources if (m := view.metric(s)) is not None]
    return list(view.metrics)


def _player_line(view: ScoutingView) -> str:
    dims = view.dimensions.get(view.primary, {})
    bits = [str(dims[k]) for k in ("team", "position", "league") if dims.get(k)]
    return "  ·  ".join([view.primary] + bits)


def _footer(view: ScoutingView) -> str:
    return f"Dataset: {view.dataset_name or 'player scouting'}  ·  {view.population} players"


# ---------------------------------------------------------------- charts
def bar_chart(view: ScoutingView, sources: list[str], theme: Any) -> Figure:
    """Raw metric values for the player (source values preserved)."""
    pal = palette(theme)
    metrics = _sources_or_all(view, sources)[:16]
    fig, ax = _new_fig(pal, (8.5, max(4.0, 0.42 * len(metrics) + 2)))
    fig.subplots_adjust(left=0.42, right=0.96, top=0.82, bottom=0.12)
    names = [m.name for m in metrics]
    vals = [(m.value(view.primary) or 0.0) for m in metrics]
    cols = pal.category_colors([m.category for m in metrics])
    y = np.arange(len(metrics))[::-1]
    ax.barh(y, vals, color=cols, edgecolor=pal.bg, height=0.68)
    for yi, v in zip(y, vals):
        ax.text(v, yi, f"  {v:.2f}", va="center", ha="left", color=pal.text, fontsize=8)
    ax.set_yticks(y); ax.set_yticklabels(names, color=pal.text, fontsize=8)
    ax.grid(axis="x", color=pal.grid, lw=0.6, alpha=0.5)
    ax.set_axisbelow(True)
    _titles(fig, pal, "Metric values", _player_line(view), _footer(view))
    return fig


def percentile_bar(view: ScoutingView, sources: list[str], theme: Any) -> Figure:
    """Horizontal 0-100 bars (normalized value or percentile)."""
    pal = palette(theme)
    metrics = _sources_or_all(view, sources)[:16]
    fig, ax = _new_fig(pal, (8.5, max(4.0, 0.42 * len(metrics) + 2)))
    fig.subplots_adjust(left=0.42, right=0.96, top=0.82, bottom=0.12)
    names = [m.name for m in metrics]
    scores = [_score(view, m, view.primary) for m in metrics]
    cols = pal.category_colors([m.category for m in metrics])
    y = np.arange(len(metrics))[::-1]
    ax.barh(y, scores, color=cols, edgecolor=pal.bg, height=0.68)
    ax.axvline(50, color=pal.muted, lw=0.8, ls="--", alpha=0.6)
    for yi, s in zip(y, scores):
        ax.text(s, yi, f"  {s:.0f}", va="center", ha="left", color=pal.text, fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_yticks(y); ax.set_yticklabels(names, color=pal.text, fontsize=8)
    ax.grid(axis="x", color=pal.grid, lw=0.6, alpha=0.5); ax.set_axisbelow(True)
    _titles(fig, pal, "Percentile profile", f"{_player_line(view)}  ·  {_score_label(view)}",
            _footer(view))
    return fig


def ranking_bar(view: ScoutingView, source: str, theme: Any, *, top: int = 12) -> Figure:
    """Where the player ranks within one metric across the dataset."""
    pal = palette(theme)
    m = view.metric(source) or (view.metrics[0] if view.metrics else None)
    fig, ax = _new_fig(pal, (8.5, 6.2))
    fig.subplots_adjust(left=0.30, right=0.96, top=0.82, bottom=0.12)
    if m is None:
        _titles(fig, pal, "Ranking", "no metric", _footer(view))
        return fig
    v = m.value(view.primary)
    rank = m.rank(view.primary)
    ax.axis("off")
    ax.text(0.5, 0.62, "" if rank is None else f"#{rank}", ha="center", va="center",
            color=pal.accent, fontsize=64, fontweight="bold", transform=ax.transAxes)
    ax.text(0.5, 0.40, f"of {m.count} players", ha="center", va="center",
            color=pal.muted, fontsize=13, transform=ax.transAxes)
    ax.text(0.5, 0.26, f"{m.name}: {('-' if v is None else f'{v:.2f}')}"
            f"   (median {('-' if m.median is None else f'{m.median:.2f}')})",
            ha="center", va="center", color=pal.text, fontsize=11, transform=ax.transAxes)
    _titles(fig, pal, "Ranking", _player_line(view), _footer(view))
    return fig


def radar_chart(view: ScoutingView, sources: list[str], theme: Any) -> Figure:
    """Multi-metric radar (0-1 normalized/percentile), one polygon per player."""
    pal = palette(theme)
    metrics = _sources_or_all(view, sources)[:12]
    fig = Figure(figsize=(7.6, 7.8), dpi=150, facecolor=pal.bg)
    ax = fig.add_subplot(111); ax.set_facecolor(pal.bg)
    labels = [m.name for m in metrics]
    n = len(labels)
    if n < 3:
        ax.axis("off"); _titles(fig, pal, "Radar", "select at least 3 metrics", _footer(view))
        return fig
    angles = np.pi / 2 - np.arange(n) * 2 * np.pi / n
    for ring in (0.25, 0.5, 0.75, 1.0):
        ax.add_patch(Polygon([(ring * math.cos(a), ring * math.sin(a)) for a in angles],
                             closed=True, fill=False, edgecolor=pal.grid, lw=0.8,
                             alpha=0.6, zorder=1))
    for a, label in zip(angles, labels):
        ca, sa = math.cos(a), math.sin(a)
        ax.plot([0, ca], [0, sa], color=pal.grid, lw=0.8, alpha=0.5, zorder=1)
        ax.text(1.2 * ca, 1.2 * sa, label, color=pal.text, fontsize=8,
                ha="center" if abs(ca) < 0.3 else ("left" if ca > 0 else "right"),
                va="center" if abs(sa) < 0.3 else ("bottom" if sa > 0 else "top"))
    colors = [pal.accent, pal.warning, pal.success, pal.danger]
    for i, player in enumerate(view.players):
        vals = [_score(view, m, player) / 100.0 for m in metrics]
        pts = [(v * math.cos(a), v * math.sin(a)) for v, a in zip(vals, angles)]
        loop = pts + pts[:1]
        col = colors[i % len(colors)]
        ax.add_patch(Polygon(pts, closed=True, facecolor=col, edgecolor=col,
                             alpha=0.22, lw=2, zorder=2, label=player))
        ax.plot([p[0] for p in loop], [p[1] for p in loop], color=col, lw=2, zorder=3)
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], color=col, s=22,
                   zorder=4, edgecolors=pal.panel)
    ax.set_xlim(-1.45, 1.45); ax.set_ylim(-1.4, 1.5); ax.set_aspect("equal"); ax.axis("off")
    if view.is_comparison:
        ax.legend(loc="upper right", facecolor=pal.panel, edgecolor=pal.grid,
                  labelcolor=pal.text, fontsize=8)
    _titles(fig, pal, "Radar", f"{_player_line(view)}  ·  {_score_label(view)}", _footer(view))
    return fig


def pizza_chart(view: ScoutingView, sources: list[str], theme: Any, *,
                player: str | None = None) -> Figure:
    """mplsoccer PyPizza - the project's football pizza. Slice values honour
    value_scale (normalized value or percentile); colours come from the theme."""
    from mplsoccer import PyPizza
    pal = palette(theme)
    player = player or view.primary
    data = viz.pizza_values(view, sources, player)
    if not data["available"]:
        fig, ax = _new_fig(pal, (7.6, 7.8)); ax.axis("off")
        _titles(fig, pal, "Pizza", data["reason"], _footer(view))
        return fig
    params = data["params"]
    values = data["values"]
    slice_colors = pal.category_colors(data["categories"])
    baker = PyPizza(
        params=params, background_color=pal.bg, straight_line_color=pal.grid,
        last_circle_color=pal.grid, other_circle_color=pal.grid,
        straight_line_lw=1, last_circle_lw=1.4, other_circle_lw=1)
    fig, ax = baker.make_pizza(
        values, figsize=(8.2, 8.6), color_blank_space="same", slice_colors=slice_colors,
        value_bck_colors=slice_colors, blank_alpha=0.35,
        kwargs_slices=dict(edgecolor=pal.bg, zorder=2, linewidth=1),
        kwargs_params=dict(color=pal.text, fontsize=9, va="center"),
        kwargs_values=dict(color=pal.bg, fontsize=9, zorder=3,
                           bbox=dict(edgecolor=pal.bg, boxstyle="round,pad=0.2", lw=1)))
    fig.set_facecolor(pal.bg)
    fam = {"fontfamily": pal.font} if pal.font else {}
    dims = view.dimensions.get(player, {})
    sub = "  ·  ".join([player] + [str(dims[k]) for k in ("team", "position") if dims.get(k)])
    fig.text(0.515, 0.975, "Player Pizza", color=pal.text, fontsize=16, fontweight="bold",
             ha="center", va="top", **fam)
    fig.text(0.515, 0.938, sub, color=pal.muted, fontsize=10, ha="center", va="top", **fam)
    fig.text(0.515, 0.022, f"{data['note']}  ·  {_footer(view)}", color=pal.muted,
             fontsize=7.5, ha="center", va="bottom", **fam)
    return fig


def scatter(view: ScoutingView, x_source: str, y_source: str, theme: Any,
            frame=None) -> Figure:
    """Metric-vs-metric scatter: population in the background, selected player(s)
    highlighted. Optional trendline when there are enough players."""
    pal = palette(theme)
    fig, ax = _new_fig(pal, (8.2, 7.0))
    fig.subplots_adjust(left=0.11, right=0.96, top=0.82, bottom=0.11)
    mx, my = view.metric(x_source), view.metric(y_source)
    if mx is None or my is None or frame is None:
        ax.axis("off"); _titles(fig, pal, "Scatter", "select two metrics", _footer(view))
        return fig
    xs = pd_to_numeric(frame[mx.source]); ys = pd_to_numeric(frame[my.source])
    mask = xs.notna() & ys.notna()
    ax.scatter(xs[mask], ys[mask], s=26, color=pal.grey, alpha=0.45, edgecolors="none",
               zorder=2, label="dataset")
    if mask.sum() >= 10:                       # trendline only when meaningful
        try:
            b, a = np.polyfit(xs[mask], ys[mask], 1)
            xr = np.array([xs[mask].min(), xs[mask].max()])
            ax.plot(xr, a + b * xr, color=pal.muted, lw=1, ls="--", alpha=0.7, zorder=1)
        except Exception:
            pass
    colors = [pal.accent, pal.warning, pal.success, pal.danger]
    for i, player in enumerate(view.players):
        vx, vy = mx.value(player), my.value(player)
        if vx is None or vy is None:
            continue
        col = colors[i % len(colors)]
        ax.scatter([vx], [vy], s=170, color=col, edgecolors=pal.bg, lw=1.5, zorder=4)
        ax.annotate(player, (vx, vy), textcoords="offset points", xytext=(8, 6),
                    color=pal.text, fontsize=9, fontweight="bold")
    ax.set_xlabel(mx.name, color=pal.text, fontsize=9)
    ax.set_ylabel(my.name, color=pal.text, fontsize=9)
    ax.grid(color=pal.grid, lw=0.6, alpha=0.5); ax.set_axisbelow(True)
    _titles(fig, pal, "Metric scatter", f"{mx.name}  vs  {my.name}", _footer(view))
    return fig


def histogram(view: ScoutingView, source: str, theme: Any, frame=None) -> Figure:
    """Population distribution of a metric with the player's position marked."""
    pal = palette(theme)
    fig, ax = _new_fig(pal, (8.2, 5.6))
    fig.subplots_adjust(left=0.10, right=0.96, top=0.82, bottom=0.12)
    m = view.metric(source)
    if m is None or frame is None:
        ax.axis("off"); _titles(fig, pal, "Distribution", "select a metric", _footer(view))
        return fig
    vals = pd_to_numeric(frame[m.source]).dropna()
    ax.hist(vals, bins=min(20, max(6, int(math.sqrt(len(vals))))), color=pal.accent,
            alpha=0.7, edgecolor=pal.bg)
    pv = m.value(view.primary)
    if pv is not None:
        ax.axvline(pv, color=pal.warning, lw=2.2, zorder=5)
        ax.text(pv, ax.get_ylim()[1] * 0.96, f" {view.primary}", color=pal.warning,
                fontsize=9, ha="left", va="top", fontweight="bold")
    ax.set_xlabel(m.name, color=pal.text, fontsize=9)
    ax.set_ylabel("players", color=pal.muted, fontsize=9)
    ax.grid(axis="y", color=pal.grid, lw=0.6, alpha=0.5); ax.set_axisbelow(True)
    _titles(fig, pal, "Distribution", _player_line(view), _footer(view))
    return fig


def box_plot(view: ScoutingView, sources: list[str], theme: Any, frame=None) -> Figure:
    """Population spread of the selected metrics with the player's markers."""
    pal = palette(theme)
    metrics = _sources_or_all(view, sources)[:10]
    fig, ax = _new_fig(pal, (8.5, max(4.0, 0.5 * len(metrics) + 2)))
    fig.subplots_adjust(left=0.42, right=0.96, top=0.82, bottom=0.12)
    if frame is None or not metrics:
        ax.axis("off"); _titles(fig, pal, "Box plot", "select metrics", _footer(view))
        return fig
    data = [pd_to_numeric(frame[m.source]).dropna().to_numpy() for m in metrics]
    pos = np.arange(len(metrics))[::-1]
    bp = ax.boxplot(data, positions=pos, vert=False, widths=0.55, patch_artist=True,
                    medianprops=dict(color=pal.text, lw=1.2))
    for patch in bp["boxes"]:
        patch.set(facecolor=pal.panel, edgecolor=pal.grid)
    for whisk in bp["whiskers"] + bp["caps"]:
        whisk.set(color=pal.grid)
    for yi, m in zip(pos, metrics):
        pv = m.value(view.primary)
        if pv is not None:
            ax.scatter([pv], [yi], color=pal.warning, s=70, zorder=5, edgecolors=pal.bg)
    ax.set_yticks(pos); ax.set_yticklabels([m.name for m in metrics], color=pal.text, fontsize=8)
    ax.grid(axis="x", color=pal.grid, lw=0.6, alpha=0.5); ax.set_axisbelow(True)
    _titles(fig, pal, "Population spread", f"{_player_line(view)}  ·  marker = player",
            _footer(view))
    return fig


def lollipop(view: ScoutingView, sources: list[str], theme: Any) -> Figure:
    """Clean lollipop of the player's selected metrics (0-100 score)."""
    pal = palette(theme)
    metrics = _sources_or_all(view, sources)[:16]
    fig, ax = _new_fig(pal, (8.5, max(4.0, 0.42 * len(metrics) + 2)))
    fig.subplots_adjust(left=0.42, right=0.96, top=0.82, bottom=0.12)
    names = [m.name for m in metrics]
    scores = [_score(view, m, view.primary) for m in metrics]
    cols = pal.category_colors([m.category for m in metrics])
    y = np.arange(len(metrics))[::-1]
    ax.hlines(y, 0, scores, color=pal.grid, lw=1.6, zorder=1)
    ax.scatter(scores, y, color=cols, s=90, zorder=3, edgecolors=pal.bg)
    for yi, s in zip(y, scores):
        ax.text(s + 1.5, yi, f"{s:.0f}", va="center", ha="left", color=pal.text, fontsize=8)
    ax.set_xlim(0, 104)
    ax.set_yticks(y); ax.set_yticklabels(names, color=pal.text, fontsize=8)
    ax.grid(axis="x", color=pal.grid, lw=0.6, alpha=0.5); ax.set_axisbelow(True)
    _titles(fig, pal, "Lollipop", f"{_player_line(view)}  ·  {_score_label(view)}", _footer(view))
    return fig


def comparison_bars(view: ScoutingView, sources: list[str], theme: Any) -> Figure:
    """Grouped horizontal bars comparing 2+ players across the selected metrics."""
    pal = palette(theme)
    metrics = _sources_or_all(view, sources)[:12]
    players = list(view.players)
    fig, ax = _new_fig(pal, (9.0, max(4.5, 0.6 * len(metrics) + 2)))
    fig.subplots_adjust(left=0.42, right=0.96, top=0.82, bottom=0.12)
    colors = [pal.accent, pal.warning, pal.success, pal.danger]
    base = np.arange(len(metrics))[::-1].astype(float)
    h = 0.8 / max(len(players), 1)
    for i, player in enumerate(players):
        scores = [_score(view, m, player) for m in metrics]
        ax.barh(base + (i - (len(players) - 1) / 2) * h, scores, height=h,
                color=colors[i % len(colors)], edgecolor=pal.bg, label=player)
    ax.set_xlim(0, 100)
    ax.set_yticks(base); ax.set_yticklabels([m.name for m in metrics], color=pal.text, fontsize=8)
    ax.grid(axis="x", color=pal.grid, lw=0.6, alpha=0.5); ax.set_axisbelow(True)
    ax.legend(loc="lower right", facecolor=pal.panel, edgecolor=pal.grid,
              labelcolor=pal.text, fontsize=8)
    _titles(fig, pal, "Player comparison", _score_label(view), _footer(view))
    return fig


def small_multiples(view: ScoutingView, sources: list[str], theme: Any) -> Figure:
    """Compact mini-bars per metric - clean for scouting reports (section 16)."""
    pal = palette(theme)
    metrics = _sources_or_all(view, sources)[:12]
    n = len(metrics)
    cols = 3 if n > 4 else max(1, n)
    rows = math.ceil(n / cols) if n else 1
    fig = Figure(figsize=(9.0, 1.4 * rows + 1.4), dpi=150, facecolor=pal.bg)
    fig.subplots_adjust(left=0.05, right=0.97, top=0.84, bottom=0.06, hspace=0.9, wspace=0.25)
    for i, m in enumerate(metrics):
        ax = fig.add_subplot(rows, cols, i + 1); ax.set_facecolor(pal.bg)
        score = _score(view, m, view.primary)
        col = pal.category_colors([m.category])[0]
        ax.barh([0], [100], color=pal.grid, alpha=0.35, height=0.5)
        ax.barh([0], [score], color=col, height=0.5, edgecolor=pal.bg)
        ax.set_xlim(0, 100); ax.set_ylim(-0.6, 0.6); ax.axis("off")
        ax.text(0, 0.7, m.name, color=pal.text, fontsize=8, va="bottom", ha="left")
        ax.text(100, 0.7, f"{score:.0f}", color=pal.muted, fontsize=8, va="bottom", ha="right")
    _titles(fig, pal, "Metric snapshot", f"{_player_line(view)}  ·  {_score_label(view)}",
            _footer(view))
    return fig


def heatmap(view: ScoutingView, sources: list[str], theme: Any) -> Figure:
    """Players x metrics matrix of 0-100 scores."""
    pal = palette(theme)
    metrics = _sources_or_all(view, sources)[:16]
    players = list(view.players)
    fig, ax = _new_fig(pal, (max(7.0, 0.6 * len(players) + 4), max(4.5, 0.4 * len(metrics) + 2)))
    fig.subplots_adjust(left=0.42, right=0.9, top=0.82, bottom=0.1)
    if not metrics or len(players) < 1:
        ax.axis("off"); _titles(fig, pal, "Matrix", "need players and metrics", _footer(view))
        return fig
    mat = np.array([[_score(view, m, p) for p in players] for m in metrics])
    cmap = (getattr(theme, "heatmap_cmaps", None) or ("viridis",))[0]
    im = ax.imshow(mat, aspect="auto", cmap=cmap, vmin=0, vmax=100)
    ax.set_xticks(range(len(players))); ax.set_xticklabels(players, color=pal.text, fontsize=8, rotation=20, ha="right")
    ax.set_yticks(range(len(metrics))); ax.set_yticklabels([m.name for m in metrics], color=pal.text, fontsize=8)
    for i in range(len(metrics)):
        for j in range(len(players)):
            ax.text(j, i, f"{mat[i, j]:.0f}", ha="center", va="center",
                    color=pal.bg, fontsize=7)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.ax.tick_params(colors=pal.muted, labelsize=7)
    _titles(fig, pal, "Metric matrix", _score_label(view), _footer(view))
    return fig


# small local helper so this module doesn't import pandas at top just for one call
def pd_to_numeric(series):
    import pandas as pd
    return pd.to_numeric(series, errors="coerce")


# dispatch used by the UI / tests
RENDERERS = {
    "bar": lambda view, theme, opts: bar_chart(view, opts.get("metrics"), theme),
    "percentile_bar": lambda view, theme, opts: percentile_bar(view, opts.get("metrics"), theme),
    "ranking_bar": lambda view, theme, opts: ranking_bar(view, opts.get("metric"), theme),
    "radar": lambda view, theme, opts: radar_chart(view, opts.get("metrics"), theme),
    "pizza": lambda view, theme, opts: pizza_chart(view, opts.get("metrics"), theme),
    "scatter": lambda view, theme, opts: scatter(view, opts.get("x"), opts.get("y"), theme, opts.get("frame")),
    "histogram": lambda view, theme, opts: histogram(view, opts.get("metric"), theme, opts.get("frame")),
    "box": lambda view, theme, opts: box_plot(view, opts.get("metrics"), theme, opts.get("frame")),
    "lollipop": lambda view, theme, opts: lollipop(view, opts.get("metrics"), theme),
    "comparison": lambda view, theme, opts: comparison_bars(view, opts.get("metrics"), theme),
    "small_multiples": lambda view, theme, opts: small_multiples(view, opts.get("metrics"), theme),
    "heatmap": lambda view, theme, opts: heatmap(view, opts.get("metrics"), theme),
}


def render(chart_type: str, view: ScoutingView, theme: Any, options: dict | None = None) -> Figure:
    """Render any supported chart type to a matplotlib Figure. The CALLER exports
    it (via ExportEngine) and closes it - figures are never returned into state."""
    fn = RENDERERS.get(chart_type)
    if fn is None:
        raise ValueError(f"unknown chart type {chart_type!r}")
    return fn(view, theme, options or {})


__all__ = ["Palette", "palette", "render", "RENDERERS",
           "bar_chart", "percentile_bar", "ranking_bar", "radar_chart", "pizza_chart",
           "scatter", "histogram", "box_plot", "lollipop", "comparison_bars",
           "small_multiples", "heatmap"]
