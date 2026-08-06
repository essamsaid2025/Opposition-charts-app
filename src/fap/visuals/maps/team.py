"""Team analysis plugins."""
from __future__ import annotations

from typing import Sequence

import pandas as pd

from fap.core.plugin import PluginInfo
from fap.visuals import analysis as A
from fap.visuals.base import PitchVisualization, visual_registry
from fap.visuals.context import LayerContext
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.maps._builders import _primary, _secondary, density_map

_C = "Team"

IN_POSSESSION = ("pass", "carry", "dribble", "cross", "shot")
OUT_POSSESSION = ("duel", "recovery", "interception", "clearance",
                  "tackle", "block", "pressure")


def _avg_positions(df: pd.DataFrame, kinds: tuple[str, ...] = ()) -> pd.DataFrame:
    d = df if not kinds else df[df["event_type"].str.lower().isin(kinds)]
    d = d[d["player"].str.strip().ne("")]
    return d.groupby("player").agg(
        x=("x", "mean"), y=("y", "mean"), count=("x", "size"),
        jersey_number=("jersey_number", "first")).reset_index()


class _ShapeBase(PitchVisualization):
    kinds: tuple[str, ...] = ()
    with_hull = False
    control_groups = ("titles", "pitch", "markers", "colors", "legend",
                      "text", "images", "export", "layout")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        nodes = _avg_positions(ctx.df, self.kinds)
        if nodes.empty:
            return []
        out: list[Layer] = []
        if self.with_hull and len(nodes) >= 3:
            out.append(layer_registry.create("convex_hull", df=nodes,
                                             color=_primary(ctx)))
        out.append(layer_registry.create("player_markers", df=nodes,
                                         color=_secondary(ctx), show_names=True))
        return out


for vid, vname, kinds, hull, desc in (
    ("average_positions", "Average Positions", (), False,
     "Mean event location per player."),
    ("average_shape", "Average Shape", (), True,
     "Average positions with team convex hull."),
    ("in_possession_shape", "In Possession Shape", IN_POSSESSION, True,
     "Shape from on-ball events."),
    ("out_possession_shape", "Out of Possession Shape", OUT_POSSESSION, True,
     "Shape from defensive events."),
    ("team_convex_hull", "Convex Hull", (), True, "Team occupation hull."),
):
    cls = type(f"Viz_{vid}", (_ShapeBase,), {
        "info": PluginInfo(id=vid, name=vname, category=_C, description=desc),
        "kinds": kinds, "with_hull": hull})
    visual_registry.register(cls)


@visual_registry.register
class TeamVoronoi(PitchVisualization):
    info = PluginInfo(id="team_voronoi", name="Voronoi / Space Control", category=_C,
                      description="Space controlled from average positions.")
    control_groups = ("titles", "pitch", "markers", "colors", "legend",
                      "text", "images", "export", "layout")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        nodes = _avg_positions(ctx.df)
        if len(nodes) < 4:
            return []
        return [
            layer_registry.create("voronoi", df=nodes, color=_primary(ctx)),
            layer_registry.create("player_markers", df=nodes,
                                  color=_secondary(ctx), show_names=True),
        ]


@visual_registry.register
class SpaceOccupation(TeamVoronoi):
    info = PluginInfo(id="space_occupation", name="Space Occupation", category=_C,
                      description="Voronoi space control with occupation density.")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        return [layer_registry.create("heatmap", heat_alpha=0.35)] + \
            list(super().layers(ctx))


def _avg_positions_by_team(df: pd.DataFrame) -> pd.DataFrame:
    """Average position per player, keeping their team (for team-coloured control)."""
    d = df[df["player"].astype(str).str.strip().ne("")]
    if "team" in d.columns:
        d = d.assign(team=d["team"].astype(str).str.strip())
    else:
        d = d.assign(team="")
    nodes = d.groupby("player").agg(
        x=("x", "mean"), y=("y", "mean"), count=("x", "size"),
        jersey_number=("jersey_number", "first"),
        team=("team", "first")).reset_index()
    return nodes.dropna(subset=["x", "y"])


def _short_name(name: str) -> str:
    parts = str(name).split()
    return parts[-1] if parts else ""


@visual_registry.register
class PlayerVoronoi(PitchVisualization):
    """Space control from average positions, done properly for a full match.

    With TWO teams present the pitch is tessellated once and every cell is tinted
    by the team that controls it (home vs away), with team-coloured player dots and
    jersey numbers - the classic pitch-control read. With a single team it falls
    back to a distinct colour per player. Full-name labels are off by default
    (they overlap badly on 20+ players); the Text panel's "Show labels" adds tidy
    surnames on demand."""
    info = PluginInfo(id="player_voronoi", name="Player Voronoi (Space Control)",
                      category=_C,
                      description="Territory each team/player controls from average "
                                  "positions - team-coloured for a full match.")
    control_groups = ("titles", "pitch", "markers", "colors", "legend",
                      "text", "images", "export", "layout")

    def layers(self, ctx: LayerContext) -> Sequence[Layer]:
        import matplotlib
        from matplotlib.colors import to_hex
        nodes = _avg_positions_by_team(ctx.df)
        if len(nodes) < 4:                                # Voronoi needs >= 4 sites
            return []
        c = ctx.theme.colors
        teams = [t for t in nodes["team"].value_counts().index.tolist() if t]
        out: list[Layer] = []

        if len(teams) >= 2:                               # --- two teams: colour by team
            a, b = teams[0], teams[1]
            col_a = ctx.controls.get("primary_color") or c["accent"]
            col_b = ctx.controls.get("fail_color") or c["accent_2"]
            nodes = nodes[nodes["team"].isin([a, b])].reset_index(drop=True)
            if len(nodes) < 4:
                return []
            team_col = {a: col_a, b: col_b}
            colors = [team_col[t] for t in nodes["team"]]
            out.append(layer_registry.create("voronoi", df=nodes, colors=colors, fill_alpha=0.45))
            for team in (a, b):                           # team-coloured dots + numbers
                sub = nodes[nodes["team"] == team]
                out.append(layer_registry.create("player_markers", df=sub, color=team_col[team]))
            ctx.legend.add(str(a), kind="patch", color=col_a)
            ctx.legend.add(str(b), kind="patch", color=col_b)
        else:                                             # --- one team: colour per player
            cmap = matplotlib.colormaps.get_cmap("tab20")
            colors = [to_hex(cmap((i % 20) / 19.0)) for i in range(len(nodes))]
            out.append(layer_registry.create("voronoi", df=nodes, colors=colors, fill_alpha=0.4))
            out.append(layer_registry.create("player_markers", df=nodes, color=_secondary(ctx)))

        if ctx.controls.get("show_labels"):               # opt-in tidy surnames
            out.append(layer_registry.create(
                "labels", df=nodes.assign(_short=nodes["player"].map(_short_name)),
                column="_short"))
        return out


density_map("occupation_map", "Occupation Map", lambda df, ctx: df, category=_C)
density_map("territory_map", "Territory Map", lambda df, ctx: A.movement(df),
            category=_C, kind="hexbin")
