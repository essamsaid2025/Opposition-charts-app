"""Match Analysis library tests: registry completeness, universal render
smoke test over EVERY plugin, controls, filters, helpers, interactivity,
report integration."""
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from fap.core.types import RenderContext
from fap.pipeline.filters import FilterSet
from fap.pipeline.pipeline import DataPipeline
from fap.providers.base import RawDataset
from fap.themes import ThemeManager
from fap.visuals import Renderer, analysis as A, visual_registry
from fap.visuals.base import load_builtin_visuals
from fap.visuals.interaction import SelectionModel

load_builtin_visuals()
THEMES = ThemeManager("assets/themes")


def rich_dataset(n: int = 600, seed: int = 11) -> pd.DataFrame:
    """Synthetic match data exercising every plugin family, run through the
    real pipeline so every derived column exists."""
    rng = np.random.default_rng(seed)
    events = rng.choice(["pass", "carry", "shot", "cross", "dribble", "recovery",
                         "interception", "tackle", "clearance", "duel", "block",
                         "pressure", "save", "claim", "punch", "goal_kick"],
                        n, p=[.38, .12, .05, .04, .03, .06, .05, .05, .04, .05,
                              .03, .05, .02, .01, .01, .01])
    players = [f"Player {i}" for i in range(1, 12)] + ["Keeper"]
    x = rng.uniform(2, 98, n)
    df = pd.DataFrame({
        "event_type": events,
        "x": x, "y": rng.uniform(2, 98, n),
        "end_x": np.clip(x + rng.normal(12, 18, n), 0, 100),
        "end_y": rng.uniform(0, 100, n),
        "player": rng.choice(players, n),
        "receiver": rng.choice(players, n),
        "team": rng.choice(["Lions", "Rivals"], n, p=[0.7, 0.3]),
        "opponent": "Rivals",
        "position": rng.choice(["GK", "CB", "CM", "ST", "LW"], n),
        "jersey_number": rng.integers(1, 30, n),
        "minute": np.sort(rng.integers(0, 94, n)),
        "second": rng.integers(0, 60, n),
        "period": rng.choice([1, 2], n),
        "match_id": rng.choice(["m1", "m2"], n),
        "competition": "League", "season": "2026",
        "venue": rng.choice(["home", "away"], n),
        "outcome": rng.choice(["successful", "unsuccessful", ""], n, p=[.6, .3, .1]),
        "shot_result": np.where(events == "shot",
                                rng.choice(["Goal", "Saved", "Off Target", "Blocked"], n),
                                ""),
        "shot_xg": np.where(events == "shot", rng.uniform(0.02, 0.8, n), np.nan),
        "pass_length": np.where(np.isin(events, ["pass", "cross"]),
                                rng.uniform(4, 45, n), np.nan),
        "under_pressure": rng.choice([True, False], n, p=[0.25, 0.75]),
        "key_pass": (events == "pass") & (rng.random(n) < 0.06),
        "assist": (events == "pass") & (rng.random(n) < 0.02),
        "sequence_id": rng.choice([f"s{i}" for i in range(1, 40)], n),
        "sub_event": rng.choice(["", "aerial duel", "ground duel"], n),
        "play_pattern": rng.choice(["regular play", "from goal kick", "counter"], n),
        "body_part": rng.choice(["right foot", "left foot", "head"], n),
    })
    return DataPipeline().run(RawDataset(frame=df))


DF = rich_dataset()
ALL_IDS = visual_registry.ids()


# ---------------------------------------------------------------- completeness
SPEC_IDS = {
    # passing
    "pass_map", "successful_passes", "failed_passes", "forward_passes",
    "backward_passes", "sideways_passes", "progressive_passes",
    "line_breaking_passes", "vertical_passes", "switches_of_play", "long_passes",
    "short_passes", "crosses_map", "key_passes", "assists_map", "expected_assists",
    "pass_length_distribution", "pass_angle_distribution", "pass_direction_map",
    "pass_density", "pass_heatmap", "pass_network", "weighted_passing_network",
    "passing_connections", "passing_lanes", "passing_options", "pass_origin_zones",
    "pass_destination_zones", "final_third_entries", "penalty_area_entries",
    "zone14_entries", "half_space_entries", "xt_pass_map",
    # progression
    "carry_map", "progressive_carries", "carry_network", "driving_runs",
    "ball_progression", "ball_movement", "progressive_distance", "ball_advancement",
    # attacking
    "shot_map", "shot_ending_map", "shot_density", "shot_heatmap", "shot_timeline",
    "goals_map", "shots_on_target", "shots_off_target", "blocked_shots",
    "big_chances", "expected_goals_map", "post_shot_xg", "goal_probability",
    "goal_mouth_map", "shot_angle_chart", "shot_distance_chart", "shot_body_part",
    "shot_assist_map", "expected_threat_map",
    # defensive
    "defensive_actions", "interceptions", "recoveries", "tackles", "blocks",
    "pressures", "counter_pressures", "ball_wins", "ball_losses", "clearances",
    "aerial_duels", "ground_duels", "defensive_heatmap", "pressing_heatmap",
    "recovery_heatmap", "turnovers_map", "counterpress_recoveries",
    # goalkeeper
    "gk_pass_map", "gk_distribution_length", "launch_map", "save_map",
    "save_zones", "gk_claims", "gk_punches", "sweeper_actions", "gk_positioning",
    # team
    "average_positions", "average_shape", "in_possession_shape",
    "out_possession_shape", "occupation_map", "territory_map", "team_convex_hull",
    "team_voronoi", "space_occupation", "team_width", "team_depth",
    "team_compactness",
    # build-up
    "goal_kick_buildup", "first_phase_buildup", "second_phase_buildup",
    "third_phase_buildup", "progression_routes", "exit_routes", "press_resistance",
    # transitions
    "fast_attacks", "counter_attacks", "counter_press_map", "transition_heatmap",
    "transition_timeline",
    # possession
    "possession_chains", "attacking_sequences", "passing_sequences",
    "sequence_builder", "sequence_timeline",
    # zones
    "zone14_map", "half_spaces_map", "penalty_area_map", "final_third_map",
    "wide_areas_map", "crossing_zones_map", "golden_zone_map", "custom_zones",
}


def test_full_library_registered():
    missing = SPEC_IDS - set(ALL_IDS)
    assert not missing, f"missing plugins: {sorted(missing)}"
    assert len(ALL_IDS) >= 120


# ---------------------------------------------------------------- universal render
@pytest.mark.parametrize("viz_id", ALL_IDS)
def test_every_visualization_renders(viz_id):
    viz = visual_registry.create(viz_id)
    ctx = RenderContext(df=DF, theme=THEMES.get("opta_light"),
                        controls={"title": viz.info.name}, meta={})
    fig = Renderer().render(viz, ctx)
    assert fig.axes and len(fig.axes[0].get_children()) > 0
    plt.close(fig)


@pytest.mark.parametrize("viz_id", ["pass_map", "shot_map", "defensive_heatmap",
                                    "pass_network", "team_voronoi"])
def test_key_visuals_render_in_dark_theme_and_export(viz_id):
    from fap.visuals import ExportEngine
    viz = visual_registry.create(viz_id)
    ctx = RenderContext(df=DF, theme=THEMES.get("tv_broadcast"),
                        controls={"title": "T", "view": "full"}, meta={})
    fig = Renderer().render(viz, ctx)
    result = ExportEngine().export(fig, viz_id, fmt="png", dpi="screen",
                                   transparent=True)
    assert result.data[:8] == b"\x89PNG\r\n\x1a\n"
    plt.close(fig)


# ---------------------------------------------------------------- controls
def test_every_plugin_declares_professional_controls():
    for viz_id in ALL_IDS:
        viz = visual_registry.create(viz_id)
        keys = [c.key for c in viz.all_controls]
        assert len(keys) == len(set(keys)), f"duplicate control keys in {viz_id}"
        assert "title" in keys and "legend" in keys, viz_id
        assert viz.info.name and viz.info.category, viz_id


def test_arrow_maps_expose_arrow_and_color_controls():
    keys = [c.key for c in visual_registry.create("pass_map").all_controls]
    for expected in ("arrow_width", "arrow_head", "arrow_curve", "primary_color",
                     "fail_color", "export_dpi", "max_events", "pitch_spec", "view"):
        assert expected in keys


# ---------------------------------------------------------------- filters
def test_new_filter_dimensions():
    assert set(FilterSet(positions=("GK",)).apply(DF)["position"]) == {"GK"}
    assert set(FilterSet(venues=("home",)).apply(DF)["venue"]) == {"home"}
    pressured = FilterSet(pressure_state="under_pressure").apply(DF)
    assert pressured["under_pressure"].all() and len(pressured) < len(DF)
    calm = FilterSet(pressure_state="no_pressure").apply(DF)
    assert (~calm["under_pressure"]).all()


def test_score_state_derived_and_filterable():
    states = set(DF["score_state"].unique())
    assert states <= {"winning", "drawing", "losing"} and len(states) >= 2
    winning = FilterSet(score_states=("winning",)).apply(DF)
    assert set(winning["score_state"]) == {"winning"}


def test_filters_flow_through_renderer():
    viz = visual_registry.create("pass_map")
    ctx = RenderContext(df=DF, theme=THEMES.get("opta_light"),
                        controls={"title": ""},
                        meta={"filters": {"players": ["Player 1"]}})
    fig = Renderer().render(viz, ctx)      # renders the filtered subset
    plt.close(fig)


# ---------------------------------------------------------------- analysis helpers
def test_analysis_helpers_sanity():
    p = A.passes(DF)
    prog = A.progressive(p)
    assert len(prog) and ((100 - prog["end_x"]) <= 0.75 * (100 - prog["x"])).all()
    assert (A.switches(p)["end_y"] - A.switches(p)["y"]).abs().min() >= 40
    assert A.xt_value(pd.Series([95.0]), pd.Series([50.0]))[0] > \
        A.xt_value(pd.Series([10.0]), pd.Series([50.0]))[0]
    nodes, edges = A.pass_network(DF)
    assert {"player", "x", "y", "count"} <= set(nodes.columns)
    entries = A.entries_into(DF, A.PENALTY_AREA)
    assert A.in_zone(entries["end_x"], entries["end_y"], A.PENALTY_AREA).all()


# ---------------------------------------------------------------- interactivity
def test_selection_cross_highlighting():
    model = SelectionModel(players=("Player 1",), source_viz="pass_map")
    restored = SelectionModel.from_dict(model.to_dict())
    assert restored.players == ("Player 1",)
    viz = visual_registry.create("shot_map")     # different (linked) visual
    ctx = RenderContext(df=DF, theme=THEMES.get("opta_light"),
                        controls={"title": ""},
                        meta={"selection": model.to_dict()})
    fig = Renderer().render(viz, ctx)
    plain = Renderer().render(viz, RenderContext(
        df=DF, theme=THEMES.get("opta_light"), controls={"title": ""}, meta={}))
    assert len(fig.axes[0].collections) > len(plain.axes[0].collections)
    plt.close(fig); plt.close(plain)


# ---------------------------------------------------------------- report integration
def test_report_engine_renders_any_visualization():
    from fap.reports import ReportBuilder, ReportSpec
    ctx = RenderContext(df=DF, theme=THEMES.get("opta_light"), controls={},
                        meta={"report_visuals": [
                            {"viz_id": "pass_map", "controls": {"title": "Passes"}},
                            {"viz_id": "shot_timeline", "controls": {}},
                        ]})
    sections = ReportBuilder().build(ReportSpec(title="Match Report",
                                                section_ids=["visuals"]), ctx)
    assert len(sections[0].figures) == 2
    assert "Pass Map" in sections[0].markdown
    for fig in sections[0].figures:
        plt.close(fig)
