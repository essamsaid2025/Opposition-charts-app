"""Delivery-structure set-piece charts — ported from the standalone Set-Pieces app.

Render straight from a rich set-piece export (delivery landing, delivery type,
target zone, first/second-ball wins, near/far-post player & defender counts,
taker) — NO manual position/contact tagging. They consume the ``delivery_full``
dataset (one row per delivery, built in ``fap.setpieces.build_frames``).

Pitch charts use a shared VERTICAL penalty-box view (goal at the top, attacking
upward), matching the standalone app: canonical ``x`` (depth, attacking->100) is
the vertical axis and canonical ``y`` (across the goal) is the horizontal axis.
"""
from __future__ import annotations

from collections import Counter

from fap.visuals.setpieces.builders import (CAT_CONTACTS, CAT_DEFENSIVE, CAT_DELIVERY,
                                            sp_chart)
from fap.visuals.setpieces.library import _chart_axes, _reg

# named delivery zones inside the box (canonical x depth, y across; 0-100).
_ZONES = (
    ("Near post", 94.2, 21.0, 100.0, 39.0),
    ("Far post", 94.2, 61.0, 100.0, 79.0),
    ("6-yard centre", 94.2, 39.0, 100.0, 61.0),
    ("Penalty spot", 88.0, 36.0, 94.2, 64.0),
    ("Box left", 83.0, 21.0, 94.2, 36.0),
    ("Box right", 83.0, 64.0, 94.2, 79.0),
    ("Edge of box", 74.0, 21.0, 83.0, 79.0),
)
_DELIVERY_COLORS = {
    "inswing": "accent", "outswing": "accent_2", "straight": "success",
    "driven": "warning", "short": "grey", "lofted": "bar", "ground": "muted",
}


def _zone_of(x, y):
    fx, fy = _fnum(x), _fnum(y)
    if fx is None or fy is None:
        return ""
    for name, x0, y0, x1, y1 in _ZONES:
        if x0 <= fx <= x1 and y0 <= fy <= y1:
            return name
    return ""


def _fnum(v):
    try:
        if v is None or str(v).strip() in ("", "nan"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


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


# ---- shared VERTICAL penalty-box view (goal at top) -------------------------
def _vbox(ctx):
    """Draw the attacking penalty area vertically (goal at top). Returns ``T`` that
    maps canonical ``(x_depth, y_across)`` to screen ``(x, y)`` = ``(across, depth)``."""
    from matplotlib.patches import Arc, Rectangle
    ax, c = ctx.ax, ctx.theme.colors
    line = c["lines"]
    ax.set_facecolor(c.get("bg", c["panel"]))
    # penalty area + six-yard + goal, drawn in (across, depth) screen coords
    ax.add_patch(Rectangle((21.1, 83.0), 57.8, 17.0, fill=False, edgecolor=line, lw=1.6))
    ax.add_patch(Rectangle((36.8, 94.5), 26.4, 5.5, fill=False, edgecolor=line, lw=1.6))
    ax.plot([44.2, 55.8], [100.0, 100.0], color=line, lw=4.0, solid_capstyle="butt")
    ax.add_patch(Arc((50.0, 88.5), 18.0, 12.0, theta1=200, theta2=340, color=line, lw=1.4))
    ax.scatter([50.0], [88.5], s=10, color=line, zorder=3)
    ax.set_xlim(14.0, 86.0)
    ax.set_ylim(73.0, 101.5)
    ax.set_aspect("equal")
    ax.axis("off")
    return lambda cx, cy: (cy, cx)


def _ends(df):
    """(across, depth) screen points for delivery landings + the source rows."""
    pts = []
    for _, r in df.iterrows():
        x, y = _fnum(r.get("end_x")), _fnum(r.get("end_y"))
        if x is not None and y is not None:
            pts.append((y, x, r))                       # (screen_x=across, screen_y=depth, row)
    return pts


# ---------------------------------------------------------------- pitch charts
def _delivery_zones(ctx):
    from matplotlib.colors import to_rgba
    from matplotlib.patches import Rectangle
    df = _df(ctx)
    if df.empty or "end_x" not in df.columns:
        return _no_data(ctx)
    _vbox(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    accent = ctx.controls.get("primary_color") or c["accent"]
    counts = {z[0]: 0 for z in _ZONES}
    total = 0
    for _, r in df.iterrows():
        z = _zone_of(r.get("end_x"), r.get("end_y"))
        if z:
            counts[z] += 1; total += 1
    mx = max(counts.values()) or 1
    for name, x0, y0, x1, y1 in _ZONES:                 # (depth x0..x1, across y0..y1)
        n = counts[name]
        ax.add_patch(Rectangle((y0, x0), y1 - y0, x1 - x0,
                               facecolor=to_rgba(accent, 0.10 + 0.6 * n / mx),
                               edgecolor=c["lines"], lw=0.8, zorder=2))
        pct = (100 * n / total) if total else 0
        ax.text((y0 + y1) / 2, (x0 + x1) / 2, f"{n}\n{pct:.0f}%", ha="center", va="center",
                fontsize=ctx.style("label_size"), color=c["text"], fontweight="bold", zorder=3)
    ax.set_title(f"Delivery zones ({total})", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _delivery_trajectories(ctx):
    df = _df(ctx)
    if df.empty or "end_x" not in df.columns:
        return _no_data(ctx)
    T = _vbox(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    seen = {}
    for _, r in df.iterrows():
        x, y = _fnum(r.get("x")), _fnum(r.get("y"))
        ex, ey = _fnum(r.get("end_x")), _fnum(r.get("end_y"))
        if None in (x, y, ex, ey):
            continue
        dt = str(r.get("delivery_type") or "").strip().lower()
        col = _dcolor(ctx, dt)
        sx, sy = T(x, y); tx, ty = T(ex, ey)
        ax.annotate("", xy=(tx, ty), xytext=(sx, sy),
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=1.8, alpha=0.75,
                                    connectionstyle="arc3,rad=0.12"))
        if dt and dt not in seen:
            seen[dt] = col
    if seen and ctx.controls.get("legend", True):
        from matplotlib.lines import Line2D
        ax.legend(handles=[Line2D([0], [0], color=col, lw=3, label=dt.title())
                           for dt, col in seen.items()],
                  loc="lower center", ncol=min(4, len(seen)), facecolor=c["panel"],
                  edgecolor=c["grid"], labelcolor=c["text"], fontsize=ctx.style("legend_size"))
    ax.set_title("Delivery trajectories", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _heatmap(ctx, *, conceded=False):
    import numpy as np
    from scipy.ndimage import gaussian_filter
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
    T = _vbox(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    xs = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts])
    xe = np.linspace(14, 86, 44); ye = np.linspace(73, 101.5, 24)
    H, _, _ = np.histogram2d(xs, ys, bins=[xe, ye])
    H = gaussian_filter(H, sigma=1.4)
    cmap = "Reds" if conceded else (ctx.theme.heatmap_cmaps[0] if getattr(ctx.theme, "heatmap_cmaps", None) else "Purples")
    ax.imshow(H.T, extent=[14, 86, 73, 101.5], origin="lower", cmap=cmap, alpha=0.85,
              aspect="auto", zorder=1)
    _vbox(ctx)                                           # redraw lines on top
    ax.scatter(xs, ys, s=14, color=c["text"], alpha=0.35, zorder=4)
    title = "Conceded delivery heatmap" if conceded else "Delivery landing heatmap"
    ax.set_title(f"{title} ({len(pts)})", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _trajectory_clusters(ctx):
    import numpy as np
    df = _df(ctx)
    rows = [r for _, r in df.iterrows()
            if None not in (_fnum(r.get("x")), _fnum(r.get("y")),
                            _fnum(r.get("end_x")), _fnum(r.get("end_y")))]
    if len(rows) < 3:
        return _no_data(ctx, "Need ≥3 deliveries to cluster")
    T = _vbox(ctx)
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
        for r in (X[lab == j]):
            sx, sy = T(r[0], r[1]); tx, ty = T(r[2], r[3])
            ax.annotate("", xy=(tx, ty), xytext=(sx, sy),
                        arrowprops=dict(arrowstyle="-", color=col, lw=1.0, alpha=0.4))
        sx, sy = T(C[j][0], C[j][1]); tx, ty = T(C[j][2], C[j][3])
        ax.annotate("", xy=(tx, ty), xytext=(sx, sy),
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=3.2,
                                    connectionstyle="arc3,rad=0.12"))
    ax.set_title(f"Delivery route clusters ({k})", color=c["text"],
                 fontsize=ctx.style("label_size") + 1)


def _second_ball_map(ctx):
    df = _df(ctx)
    if df.empty or "end_x" not in df.columns:
        return _no_data(ctx)
    _vbox(ctx)
    ax, c = ctx.ax, ctx.theme.colors
    nw = nl = 0
    for sx, sy, r in _ends(df):
        if bool(r.get("second_ball_win")):
            ax.scatter([sx], [sy], s=90, facecolor=c["success"], edgecolor=c["bg"], lw=1.0, zorder=5); nw += 1
        else:
            ax.scatter([sx], [sy], s=90, facecolor="none", edgecolor=c["danger"], lw=2.0, zorder=5); nl += 1
    ax.set_title(f"Second ball — won {nw} / lost {nl}", color=c["text"],
                 fontsize=ctx.style("label_size") + 1)


# ---------------------------------------------------------------- bar charts
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
    labels = ([str(v).strip() for v in df["target_zone"].tolist()] if has_tz
              else [_zone_of(r.get("end_x"), r.get("end_y")) for _, r in df.iterrows()])
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
_reg(sp_chart("sp_delivery_trajectories", "Delivery Trajectories", CAT_DELIVERY, "delivery_full",
              _delivery_trajectories, description="Start→landing arcs coloured by delivery type."))
_reg(sp_chart("sp_delivery_landing_heatmap", "Delivery Landing Heatmap", CAT_DELIVERY,
              "delivery_full", lambda ctx: _heatmap(ctx), description="Density of delivery landings."))
_reg(sp_chart("sp_trajectory_clusters", "Delivery Route Clusters", CAT_DELIVERY, "delivery_full",
              _trajectory_clusters, description="k-means clusters of delivery routes."))
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
_reg(sp_chart("sp_conceded_heatmap", "Conceded Delivery Heatmap", CAT_DEFENSIVE, "delivery_full",
              lambda ctx: _heatmap(ctx, conceded=True),
              description="Where dangerous deliveries repeatedly land (defensive)."))
