"""The set-piece visualization inventory (Phase 9.2).

Importing this module registers every set-piece visualization into the shared
``visual_registry`` via the builders (which reuse the existing base classes,
pitch, layers, themes and export). Import is idempotent - Python caches the
module, so ``load_setpiece_visuals`` just triggers this import once.

Grouped exactly as the requirements: Occupancy, Delivery, Contacts, Defensive,
Movement, Outcomes, Penalties. Every entry maps a name to (builder, dataset kind)
so the visual layer is a thin declaration over the 9.1 data pipeline.
"""
from __future__ import annotations

from typing import Any

from fap.visuals.context import LayerContext
from fap.visuals.setpieces.builders import (
    CAT_CONTACTS, CAT_DEFENSIVE, CAT_DELIVERY, CAT_MOVEMENT, CAT_OCCUPANCY,
    CAT_OUTCOMES, CAT_PENALTIES, sp_arrows, sp_chart, sp_heatmap, sp_positions,
    sp_scatter, sp_zonegrid,
)

SETPIECE_IDS: list[str] = []


def _reg(cls: type) -> type:
    SETPIECE_IDS.append(cls.info.id)
    return cls


# =============================================================== Occupancy
_reg(sp_heatmap("sp_box_occupancy", "Box Occupancy Heatmap", CAT_OCCUPANCY, "occ_attack_density",
                description="Where attackers stand at delivery."))
_reg(sp_zonegrid("sp_zone_occupancy", "Zone Occupancy Map", CAT_OCCUPANCY, "occ_attack_density",
                 description="Average occupancy per box zone."))
_reg(sp_positions("sp_avg_positions", "Average Player Positions", CAT_OCCUPANCY, "occ_attack_avg",
                  hull=True, description="Mean position of each attacker."))
_reg(sp_heatmap("sp_player_density", "Player Density Map", CAT_OCCUPANCY, "occ_attack_density",
                overlay_points=True, description="Attacker density with markers."))
_reg(sp_heatmap("sp_crowded_box", "Crowded Box Map", CAT_OCCUPANCY, "occ_attack_density",
                description="Most contested areas of the box."))
_reg(sp_chart("sp_occupancy_timeline", "Occupancy Timeline", CAT_OCCUPANCY, "occ_timeline",
              lambda ctx: _bar(ctx, "label", "value", "Set pieces by match period")))

# =============================================================== Delivery
_reg(sp_heatmap("sp_delivery_heatmap", "Delivery Heatmap", CAT_DELIVERY, "delivery",
                description="Landing density of deliveries."))
_reg(sp_scatter("sp_delivery_scatter", "Delivery Scatter", CAT_DELIVERY, "delivery",
                description="Every delivery landing point."))
_reg(sp_arrows("sp_delivery_accuracy", "Delivery Accuracy Map", CAT_DELIVERY, "delivery_accuracy",
               description="Target vs actual landing (error vectors)."))
_reg(sp_scatter("sp_delivery_success", "Successful vs Failed Deliveries", CAT_DELIVERY,
                "delivery_success", split="success", description="Delivery outcome split."))
_reg(sp_scatter("sp_delivery_end", "Delivery End Locations", CAT_DELIVERY, "delivery",
                description="Delivery end locations."))
_reg(sp_arrows("sp_delivery_trajectory", "Delivery Trajectory", CAT_DELIVERY, "delivery_trajectory",
               curved=True, description="Delivery start to landing arcs."))

# =============================================================== Contacts
_reg(sp_scatter("sp_first_contact", "First Contact Map", CAT_CONTACTS, "first_contact",
                split="team", description="Who wins first contact and where."))
_reg(sp_scatter("sp_second_ball", "Second Ball Map", CAT_CONTACTS, "second_ball",
                split="won", description="Second-ball recoveries."))
_reg(sp_scatter("sp_shot_location", "Shot Location Map", CAT_CONTACTS, "shot",
                size_by="xg", description="Shots from set pieces, sized by xG."))
_reg(sp_scatter("sp_goal_location", "Goal Location Map", CAT_CONTACTS, "goals",
                color_role="success", description="Goals scored from set pieces."))
_reg(sp_scatter("sp_clearance", "Clearance Map", CAT_CONTACTS, "clearance",
                color_role="warning", description="Defensive clearances."))
_reg(sp_scatter("sp_flick_on", "Flick-on Map", CAT_CONTACTS, "flick_on",
                description="Headed flick-ons."))

# =============================================================== Defensive
_reg(sp_positions("sp_defensive_shape", "Defensive Shape", CAT_DEFENSIVE, "def_positions",
                  hull=True, description="Average defending positions."))
_reg(sp_positions("sp_marking", "Zonal vs Man Marking", CAT_DEFENSIVE, "def_positions",
                  description="Marking scheme by defender."))
_reg(sp_arrows("sp_marking_assignment", "Marking Assignment Map", CAT_DEFENSIVE,
               "marking_assignment", description="Defender to nearest attacker."))
_reg(sp_scatter("sp_blockers", "Blockers Map", CAT_DEFENSIVE, "blockers",
                color_role="danger", description="Blocking defenders."))
_reg(sp_scatter("sp_screens_def", "Screen Map", CAT_DEFENSIVE, "screens",
                description="Screen locations."))
_reg(sp_positions("sp_wall", "Wall Position", CAT_DEFENSIVE, "wall",
                  description="Free-kick wall positions."))
_reg(sp_positions("sp_defensive_line", "Defensive Line", CAT_DEFENSIVE, "def_positions",
                  line=True, description="Deepest defender / line height."))
_reg(sp_heatmap("sp_gk_start", "GK Starting Position", CAT_DEFENSIVE, "gk_start",
                description="Goalkeeper starting positions."))
_reg(sp_arrows("sp_gk_movement", "GK Movement", CAT_DEFENSIVE, "gk_move",
               description="Goalkeeper movement vectors."))
_reg(sp_heatmap("sp_gk_claim", "GK Claim Area", CAT_DEFENSIVE, "gk_start",
                description="Goalkeeper claim/command area."))

# =============================================================== Movement
_reg(sp_arrows("sp_movement_vectors", "Player Movement Vectors", CAT_MOVEMENT, "movement",
               description="Attacking movement before/at delivery."))
_reg(sp_arrows("sp_run_paths", "Run Paths", CAT_MOVEMENT, "movement",
               description="All attacking runs."))
_reg(sp_arrows("sp_screen_routes", "Screen Routes", CAT_MOVEMENT, "movement_screen",
               description="Screen/pick routes."))
_reg(sp_arrows("sp_decoy_runs", "Decoy Runs", CAT_MOVEMENT, "movement_decoy",
               description="Decoy runs."))
_reg(sp_arrows("sp_post_runs", "Near/Far Post Runs", CAT_MOVEMENT, "movement_post",
               description="Near and far post runs."))
_reg(sp_arrows("sp_edge_runs", "Edge Box Runs", CAT_MOVEMENT, "movement_edge",
               description="Runs to the edge of the box."))

# =============================================================== Outcomes
_reg(sp_zonegrid("sp_goal_probability", "Goal Probability Map", CAT_OUTCOMES, "shot",
                 weight="xg", description="xG-weighted danger by zone."))
_reg(sp_heatmap("sp_chance_creation", "Chance Creation Map", CAT_OUTCOMES, "shot",
                description="Shot creation density."))
_reg(sp_scatter("sp_xg_map", "xG Map", CAT_OUTCOMES, "shot", size_by="xg",
                description="Shots sized by xG."))
_reg(sp_arrows("sp_shot_assist", "Shot Assist Map", CAT_OUTCOMES, "shot_assist",
               description="Delivery to shot (assist) vectors."))
_reg(sp_zonegrid("sp_dangerous_zones", "Dangerous Zones", CAT_OUTCOMES, "shot", weight="xg",
                 description="Highest-threat box zones."))
_reg(sp_heatmap("sp_threat_map", "Threat Map", CAT_OUTCOMES, "threat",
                description="Overall set-piece threat."))

# =============================================================== Penalties
_reg(sp_chart("sp_pen_placement", "Penalty Placement Heatmap", CAT_PENALTIES, "pen_placement",
              lambda ctx: _goal_grid(ctx, "count")))
_reg(sp_chart("sp_gk_dive_heatmap", "Goalkeeper Dive Heatmap", CAT_PENALTIES, "pen_dive",
              lambda ctx: _dive_bars(ctx)))
_reg(sp_chart("sp_gk_dive_direction", "Goalkeeper Dive Direction", CAT_PENALTIES,
              "pen_dive_direction", lambda ctx: _dive_arrows(ctx)))
_reg(sp_chart("sp_pen_outcome", "Penalty Outcome Map", CAT_PENALTIES, "pen_outcome",
              lambda ctx: _bar(ctx, "outcome", "count", "Penalty outcomes")))
_reg(sp_chart("sp_pen_shooter", "Shooter Preference Map", CAT_PENALTIES, "pen_shooter",
              lambda ctx: _bar(ctx, "name", "conversion_pct", "Shooter conversion %")))
_reg(sp_chart("sp_pen_gk", "Goalkeeper Preference Map", CAT_PENALTIES, "pen_gk",
              lambda ctx: _bar(ctx, "name", "save_pct", "Goalkeeper save %")))

# --- Phase 9.4 penalty module extensions -------------------------------------
_reg(sp_chart("sp_pen_goal_heatmap", "Goal Heatmap", CAT_PENALTIES, "pen_goal",
              lambda ctx: _goal_grid(ctx, "count")))
_reg(sp_chart("sp_pen_miss_heatmap", "Miss Heatmap", CAT_PENALTIES, "pen_miss",
              lambda ctx: _goal_grid(ctx, "count")))
_reg(sp_chart("sp_pen_distribution", "Shot Distribution", CAT_PENALTIES, "pen_shots",
              lambda ctx: _goal_grid(ctx, "count")))
_reg(sp_chart("sp_gk_reach", "Goalkeeper Reach Map", CAT_PENALTIES, "pen_reach",
              lambda ctx: _reach_grid(ctx)))
_reg(sp_chart("sp_pen_clusters", "Placement Clusters", CAT_PENALTIES, "pen_clusters",
              lambda ctx: _zone_grid(ctx, "attempts")))
_reg(sp_chart("sp_pen_height", "Shot Height Distribution", CAT_PENALTIES, "pen_height",
              lambda ctx: _bar(ctx, "height", "count", "Shot height")))
_reg(sp_chart("sp_pen_direction", "Shot Direction Distribution", CAT_PENALTIES, "pen_direction",
              lambda ctx: _bar(ctx, "side", "count", "Shot direction")))
_reg(sp_chart("sp_pen_success_zones", "Success Zones", CAT_PENALTIES, "pen_zones",
              lambda ctx: _zone_grid(ctx, "conversion_pct")))
_reg(sp_chart("sp_pen_failure_zones", "Failure Zones", CAT_PENALTIES, "pen_zones",
              lambda ctx: _zone_grid(ctx, "conversion_pct", invert=True)))


# ------------------------------------------------------------------ chart artists
def _chart_axes(ctx: LayerContext) -> None:
    ax, c = ctx.ax, ctx.theme.colors
    ax.set_facecolor(c["panel"])
    ax.tick_params(colors=c["text"], labelsize=ctx.style("label_size"))
    for spine in ax.spines.values():
        spine.set_color(c["grid"])


def _bar(ctx: LayerContext, label_col: str, value_col: str, title: str) -> None:
    _chart_axes(ctx)
    df = ctx.df
    if df is None or df.empty or label_col not in df.columns or value_col not in df.columns:
        ctx.ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    color=ctx.theme.colors["muted"], transform=ctx.ax.transAxes)
        return
    labels = [str(v) for v in df[label_col].tolist()]
    values = [float(v) for v in df[value_col].tolist()]
    ctx.ax.bar(labels, values, color=ctx.controls.get("primary_color") or ctx.theme.colors["accent"])
    ctx.ax.set_title(title, color=ctx.theme.colors["text"], fontsize=ctx.style("label_size") + 1)
    ctx.ax.set_ylabel(value_col, color=ctx.theme.colors["muted"])
    for tick in ctx.ax.get_xticklabels():
        tick.set_rotation(30)
        tick.set_ha("right")


def _goal_grid(ctx: LayerContext, value: str) -> None:
    """3x3 goal grid shaded by penalty count per cell."""
    import numpy as np
    ax, c = ctx.ax, ctx.theme.colors
    ax.set_facecolor(c["panel"])
    ax.set_xlim(-0.2, 3.2)
    ax.set_ylim(-0.2, 3.4)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    # goal frame
    ax.plot([0, 0, 3, 3], [0, 3, 3, 0], color=c["lines"], lw=3)
    counts = np.zeros((3, 3))
    df = ctx.df
    if df is not None and not df.empty and {"gx", "gy"}.issubset(df.columns):
        for _, r in df.iterrows():
            gx, gy = int(r["gx"]), int(r["gy"])
            if 0 <= gx < 3 and 0 <= gy < 3:
                counts[gy, gx] += 1
    mx = counts.max() or 1
    accent = ctx.controls.get("primary_color") or c["accent"]
    from matplotlib.colors import to_rgba
    for gy in range(3):
        for gx in range(3):
            n = counts[gy, gx]
            ax.add_patch(_cell(gx, gy, to_rgba(accent, 0.15 + 0.75 * n / mx)))
            if n:
                ax.text(gx + 0.5, gy + 0.5, str(int(n)), ha="center", va="center",
                        color=c["text"], fontweight="bold", fontsize=ctx.style("label_size") + 2)
    ax.set_title("Penalty placement", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _cell(gx: int, gy: int, color):
    from matplotlib.patches import Rectangle
    return Rectangle((gx + 0.03, gy + 0.03), 0.94, 0.94, color=color, ec="none")


def _zone_grid(ctx: LayerContext, value: str, invert: bool = False) -> None:
    """3x3 goal grid shaded by a per-cell value (attempts or conversion %).
    ``invert`` highlights the LOW-value cells (failure zones)."""
    import numpy as np
    from matplotlib.colors import to_rgba
    ax, c = ctx.ax, ctx.theme.colors
    ax.set_facecolor(c["panel"]); ax.set_xlim(-0.2, 3.2); ax.set_ylim(-0.2, 3.4)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.plot([0, 0, 3, 3], [0, 3, 3, 0], color=c["lines"], lw=3)
    vals = np.zeros((3, 3))
    labels = np.zeros((3, 3))
    df = ctx.df
    if df is not None and not df.empty and {"gx", "gy", value}.issubset(df.columns):
        for _, r in df.iterrows():
            gx, gy = int(r["gx"]), int(r["gy"])
            if 0 <= gx < 3 and 0 <= gy < 3:
                v = float(r[value]) if r[value] is not None else 0.0
                vals[gy, gx] = (100 - v) if invert else v
                labels[gy, gx] = float(r.get("conversion_pct", r[value]) or 0.0)
    mx = vals.max() or 1
    accent = ctx.controls.get("primary_color") or (c["danger"] if invert else c["success"])
    for gy in range(3):
        for gx in range(3):
            ax.add_patch(_cell(gx, gy, to_rgba(accent, 0.12 + 0.8 * vals[gy, gx] / mx)))
            if vals[gy, gx]:
                txt = f"{int(labels[gy, gx])}%" if value == "conversion_pct" else f"{int(vals[gy, gx])}"
                ax.text(gx + 0.5, gy + 0.5, txt, ha="center", va="center",
                        color=c["text"], fontweight="bold", fontsize=ctx.style("label_size") + 1)
    ax.set_title("Failure zones" if invert else "Zones", color=c["text"],
                 fontsize=ctx.style("label_size") + 1)


def _reach_grid(ctx: LayerContext) -> None:
    """Goalkeeper reach/dive endpoints plotted across the goal mouth."""
    ax, c = ctx.ax, ctx.theme.colors
    ax.set_facecolor(c["panel"]); ax.set_xlim(-1.0, 4.0); ax.set_ylim(-0.3, 3.4)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.plot([0, 0, 3, 3], [0, 3, 3, 0], color=c["lines"], lw=3)
    df = ctx.df
    if df is None or df.empty or "gx" not in df.columns:
        ax.text(1.5, 1.5, "No data", ha="center", va="center", color=c["muted"])
        return
    for _, r in df.iterrows():
        saved = bool(r.get("saved"))
        ax.scatter([float(r["gx"]) * 1.5], [float(r.get("gy", 1)) * 1.5],
                   s=140, color=c["success"] if saved else c["danger"],
                   edgecolors=c["lines"], alpha=0.8, zorder=5)
    ax.set_title("Goalkeeper reach", color=c["text"], fontsize=ctx.style("label_size") + 1)


def _dive_bars(ctx: LayerContext) -> None:
    _bar(ctx, "direction", "count", "Goalkeeper dives")


def _dive_arrows(ctx: LayerContext) -> None:
    ax, c = ctx.ax, ctx.theme.colors
    ax.set_facecolor(c["panel"])
    ax.set_xlim(-1.4, 1.4); ax.set_ylim(-1.2, 1.2)
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    df = ctx.df
    if df is None or df.empty:
        ax.text(0, 0, "No data", ha="center", va="center", color=c["muted"])
        return
    mx = max((float(r.get("count", 0)) for _, r in df.iterrows()), default=1) or 1
    accent = ctx.controls.get("primary_color") or c["accent"]
    for _, r in df.iterrows():
        dx, dy, n = float(r.get("dx", 0)), float(r.get("dy", 0)), float(r.get("count", 0))
        if dx == 0 and dy == 0:
            ax.scatter([0], [0], s=200 * n / mx + 30, color=accent, zorder=5)
        else:
            ax.annotate("", xy=(dx, dy), xytext=(0, 0),
                        arrowprops=dict(arrowstyle="-|>", color=accent,
                                        lw=1 + 4 * n / mx))
        ax.text(dx * 1.15, dy * 1.15, f"{r.get('direction','')} ({int(n)})",
                ha="center", va="center", color=c["text"], fontsize=ctx.style("label_size"))
    ax.set_title("Dive direction", color=c["text"], fontsize=ctx.style("label_size") + 1)
