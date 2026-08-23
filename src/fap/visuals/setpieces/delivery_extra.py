"""Delivery-structure set-piece charts — ported from the standalone Set-Pieces app.

These render straight from a rich set-piece export (delivery landing, target zone,
first/second-ball wins, near/far-post player & defender counts, taker) — NO manual
position/contact tagging. They consume the ``delivery_full`` dataset (one row per
set-piece delivery, built in ``fap.setpieces.build_frames``). Registered into the
same set-piece registry via ``_reg`` so they appear in the Set Piece picker.
"""
from __future__ import annotations

from collections import Counter

from fap.visuals.setpieces.builders import CAT_CONTACTS, CAT_DEFENSIVE, CAT_DELIVERY, sp_chart
from fap.visuals.setpieces.library import _chart_axes, _reg

# named delivery zones inside/around the box (canonical x,y 0-100; attacking x=100).
# tightest first so a landing maps to exactly one zone.
_ZONES = (
    ("Near post", 94.2, 21.0, 100.0, 39.0),
    ("Far post", 94.2, 61.0, 100.0, 79.0),
    ("6-yard centre", 94.2, 39.0, 100.0, 61.0),
    ("Penalty spot", 88.0, 36.0, 94.2, 64.0),
    ("Box left", 83.0, 21.0, 94.2, 36.0),
    ("Box right", 83.0, 64.0, 94.2, 79.0),
    ("Edge of box", 74.0, 21.0, 83.0, 79.0),
)


def _zone_of(x, y):
    if x is None or y is None:
        return ""
    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        return ""
    for name, x0, y0, x1, y1 in _ZONES:
        if x0 <= fx <= x1 and y0 <= fy <= y1:
            return name
    return ""


def _df(ctx):
    import pandas as pd
    df = ctx.df
    return df if df is not None and not df.empty else pd.DataFrame()


def _no_data(ctx, msg="No delivery data"):
    ax, c = ctx.ax, ctx.theme.colors
    ax.set_facecolor(c["panel"])
    ax.text(0.5, 0.5, msg, ha="center", va="center", color=c["muted"], transform=ax.transAxes)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])


def _box_pitch(ctx):
    from fap.visuals.pitch import DISPLAY_WIDTH, PitchFactory, get_spec
    PitchFactory().draw_pitch(ctx.ax, ctx.theme, get_spec("uefa"), vertical=False)
    ctx.ax.set_xlim(72.0, 101.5)                       # crop to the attacking penalty area
    ctx.ax.set_ylim(12.0, DISPLAY_WIDTH - 12.0)
    ctx.ax.set_aspect("equal")
    ctx.ax.axis("off")
    return DISPLAY_WIDTH


def _fnum(v):
    try:
        if v is None or str(v).strip() in ("", "nan"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------- pitch charts
def _delivery_zones(ctx):
    from matplotlib.colors import to_rgba
    from matplotlib.patches import Rectangle
    df = _df(ctx)
    if df.empty or "end_x" not in df.columns:
        return _no_data(ctx)
    W = _box_pitch(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    accent = ctx.controls.get("primary_color") or c["accent"]
    counts = {z[0]: 0 for z in _ZONES}
    total = 0
    for _, r in df.iterrows():
        z = _zone_of(r.get("end_x"), r.get("end_y"))
        if z:
            counts[z] += 1; total += 1
    mx = max(counts.values()) or 1
    for name, x0, y0, x1, y1 in _ZONES:
        n = counts[name]
        ax.add_patch(Rectangle((x0, y0 / 100 * W), x1 - x0, (y1 - y0) / 100 * W,
                               facecolor=to_rgba(accent, 0.12 + 0.6 * n / mx),
                               edgecolor=c["lines"], lw=1.0, zorder=2))
        pct = (100 * n / total) if total else 0
        ax.text((x0 + x1) / 2, (y0 + y1) / 2 / 100 * W, f"{n}\n{pct:.0f}%", ha="center",
                va="center", fontsize=ctx.style("label_size"), color=c["text"],
                fontweight="bold", zorder=3)
    ax.set_title(f"Delivery zones ({total})", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _second_ball_map(ctx):
    df = _df(ctx)
    if df.empty or "end_x" not in df.columns:
        return _no_data(ctx)
    W = _box_pitch(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    nw = nl = 0
    for _, r in df.iterrows():
        x, y = _fnum(r.get("end_x")), _fnum(r.get("end_y"))
        if x is None or y is None:
            continue
        dy = y / 100 * W
        if bool(r.get("second_ball_win")):
            ax.scatter([x], [dy], s=90, facecolor=c["success"], edgecolor=c["bg"], lw=1.0, zorder=5); nw += 1
        else:
            ax.scatter([x], [dy], s=90, facecolor="none", edgecolor=c["danger"], lw=2.0, zorder=5); nl += 1
    ax.set_title(f"Second ball — won {nw} / lost {nl}", color=c["text"],
                 fontsize=ctx.style("label_size") + 1)


# --------------------------------------------------------------- bar charts
def _fc_win_zone(ctx):
    df = _df(ctx)
    if df.empty or "first_contact_win" not in df.columns:
        return _no_data(ctx, "No first-contact data")
    agg: dict[str, list[int]] = {}
    for _, r in df.iterrows():
        z = _zone_of(r.get("end_x"), r.get("end_y"))
        w = r.get("first_contact_win")
        if not z or w is None:
            continue
        a = agg.setdefault(z, [0, 0])
        a[0] += 1 if bool(w) else 0
        a[1] += 1
    if not agg:
        return _no_data(ctx, "No first-contact data")
    zones = sorted(agg, key=lambda z: agg[z][0] / agg[z][1], reverse=True)
    pct = [100 * agg[z][0] / agg[z][1] for z in zones]
    ax, c = ctx.ax, ctx.theme.colors
    _chart_axes(ctx)
    ax.barh(zones, pct, color=[c["success"] if p >= 50 else c["danger"] for p in pct])
    ax.set_xlim(0, 100); ax.invert_yaxis()
    ax.set_xlabel("First-contact win %", color=c["muted"])
    ax.set_title("First contact win by zone", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _target_zone_breakdown(ctx):
    df = _df(ctx)
    if df.empty:
        return _no_data(ctx)
    has_tz = "target_zone" in df.columns and df["target_zone"].astype(str).str.strip().ne("").any()
    if has_tz:
        labels = [str(v).strip() for v in df["target_zone"].tolist()]
    else:
        labels = [_zone_of(r.get("end_x"), r.get("end_y")) for _, r in df.iterrows()]
    cnt = Counter(l for l in labels if l)
    if not cnt:
        return _no_data(ctx)
    items = cnt.most_common(10)
    ax, c = ctx.ax, ctx.theme.colors
    _chart_axes(ctx)
    ax.bar([k for k, _ in items], [v for _, v in items],
           color=ctx.controls.get("primary_color") or c["accent"])
    ax.set_title("Target zone breakdown", color=c["text"], fontsize=ctx.style("label_size") + 1)
    for t in ax.get_xticklabels():
        t.set_rotation(30); t.set_ha("right")


def _taker_profile(ctx):
    df = _df(ctx)
    if df.empty or "taker" not in df.columns:
        return _no_data(ctx, "No taker data")
    cnt = Counter(str(t).strip() for t in df["taker"].tolist() if str(t).strip())
    if not cnt:
        return _no_data(ctx, "No taker data")
    items = cnt.most_common(10)
    ax, c = ctx.ax, ctx.theme.colors
    _chart_axes(ctx)
    ax.barh([k for k, _ in items], [v for _, v in items],
            color=ctx.controls.get("primary_color") or c["accent"])
    ax.invert_yaxis()
    ax.set_xlabel("Set pieces taken", color=c["muted"])
    ax.set_title("Taker profile", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _structure_avgs(ctx):
    import numpy as np
    df = _df(ctx)
    cols = [("players_near_post", "Near post"), ("players_far_post", "Far post"),
            ("players_small_area", "6-yard"), ("players_penalty_area", "Penalty area")]
    present = [(col, lbl) for col, lbl in cols if col in df.columns]
    if df.empty or not present:
        return _no_data(ctx, "No structure data")
    labels, atk, dfn = [], [], []
    for col, lbl in present:
        vals = [v for v in (_fnum(x) for x in df[col].tolist()) if v is not None]
        dcol = col.replace("players_", "defenders_")
        dvals = ([v for v in (_fnum(x) for x in df[dcol].tolist()) if v is not None]
                 if dcol in df.columns else [])
        labels.append(lbl)
        atk.append(sum(vals) / len(vals) if vals else 0)
        dfn.append(sum(dvals) / len(dvals) if dvals else 0)
    ax, c = ctx.ax, ctx.theme.colors
    _chart_axes(ctx)
    x = np.arange(len(labels)); w = 0.4
    ax.bar(x - w / 2, atk, w, label="Attackers", color=c["accent"])
    if any(dfn):
        ax.bar(x + w / 2, dfn, w, label="Defenders", color=c["danger"])
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("Avg players", color=c["muted"])
    ax.set_title("Set-piece structure (avg players / zone)", color=c["text"],
                 fontsize=ctx.style("label_size") + 1)
    if any(dfn):
        ax.legend(facecolor=c["panel"], edgecolor=c["grid"], labelcolor=c["text"])


# ------------------------------------------------------------------ register
_reg(sp_chart("sp_delivery_zones", "Delivery Zones", CAT_DELIVERY, "delivery_full",
              _delivery_zones, description="Where deliveries land across the box zones."))
_reg(sp_chart("sp_first_contact_win_zone", "First Contact Win by Zone", CAT_CONTACTS,
              "delivery_full", _fc_win_zone, description="Win % of the first contact per zone."))
_reg(sp_chart("sp_second_ball_map", "Second Ball Map", CAT_CONTACTS, "delivery_full",
              _second_ball_map, description="Where the second ball is won/lost."))
_reg(sp_chart("sp_target_zone_breakdown", "Target Zone Breakdown", CAT_DELIVERY,
              "delivery_full", _target_zone_breakdown, description="Delivery destination mix."))
_reg(sp_chart("sp_taker_profile", "Taker Profile", CAT_DELIVERY, "delivery_full",
              _taker_profile, description="Set pieces taken per player."))
_reg(sp_chart("sp_defensive_structure", "Defensive Structure", CAT_DEFENSIVE, "delivery_full",
              _structure_avgs, description="Average attackers/defenders per box zone."))
