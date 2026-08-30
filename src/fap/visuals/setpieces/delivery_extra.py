"""Delivery-structure set-piece charts — ported from the standalone Set-Pieces app.

Render straight from a rich set-piece export (delivery landing, delivery type,
target zone, first/second-ball wins, near/far-post player & defender counts,
taker) — NO manual position/contact tagging. They consume the ``delivery_full``
dataset (one row per delivery, built in ``fap.setpieces.build_frames``).

Pitch charts draw on a real football pitch via ``mplsoccer`` (correct proportions,
goal at the top). Orientation is a control (``sp_orientation`` = vertical|horizontal).
Coordinates are canonical: ``x`` = depth (attacking toward 100 = the goal line),
``y`` = across the goal (0-100) — fed to mplsoccer's Opta pitch as (x=length, y=width).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from fap.core.types import Control
from fap.visuals.setpieces.builders import (CAT_CONTACTS, CAT_DEFENSIVE, CAT_DELIVERY,
                                            sp_chart)
from fap.visuals.setpieces.library import _chart_axes, _reg

ORIENT = Control("sp_orientation", "Pitch orientation", "select", default="vertical",
                 options=("vertical", "horizontal"),
                 help="Draw the set-piece box vertically (goal at top) or horizontally.")

# named delivery zones inside the box (canonical x depth, y across; 0-100). Canonical
# y=0 is the RIGHT touchline, so the low-y band is the right of the box (matching the
# near/far-post naming for a right-side corner) and the high-y band is the left.
_ZONES = (
    ("Near post", 94.2, 20.0, 100.0, 44.0),
    ("Far post", 94.2, 56.0, 100.0, 80.0),
    ("6-yard centre", 94.2, 44.0, 100.0, 56.0),
    ("Penalty spot", 88.0, 44.0, 94.2, 56.0),
    ("Box right", 83.0, 20.0, 94.2, 44.0),
    ("Box left", 83.0, 56.0, 94.2, 80.0),
    ("Edge of box", 74.0, 20.0, 83.0, 80.0),
)
_DELIVERY_COLORS = {
    "inswing": "accent", "outswing": "accent_2", "straight": "success",
    "driven": "warning", "short": "grey", "lofted": "bar", "ground": "muted",
}


def _fnum(v):
    try:
        if v is None or str(v).strip() in ("", "nan"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _zone_of(x, y):
    fx, fy = _fnum(x), _fnum(y)
    if fx is None or fy is None:
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


def _dcolor(ctx, dt):
    c = ctx.theme.colors
    return c.get(_DELIVERY_COLORS.get(str(dt).strip().lower(), "accent"), c["accent"])


def _pitch(ctx):
    """A half-pitch focused on the attacking box, honoring the orientation control.
    Returns the mplsoccer pitch (use ``p.scatter/arrows/lines/kdeplot`` with canonical
    ``x``=depth, ``y``=across, ``ax=ctx.ax``)."""
    from mplsoccer import Pitch, VerticalPitch
    c = ctx.theme.colors
    orient = str(ctx.controls.get("sp_orientation")
                 or ctx.controls.get("orientation") or "vertical").lower()
    if orient not in ("vertical", "horizontal"):
        orient = "vertical"                             # e.g. framework "auto"
    kw = dict(pitch_type="opta", half=True, pitch_color=c.get("bg", c["panel"]),
              line_color=c["lines"], linewidth=1.5, pad_top=2, goal_type="box",
              goal_alpha=1.0)
    p = (Pitch(**kw) if orient == "horizontal" else VerticalPitch(**kw))
    p.draw(ax=ctx.ax)
    ctx.ax.set_facecolor(c.get("bg", c["panel"]))
    ax = ctx.ax
    # zoom to the attacking third (box + edge) so the set-piece area fills the frame,
    # and orient "across" to the canonical convention (y=0 = RIGHT touchline) so a
    # Right-side corner reads on the RIGHT — matching the sheet's ``side`` and the
    # tagging tool. Vertical: across is the x-axis, so y=0 must sit on the right
    # (descending xlim). Horizontal (attack →): across is the y-axis, y=0 at the
    # bottom (ascending ylim), which is the right touchline for a left→right attack.
    if orient == "horizontal":
        ax.set_xlim(74.0, 101.0)
        y0, y1 = ax.get_ylim(); ax.set_ylim(min(y0, y1), max(y0, y1))
    else:
        ax.set_ylim(73.5, 101.0)
        x0, x1 = ax.get_xlim(); ax.set_xlim(max(x0, x1), min(x0, x1))
    return p


def _ends(df):
    out = []
    for _, r in df.iterrows():
        x, y = _fnum(r.get("end_x")), _fnum(r.get("end_y"))
        if x is not None and y is not None:
            out.append((x, y, r))                       # (depth, across, row)
    return out


# named corner zones (canonical depth x0..x1, across y0..y1) + fixed zone colours
# matching the standalone app's corner-zone map (independent of the chart theme).
_CORNER_ZONES = (
    ("Six Yard", 94.2, 44.0, 100.0, 56.0, "#B59B3A", 0.60),      # checked first (specific)
    ("Penalty Spot", 83.0, 44.0, 94.2, 56.0, "#2E8B57", 0.55),
    ("Near Post Short", 83.0, 2.0, 100.0, 20.0, "#2E6E8E", 0.30),
    ("Near Post", 83.0, 20.0, 100.0, 44.0, "#2E6E8E", 0.48),
    ("Far Post", 83.0, 56.0, 100.0, 80.0, "#3E5C8A", 0.48),
    ("Far Post Long", 83.0, 80.0, 100.0, 98.0, "#3E5C8A", 0.30),
    ("Box Front", 74.0, 30.0, 83.0, 70.0, "#5A6472", 0.28),
)


def _corner_zone_of(x, y):
    fx, fy = _fnum(x), _fnum(y)
    if fx is None or fy is None:
        return ""
    for name, x0, y0, x1, y1, _c, _a in _CORNER_ZONES:
        if x0 <= fx <= x1 and y0 <= fy <= y1:
            return name
    return ""


def _canon_zone(s):
    """Collapse any zone wording (a drawn-zone name or a sheet ``target_zone`` label)
    to a stable token, so the analyst's own zone labels drive the zone charts."""
    t = str(s or "").strip().lower()
    if not t or t == "nan":
        return ""
    if "near" in t:
        return "near"
    if "far" in t:
        return "far"
    if "spot" in t:
        return "spot"
    if "six" in t or "6" in t or "middle" in t or "central" in t \
            or "centre" in t or "center" in t:
        return "middle"                                 # 6-yard / central band
    if "short" in t:
        return "short"
    if "edge" in t or "front" in t or "top" in t:
        return "edge"
    if "left" in t:
        return "left"
    if "right" in t:
        return "right"
    if "penalty" in t or "pen" in t or "box" in t:
        return "middle"
    return t


def _match_drawn_zone(label, zone_names):
    """Best drawn-zone name for a sheet ``target_zone`` label (token match). Prefers
    the base zone over a qualified variant (``Near Post`` over ``Near Post Short``);
    returns "" when the label names no drawn box zone."""
    tok = _canon_zone(label)
    if not tok:
        return ""
    cands = [z for z in zone_names if _canon_zone(z) == tok]
    return min(cands, key=len) if cands else ""


def _resolved_zone(row, zone_names, coord_fn):
    """The zone a delivery belongs to. The sheet's ``target_zone`` label wins (this
    is the analyst's intent); only when a row carries no usable label — or a label
    that names no box zone (e.g. a short-corner routine) — do we fall back to the
    landing coordinates."""
    label = str(row.get("target_zone") or "").strip()
    if label and label.lower() != "nan":
        z = _match_drawn_zone(label, zone_names)
        if z:
            return z
    return coord_fn(row.get("end_x"), row.get("end_y"))


def _axy(p, x_depth, y_across):
    """Canonical (depth, across) -> the mplsoccer axes data coords for the pitch."""
    from mplsoccer import VerticalPitch
    return (y_across, x_depth) if isinstance(p, VerticalPitch) else (x_depth, y_across)


# straight deliveries that carry no meaningful swing (drawn as a straight arrow)
_STRAIGHT_DELIVERIES = frozenset({"", "short", "straight", "driven", "ground", "lofted", "long"})


def _swing_arrow(ax, p, x, y, ex, ey, dt, col, *, scale=13, lw=2.4):
    """Draw a corner/set-piece delivery as an arrow that swings the correct way and
    NEVER leaves the pitch. ``inswing`` bends toward the goal line, ``outswing`` bends
    away from it; the bend direction is derived from the ball's own path so it is
    automatically correct for either corner side (no left/right special-casing). The
    curve's control point is clamped inside the pitch, so the arc — which is bounded
    by the triangle (start, control, end) — can never bulge past the goal line or a
    touchline the way a fixed-``rad`` arc does for a target sitting on the goal line."""
    import math

    from matplotlib.patches import FancyArrowPatch
    from matplotlib.path import Path as _Path

    vd, va = ex - x, ey - y                              # chord in canonical (depth, across)
    clen = math.hypot(vd, va) or 1.0
    # unit perpendicular to the chord, oriented toward the goal line (higher depth)
    nd, na = va, -vd
    if nd < 0:
        nd, na = -nd, -na
    nnorm = math.hypot(nd, na) or 1.0
    nd, na = nd / nnorm, na / nnorm
    swing = str(dt).strip().lower()
    if swing in _STRAIGHT_DELIVERIES:
        mag = 0.0                                       # no swing -> straight arrow
    else:
        s = -1.0 if swing == "outswing" else 1.0        # inswing toward goal, outswing away
        mag = s * min(0.30 * clen, 14.0)
    cd = (x + ex) / 2 + mag * nd
    ca = (y + ey) / 2 + mag * na
    cd = min(max(cd, 74.0), 99.3)                       # keep the control point in the box view
    ca = min(max(ca, 1.0), 99.0)
    a, cc, b = _axy(p, x, y), _axy(p, cd, ca), _axy(p, ex, ey)
    path = _Path([a, cc, b], [_Path.MOVETO, _Path.CURVE3, _Path.CURVE3])
    ax.add_patch(FancyArrowPatch(path=path, arrowstyle="-|>", mutation_scale=scale,
                                 lw=lw, color=col, alpha=0.9, zorder=5))
    ax.scatter(*a, s=16, color=col, zorder=5)


def _zone_backdrop(ctx, p, df=None):
    """Draw the named corner zones as labelled colour blocks behind the arrows, with
    the share of deliveries landing in each zone under its name."""
    from matplotlib.patches import Rectangle
    import matplotlib.patheffects as pe
    ax = ctx.ax
    counts = {z[0]: 0 for z in _CORNER_ZONES}
    total = 0
    names = [z[0] for z in _CORNER_ZONES]
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            z = _resolved_zone(r, names, _corner_zone_of)   # sheet target_zone wins
            if z:
                counts[z] += 1; total += 1
    for name, x0, y0, x1, y1, col, alpha in _CORNER_ZONES:
        (ax0, ay0) = _axy(p, x0, y0)
        (ax1, ay1) = _axy(p, x1, y1)
        ax.add_patch(Rectangle((min(ax0, ax1), min(ay0, ay1)), abs(ax1 - ax0), abs(ay1 - ay0),
                               facecolor=col, alpha=alpha, edgecolor="#FFFFFF", lw=0.8, zorder=0.8))
        cx, cy = _axy(p, (x0 + x1) / 2, (y0 + y1) / 2)
        pct = (100 * counts[name] / total) if total else 0
        label = f"{name.replace(' ', chr(10), 1)}\n{pct:.0f}%"
        ax.text(cx, cy, label, ha="center", va="center", color="#FFFFFF",
                fontsize=max(6, ctx.style("label_size") - 2), fontweight="bold", zorder=3,
                path_effects=[pe.withStroke(linewidth=1.6, foreground="#0A0A0A")])


# ---------------------------------------------------------------- pitch charts
def _delivery_zones(ctx):
    from matplotlib.colors import to_rgba
    df = _df(ctx)
    if df.empty or "end_x" not in df.columns:
        return _no_data(ctx)
    p = _pitch(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    accent = ctx.controls.get("primary_color") or c["accent"]
    counts = {z[0]: 0 for z in _ZONES}
    total = 0
    names = [z[0] for z in _ZONES]
    for _, r in df.iterrows():
        z = _resolved_zone(r, names, _zone_of)          # sheet target_zone wins
        if z:
            counts[z] += 1; total += 1
    mx = max(counts.values()) or 1
    for name, x0, y0, x1, y1 in _ZONES:                 # (depth x0..x1, across y0..y1)
        n = counts[name]
        verts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        p.polygon([verts], ax=ax, fc=to_rgba(accent, 0.10 + 0.6 * n / mx),
                  ec=c["lines"], lw=0.8, zorder=0.9)
        pct = (100 * n / total) if total else 0
        p.annotate(f"{n}\n{pct:.0f}%", ((x0 + x1) / 2, (y0 + y1) / 2), ax=ax, ha="center",
                   va="center", color=c["text"], fontsize=ctx.style("label_size"),
                   fontweight="bold", zorder=3)
    ax.set_title(f"Delivery zones ({total})", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _delivery_trajectories(ctx):
    df = _df(ctx)
    if df.empty or "end_x" not in df.columns:
        return _no_data(ctx)
    p = _pitch(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    _zone_backdrop(ctx, p, df)                          # named zone blocks + landing share
    seen = {}
    for _, r in df.iterrows():
        x, y = _fnum(r.get("x")), _fnum(r.get("y"))
        ex, ey = _fnum(r.get("end_x")), _fnum(r.get("end_y"))
        if None in (x, y, ex, ey):
            continue
        dt = str(r.get("delivery_type") or "").strip().lower()
        col = _dcolor(ctx, dt)
        # swing the arc the way the ball moves (inswing toward goal, outswing away) and
        # keep it inside the pitch — direction and bounds handled by the helper.
        _swing_arrow(ax, p, x, y, ex, ey, dt, col)
        if dt and dt not in seen:
            seen[dt] = col
    sides = {str(s).strip().lower() for s in df.get("side", []) if str(s).strip()}
    tag = f" — {next(iter(sides)).title()} corner" if len(sides) == 1 else ""
    if seen and ctx.controls.get("legend", True):
        from matplotlib.lines import Line2D
        ax.legend(handles=[Line2D([0], [0], color=col, lw=3, label=dt.title())
                           for dt, col in seen.items()],
                  loc="lower center", ncol=min(4, len(seen)), facecolor=c["panel"],
                  edgecolor=c["grid"], labelcolor=c["text"], fontsize=ctx.style("legend_size"),
                  framealpha=0.9)
    ax.set_title(f"Delivery trajectories{tag}", color=c["text"],
                 fontsize=ctx.style("label_size") + 1)


def _heatmap(ctx, *, conceded=False):
    df = _df(ctx)
    if df.empty or "end_x" not in df.columns:
        return _no_data(ctx)
    if conceded:
        df = df[df["outcome"].astype(str).str.lower().isin(["unsuccessful", "threat", "goal", "shot"])]
        if df.empty:
            return _no_data(ctx, "No conceded deliveries")
    pts = _ends(df)
    if not pts:
        return _no_data(ctx)
    p = _pitch(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
    cmap = "Reds" if conceded else (getattr(ctx.theme, "heatmap_cmaps", ["Purples"])[0])
    try:
        p.kdeplot(xs, ys, ax=ax, fill=True, levels=60, thresh=0.05, cmap=cmap, alpha=0.85, zorder=1)
    except Exception:
        stat = p.bin_statistic(xs, ys, bins=(18, 12))
        p.heatmap(stat, ax=ax, cmap=cmap, alpha=0.85, zorder=1)
    p.scatter(xs, ys, ax=ax, s=18, color=c["text"], alpha=0.35, zorder=4)
    title = "Conceded delivery heatmap" if conceded else "Delivery landing heatmap"
    ax.set_title(f"{title} ({len(pts)})", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _trajectory_clusters(ctx):
    import numpy as np
    df = _df(ctx)
    rows = [r for _, r in df.iterrows()
            if None not in (_fnum(r.get("x")), _fnum(r.get("y")),
                            _fnum(r.get("end_x")), _fnum(r.get("end_y")))]
    if len(rows) < 3:
        return _no_data(ctx, "Need at least 3 deliveries to cluster")
    p = _pitch(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    X = np.array([[_fnum(r.get("x")), _fnum(r.get("y")), _fnum(r.get("end_x")),
                   _fnum(r.get("end_y"))] for r in rows], dtype=float)
    k = min(3, len(rows))
    rng = np.random.default_rng(7)
    C = X[rng.choice(len(X), k, replace=False)].astype(float)
    lab = np.zeros(len(X), dtype=int)
    for _ in range(20):
        lab = ((X[:, None, :] - C[None, :, :]) ** 2).sum(2).argmin(1)
        for j in range(k):
            if (lab == j).any():
                C[j] = X[lab == j].mean(0)
    palette = [c["accent"], c["accent_2"], c["success"], c["warning"], c["danger"]]
    for j in range(k):
        col = palette[j % len(palette)]
        for r in X[lab == j]:
            p.lines(r[0], r[1], r[2], r[3], ax=ax, color=col, lw=1.0, alpha=0.35, zorder=2)
        p.lines(C[j][0], C[j][1], C[j][2], C[j][3], ax=ax, color=col, lw=3.4, alpha=0.95,
                comet=True, zorder=3)
        p.scatter(C[j][2], C[j][3], ax=ax, s=90, color=col, edgecolors=c["bg"], lw=1.0, zorder=4)
    ax.set_title(f"Delivery route clusters ({k})", color=c["text"],
                 fontsize=ctx.style("label_size") + 1)


def _second_ball_map(ctx):
    df = _df(ctx)
    if df.empty or "end_x" not in df.columns:
        return _no_data(ctx)
    p = _pitch(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    nw = nl = 0
    for x, y, r in _ends(df):
        if bool(r.get("second_ball_win")):
            p.scatter(x, y, ax=ax, s=95, facecolor=c["success"], edgecolors=c["bg"], lw=1.0, zorder=5); nw += 1
        else:
            p.scatter(x, y, ax=ax, s=95, facecolor="none", edgecolors=c["danger"], lw=2.0, zorder=5); nl += 1
    ax.set_title(f"Second ball — won {nw} / lost {nl}", color=c["text"],
                 fontsize=ctx.style("label_size") + 1)


# ---------------------------------------------------------------- bar charts
def _fc_win_zone(ctx):
    df = _df(ctx)
    if df.empty or "first_contact_win" not in df.columns:
        return _no_data(ctx, "No first-contact data")
    agg = defaultdict(lambda: [0, 0])
    for _, r in df.iterrows():
        z = _zone_of(r.get("end_x"), r.get("end_y"))
        w = r.get("first_contact_win")
        if not z or w is None:
            continue
        agg[z][0] += 1 if bool(w) else 0
        agg[z][1] += 1
    if not agg:
        return _no_data(ctx, "No first-contact data")
    zones = sorted(agg, key=lambda z: agg[z][0] / agg[z][1], reverse=True)
    pct = [100 * agg[z][0] / agg[z][1] for z in zones]
    ax, c = ctx.ax, ctx.theme.colors
    _chart_axes(ctx)
    ax.barh(zones, pct, color=[c["success"] if v >= 50 else c["danger"] for v in pct])
    ax.set_xlim(0, 100); ax.invert_yaxis()
    ax.set_xlabel("First-contact win %", color=c["muted"])
    ax.set_title("First contact win by zone", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _target_zone_breakdown(ctx):
    df = _df(ctx)
    if df.empty:
        return _no_data(ctx)
    has_tz = "target_zone" in df.columns and df["target_zone"].astype(str).str.strip().ne("").any()
    labels = ([str(v).strip() for v in df["target_zone"].tolist()] if has_tz
              else [_zone_of(r.get("end_x"), r.get("end_y")) for _, r in df.iterrows()])
    cnt = Counter(v for v in labels if v)
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


def _taker_table(ctx):
    """Per-taker table: deliveries, inswing, outswing, left, right, success %."""
    df = _df(ctx)
    if df.empty or "taker" not in df.columns:
        return _no_data(ctx, "No taker data")
    stats: dict[str, dict] = {}
    for _, r in df.iterrows():
        t = str(r.get("taker") or "").strip()
        if not t:
            continue
        s = stats.setdefault(t, {"n": 0, "in": 0, "out": 0, "L": 0, "R": 0, "ok": 0})
        s["n"] += 1
        dt = str(r.get("delivery_type") or "").lower()
        s["in"] += dt == "inswing"; s["out"] += dt == "outswing"
        side = str(r.get("side") or "").lower()
        s["L"] += side == "left"; s["R"] += side == "right"
        s["ok"] += 1 if (str(r.get("outcome") or "").lower() == "successful"
                         or bool(r.get("goal")) or bool(r.get("shot"))) else 0
    if not stats:
        return _no_data(ctx, "No taker data")
    order = sorted(stats, key=lambda t: stats[t]["n"], reverse=True)[:12]
    ax, c = ctx.ax, ctx.theme.colors
    ax.set_facecolor(c.get("bg", c["panel"]))
    ax.axis("off")
    header = ["Taker", "Deliveries", "Inswing", "Outswing", "Left", "Right", "Success %"]
    cells = [[t, stats[t]["n"], stats[t]["in"], stats[t]["out"], stats[t]["L"], stats[t]["R"],
              f"{100 * stats[t]['ok'] / stats[t]['n']:.0f}%"] for t in order]
    tbl = ax.table(cellText=cells, colLabels=header, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(ctx.style("label_size"))
    tbl.scale(1, 1.5)
    for (row, _col), cell in tbl.get_celld().items():
        cell.set_edgecolor(c["grid"])
        if row == 0:
            cell.set_facecolor(c["accent"]); cell.set_text_props(color="#FFFFFF", fontweight="bold")
        else:
            cell.set_facecolor(c["panel"]); cell.set_text_props(color=c["text"])
    ax.set_title("Taker statistics", color=c["text"], fontsize=ctx.style("label_size") + 1, pad=14)


# ------------------------------------------------------------------ register
_EC = (ORIENT,)
_reg(sp_chart("sp_delivery_zones", "Delivery Zones", CAT_DELIVERY, "delivery_full",
              _delivery_zones, description="Where deliveries land across the box zones.",
              extra_controls=_EC))
_reg(sp_chart("sp_delivery_trajectories", "Delivery Trajectories", CAT_DELIVERY, "delivery_full",
              _delivery_trajectories, description="Start->landing arcs coloured by delivery type.",
              extra_controls=_EC))
_reg(sp_chart("sp_delivery_landing_heatmap", "Delivery Landing Heatmap", CAT_DELIVERY,
              "delivery_full", lambda ctx: _heatmap(ctx), description="Density of delivery landings.",
              extra_controls=_EC))
_reg(sp_chart("sp_trajectory_clusters", "Delivery Route Clusters", CAT_DELIVERY, "delivery_full",
              _trajectory_clusters, description="k-means clusters of delivery routes.",
              extra_controls=_EC))
_reg(sp_chart("sp_first_contact_win_zone", "First Contact Win by Zone", CAT_CONTACTS,
              "delivery_full", _fc_win_zone, description="Win % of the first contact per zone."))
_reg(sp_chart("sp_second_ball_map", "Second Ball Map", CAT_CONTACTS, "delivery_full",
              _second_ball_map, description="Where the second ball is won/lost.",
              extra_controls=_EC))
_reg(sp_chart("sp_target_zone_breakdown", "Target Zone Breakdown", CAT_DELIVERY,
              "delivery_full", _target_zone_breakdown, description="Delivery destination mix."))
_reg(sp_chart("sp_taker_profile", "Taker Profile", CAT_DELIVERY, "delivery_full",
              _taker_profile, description="Set pieces taken per player."))
_reg(sp_chart("sp_taker_table", "Taker Statistics Table", CAT_DELIVERY, "delivery_full",
              _taker_table, description="Per-taker deliveries, swing, side and success %."))
_reg(sp_chart("sp_defensive_structure", "Defensive Structure", CAT_DEFENSIVE, "delivery_full",
              _structure_avgs, description="Average attackers/defenders per box zone."))
_reg(sp_chart("sp_conceded_heatmap", "Conceded Delivery Heatmap", CAT_DEFENSIVE, "delivery_full",
              lambda ctx: _heatmap(ctx, conceded=True),
              description="Where dangerous deliveries repeatedly land (defensive).",
              extra_controls=_EC))
