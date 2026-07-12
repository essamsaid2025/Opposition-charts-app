"""Distribution and timeline charts (non-pitch), all through the chart builder."""
from __future__ import annotations

import numpy as np
import pandas as pd

from fap.visuals import analysis as A
from fap.visuals.maps._builders import chart


def _hist(ax, ctx, values: pd.Series, *, bins: int, xlabel: str, color=None) -> None:
    values = pd.to_numeric(values, errors="coerce").dropna()
    if values.empty:
        return
    ax.hist(values, bins=bins,
            color=color or ctx.controls.get("primary_color") or ctx.theme.colors["bar"],
            edgecolor=ctx.theme.colors["grid"], alpha=0.9)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Count")


chart("pass_length_distribution", "Pass Length Distribution",
      lambda ctx, ax: _hist(ax, ctx, A.passes(ctx.df)["pass_length"],
                            bins=24, xlabel="Pass length (m)"),
      category="Passing")
chart("pass_angle_distribution", "Pass Angle Distribution",
      lambda ctx, ax: _hist(ax, ctx, np.degrees(pd.to_numeric(
          A.passes(ctx.df)["pass_angle"], errors="coerce")),
          bins=24, xlabel="Pass angle (° , 0 = straight upfield)"),
      category="Passing")
chart("shot_distance_chart", "Shot Distance",
      lambda ctx, ax: _hist(ax, ctx, A.shots(ctx.df)["shot_distance"],
                            bins=18, xlabel="Shot distance (units to goal)"),
      category="Attacking")
chart("shot_angle_chart", "Shot Angle",
      lambda ctx, ax: _hist(ax, ctx, np.degrees(np.arctan2(
          (A.shots(ctx.df)["y"] - 50) * 0.68,
          (100 - A.shots(ctx.df)["x"]) * 1.05)),
          bins=18, xlabel="Shot angle (° from goal center)"),
      category="Attacking")
chart("gk_distribution_length", "Distribution Length",
      lambda ctx, ax: _hist(ax, ctx, A.passes(A.goalkeeper(ctx.df))["pass_length"],
                            bins=18, xlabel="Goalkeeper distribution length (m)"),
      category="Goalkeeper")
chart("progressive_distance", "Progressive Distance",
      lambda ctx, ax: _bar_by_player(
          ax, ctx, A.progressive(A.movement(ctx.df)), "distance",
          "Progressive distance (units)"),
      category="Progression")


def _bar_by_player(ax, ctx, d: pd.DataFrame, value_col: str, xlabel: str,
                   top: int = 12) -> None:
    d = d[d["player"].str.strip().ne("")]
    if d.empty:
        return
    totals = d.groupby("player")[value_col].sum().sort_values().tail(top)
    ax.barh(totals.index, totals.values,
            color=ctx.controls.get("primary_color") or ctx.theme.colors["bar"])
    ax.set_xlabel(xlabel)


def _timeline(ax, ctx, d: pd.DataFrame, label: str) -> None:
    times = pd.to_numeric(d["time_min"], errors="coerce").dropna()
    if times.empty:
        return
    bins = np.arange(0, max(96, float(times.max()) + 6), 5)
    counts, edges = np.histogram(times, bins=bins)
    ax.plot(edges[:-1], counts, marker="o",
            color=ctx.controls.get("primary_color") or ctx.theme.colors["accent"],
            lw=2.2, label=label)
    if len(counts) >= 3:
        roll = pd.Series(counts).rolling(3, min_periods=1).mean()
        ax.plot(edges[:-1], roll,
                color=ctx.controls.get("fail_color") or ctx.theme.colors["danger"],
                lw=2.0, ls="--", label="Trend")
    ax.set_xlabel("Minute")
    ax.set_ylabel(f"{label} per 5 min")
    if ctx.controls.get("legend", True):
        ax.legend(facecolor=ctx.theme.colors["panel"],
                  edgecolor=ctx.theme.colors["grid"],
                  labelcolor=ctx.theme.colors["text"],
                  fontsize=ctx.style("legend_size"))


chart("shot_timeline", "Shot Timeline",
      lambda ctx, ax: _timeline(ax, ctx, A.shots(ctx.df), "Shots"),
      category="Attacking")
chart("transition_timeline", "Transition Timeline",
      lambda ctx, ax: _timeline(
          ax, ctx, A.sequence_reaching(ctx.df, 66.67, within_seconds=15),
          "Transitions"),
      category="Transitions")
chart("sequence_timeline", "Sequence Timeline",
      lambda ctx, ax: _sequence_timeline(ax, ctx), category="Possession")


def _sequence_timeline(ax, ctx) -> None:
    rows = []
    for seq_id, g in A.sequences(ctx.df):
        rows.append({"start": g["time_min"].min(), "events": len(g),
                     "shot": g["event_type"].str.lower().eq("shot").any()})
    if not rows:
        return
    d = pd.DataFrame(rows)
    colors = [ctx.theme.colors["danger"] if s else
              (ctx.controls.get("primary_color") or ctx.theme.colors["accent"])
              for s in d["shot"]]
    ax.scatter(d["start"], d["events"], c=colors, s=48,
               edgecolors=ctx.theme.colors["grid"])
    ax.set_xlabel("Sequence start (minute)")
    ax.set_ylabel("Events in sequence")


def _team_metric_over_time(ax, ctx, metric: str) -> None:
    d = ctx.df.dropna(subset=["x", "y", "time_min"])
    if d.empty:
        return
    bins = np.arange(0, max(96, float(d["time_min"].max()) + 6), 5)
    d = d.assign(bin=pd.cut(d["time_min"], bins=bins, labels=bins[:-1]))
    if metric == "width":
        series = d.groupby("bin", observed=False)["y"].agg(lambda s: s.max() - s.min())
        ylabel = "Width (y span)"
    elif metric == "depth":
        series = d.groupby("bin", observed=False)["x"].agg(lambda s: s.max() - s.min())
        ylabel = "Depth (x span)"
    else:                                   # compactness: mean distance to centroid
        def compact(g: pd.DataFrame) -> float:
            cx, cy = g["x"].mean(), g["y"].mean()
            return float(np.sqrt((g["x"] - cx) ** 2 + (g["y"] - cy) ** 2).mean())
        series = d.groupby("bin", observed=False).apply(compact, include_groups=False)
        ylabel = "Compactness (mean spread, lower = tighter)"
    ax.plot(series.index.astype(float), series.values, marker="o", lw=2.2,
            color=ctx.controls.get("primary_color") or ctx.theme.colors["accent"])
    ax.set_xlabel("Minute")
    ax.set_ylabel(ylabel)


chart("team_width", "Width", lambda ctx, ax: _team_metric_over_time(ax, ctx, "width"),
      category="Team")
chart("team_depth", "Depth", lambda ctx, ax: _team_metric_over_time(ax, ctx, "depth"),
      category="Team")
chart("team_compactness", "Compactness",
      lambda ctx, ax: _team_metric_over_time(ax, ctx, "compactness"), category="Team")


def _press_resistance(ax, ctx) -> None:
    d = A.under_pressure(A.movement(ctx.df))
    if d.empty:
        return
    by_player = d[d["player"].str.strip().ne("")].groupby("player")
    stats = by_player.apply(
        lambda g: pd.Series({"attempts": len(g),
                             "retained": len(A.successful(g)) / max(len(g), 1) * 100}),
        include_groups=False)
    stats = stats[stats["attempts"] >= 3].sort_values("retained").tail(12)
    if stats.empty:
        return
    ax.barh(stats.index, stats["retained"],
            color=ctx.controls.get("primary_color") or ctx.theme.colors["success"])
    ax.set_xlabel("Retention under pressure (%)")
    ax.set_xlim(0, 100)


chart("press_resistance", "Press Resistance",
      lambda ctx, ax: _press_resistance(ax, ctx), category="Build-up",
      description="On-ball retention % when pressed (min 3 attempts).")
