"""P4 - Player Scouting Visualization Workspace.

The adapter (fap.scouting.viz) and renderers (fap.scouting.charts) turn a
player-scouting metric table into professional charts (bar/radar/pizza/scatter/…)
WITHOUT event data, reusing the existing theme + export infrastructure. These
tests pin: dynamic metric discovery, row-count agnostic behaviour (1..250
players), percentile/normalized semantics with no double-normalization, chart
availability, mplsoccer pizza + presets, theme switching, export, and the
capability boundary (no event columns, no Open Play pipeline).
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from fap.scouting import charts, viz
from fap.themes import ThemeManager
from fap.visuals.export import ExportEngine

_ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets" / "themes"
PLAYER = "S. Mamadu bah"

_METRICS = [
    ("Non-penalty goals per 90", "per_90"), ("npxG per 90", "per_90"),
    ("Progressive passes per 90", "per_90"), ("Progressive runs per 90", "per_90"),
    ("xA per 90", "per_90"), ("Key passes per 90", "per_90"),
    ("Duels won, %", "percent"), ("Accurate passes, %", "percent"),
    ("Interceptions per 90", "per_90"), ("Passes", "count"),
]


def _theme(theme_id="opta_dark"):
    return ThemeManager(str(_ASSETS)).get(theme_id)


def _make(players=33, *, normalized=True, metrics=_METRICS, include_dims=True):
    """A synthetic player-scouting frame + schema (no filename/row-count coupling).
    The first player is always the exact name PLAYER."""
    names = ([PLAYER] + [f"Player {i}" for i in range(players - 1)]) if players else []
    rows = []
    for i, nm in enumerate(names):
        r = {"Player": nm}
        if include_dims:
            r["Team"] = f"Club {i % 6}"
            r["Position"] = "CF"
            r["League"] = "Test League"
        for j, (m, _u) in enumerate(metrics):
            base = ((i * 7 + j * 3) % 100) / 100.0
            r[m] = base if normalized else round(base * 40 + 1, 2)
        rows.append(r)
    frame = pd.DataFrame(rows)
    schema = {
        "id_field": "Player", "value_scale": "normalized" if normalized else "raw",
        "dimensions": ({"player": "Player", "team": "Team", "position": "Position",
                        "league": "League"} if include_dims else {"player": "Player"}),
        "metrics": [{"source": m, "name": m, "unit": u} for m, u in metrics],
    }
    return frame, schema


def _view(players=33, **kw):
    frame, schema = _make(players, **kw)
    who = [PLAYER] if players >= 1 else []
    return viz.build_view(frame, schema, who, dataset_id="d1", dataset_name="Test"), frame


# ================================================================ 3 metric discovery
def test_dynamic_metric_discovery_not_hardcoded():
    view, _ = _view(10, metrics=[("Custom Metric A per 90", "per_90"),
                                 ("Weird Stat, %", "percent"), ("Thing", "count")])
    assert len(view.metrics) == 3
    assert {m.name for m in view.metrics} == {"Custom Metric A per 90", "Weird Stat, %", "Thing"}


# ================================================================ 4-7 row-count agnostic
@pytest.mark.parametrize("n", [1, 2, 5, 33, 250])
def test_row_count_agnostic(n):
    view, _ = _view(n)
    assert view.population == n
    assert len(view.metrics) == len(_METRICS)
    assert view.primary == PLAYER


# ================================================================ 8/9 scales
def test_normalized_scale():
    view, _ = _view(33, normalized=True)
    assert view.value_scale == viz.SCALE_NORMALIZED
    data = viz.pizza_values(view, view.sources()[:5])
    assert data["mode"] == "normalized"


def test_raw_scale_uses_percentile():
    view, _ = _view(33, normalized=False)
    assert view.value_scale == viz.SCALE_RAW
    data = viz.pizza_values(view, view.sources()[:5])
    assert data["mode"] == "percentile"


# ================================================================ 10 mixed units
def test_mixed_units_detected():
    view, _ = _view(20)
    assert {"per_90", "percent", "count"} <= set(view.units())


# ================================================================ 11 percentile calc
def test_percentile_and_rank_are_correct():
    # controlled population: Player values 0.9 (top), others lower
    frame = pd.DataFrame({"Player": ["A", "B", "C", "D", PLAYER],
                          "M per 90": [0.1, 0.2, 0.3, 0.4, 0.9]})
    schema = {"id_field": "Player", "value_scale": "raw",
              "dimensions": {"player": "Player"},
              "metrics": [{"source": "M per 90", "name": "M per 90", "unit": "per_90"}]}
    view = viz.build_view(frame, schema, [PLAYER])
    m = view.metric("M per 90")
    assert m.rank(PLAYER) == 1                     # highest value
    assert m.percentile(PLAYER) == 90.0           # mean-rank percentile: (4 + 0.5)/5
    assert m.count == 5 and m.maximum == 0.9


# ================================================================ 12 no double-normalization
def test_no_double_normalization_of_normalized_values():
    view, _ = _view(33, normalized=True)
    src = view.sources()[:4]
    data = viz.pizza_values(view, src)
    # normalized slice value == raw value * 100 (never re-ranked)
    for s, sv in zip(src, data["values"]):
        raw = view.metric(s).value(PLAYER)
        assert abs(sv - raw * 100.0) < 1e-6


# ================================================================ 13-22 renderers
@pytest.mark.parametrize("ct,opts_key", [
    ("bar", "metrics"), ("percentile_bar", "metrics"), ("radar", "metrics"),
    ("lollipop", "metrics"), ("small_multiples", "metrics"),
])
def test_multi_metric_charts_render(ct, opts_key):
    view, frame = _view(33)
    fig = charts.render(ct, view, _theme(), {opts_key: view.sources()[:8], "frame": frame})
    assert fig is not None
    assert len(ExportEngine().export(fig, ct, fmt="png").data) > 0
    plt.close(fig)


def test_pizza_uses_mplsoccer_and_renders():
    from mplsoccer import PyPizza                          # the reused implementation
    assert PyPizza is not None
    view, _ = _view(33)
    fig = charts.pizza_chart(view, viz.suggest_pizza_metrics(view, 10), _theme())
    assert len(ExportEngine().export(fig, "pizza", fmt="png").data) > 0
    plt.close(fig)


def test_scatter_histogram_box_render():
    view, frame = _view(33)
    src = view.sources()
    for fig in (charts.scatter(view, src[0], src[1], _theme(), frame),
                charts.histogram(view, src[0], _theme(), frame),
                charts.box_plot(view, src[:5], _theme(), frame)):
        assert len(ExportEngine().export(fig, "c", fmt="png").data) > 0
        plt.close(fig)


def test_ranking_bar_renders():
    view, _ = _view(33)
    fig = charts.ranking_bar(view, view.sources()[0], _theme())
    assert len(ExportEngine().export(fig, "rank", fmt="png").data) > 0
    plt.close(fig)


# ================================================================ 15/16 pizza selection + presets
def test_pizza_metric_selection_is_respected():
    view, _ = _view(33)
    chosen = view.sources()[:3]
    data = viz.pizza_values(view, chosen)
    assert data["available"] and data["params"] == [view.metric(s).name for s in chosen]


def test_presets_only_appear_when_metrics_exist():
    # a passing-only dataset (>= 3 Passing metrics): 'Defensive'/'Physical' must NOT appear
    metrics = [("Passes per 90", "per_90"), ("Accurate passes, %", "percent"),
               ("Long balls per 90", "per_90"), ("Switches per 90", "per_90")]
    view, _ = _view(20, metrics=metrics)
    assert all(m.category == "Passing" for m in view.metrics)     # fixture sanity
    presets = viz.available_presets(view)
    assert "Passing" in presets
    assert "Defensive" not in presets and "Physical" not in presets


def test_preset_metrics_only_matching_category():
    view, _ = _view(33)
    defensive = viz.preset_metrics(view, "Defensive")
    assert all(view.metric(s).category == "Defensive" for s in defensive)


# ================================================================ 23 unavailable states
def test_chart_availability_reasons():
    single, _ = _view(1)
    avail = viz.chart_availability(single)
    assert avail["comparison"][0] is False and avail["comparison"][1]
    assert avail["histogram"][0] is False        # 1 player < min population
    assert avail["heatmap"][0] is False
    # scatter needs >=2 metrics AND enough players
    assert avail["scatter"][0] is False


def test_pizza_unavailable_with_too_few_metrics():
    view, _ = _view(33)
    data = viz.pizza_values(view, view.sources()[:2])
    assert data["available"] is False and data["reason"]


# ================================================================ 24/25 themes
@pytest.mark.parametrize("theme_id", ["opta_dark", "opta_light", "athletic", "hudl"])
def test_theme_switching_all_render(theme_id):
    view, _ = _view(33)
    fig = charts.pizza_chart(view, viz.suggest_pizza_metrics(view, 8), _theme(theme_id))
    assert len(ExportEngine().export(fig, "t", fmt="png").data) > 0
    plt.close(fig)


def test_light_and_dark_palettes_differ():
    dark = charts.palette(_theme("opta_dark"))
    light = charts.palette(_theme("opta_light"))
    assert dark.bg != light.bg


# ================================================================ 26 comparison
def test_player_comparison_view_and_chart():
    frame, schema = _make(33)
    view = viz.build_view(frame, schema, [PLAYER, "Player 1", "Player 2"])
    assert view.is_comparison and len(view.players) == 3
    assert viz.chart_availability(view)["comparison"][0] is True
    fig = charts.comparison_bars(view, view.sources()[:6], _theme())
    assert len(ExportEngine().export(fig, "cmp", fmt="png").data) > 0
    plt.close(fig)
    hm = charts.heatmap(view, view.sources()[:6], _theme())
    assert len(ExportEngine().export(hm, "hm", fmt="png").data) > 0
    plt.close(hm)


# ================================================================ 27 export png+pdf
def test_export_png_and_pdf():
    view, _ = _view(33)
    fig = charts.pizza_chart(view, viz.suggest_pizza_metrics(view, 8), _theme())
    ex = ExportEngine()
    png = ex.export(fig, "p", fmt="png")
    pdf = ex.export(fig, "p", fmt="pdf")
    assert png.mime.startswith("image/") and len(png.data) > 0
    assert len(pdf.data) > 0
    plt.close(fig)


# ================================================================ 28/29 capability boundary
def test_no_event_columns_required():
    frame, schema = _make(33)
    assert not ({"x", "y", "x2", "y2", "event_type"} & set(frame.columns))
    view = viz.build_view(frame, schema, [PLAYER])
    assert len(view.metrics) == len(_METRICS)     # renders purely from metrics


def test_no_open_play_pipeline_invoked(monkeypatch):
    # building the view + rendering must never call the Open Play transform
    import fap.openplay.transforms as tr

    def _boom(*a, **k):
        raise AssertionError("add_derived_columns must not be called for scouting viz")
    monkeypatch.setattr(tr, "add_derived_columns", _boom)
    view, frame = _view(33)
    fig = charts.render("pizza", view, _theme(), {"metrics": viz.suggest_pizza_metrics(view, 8)})
    plt.close(fig)                                 # no exception => pipeline untouched


# ================================================================ 30 deterministic
def test_deterministic_view_and_suggestions():
    v1, _ = _view(33)
    v2, _ = _view(33)
    assert [m.to_dict() for m in v1.metrics] == [m.to_dict() for m in v2.metrics]
    assert viz.suggest_pizza_metrics(v1, 10) == viz.suggest_pizza_metrics(v2, 10)


# ================================================================ S. Mamadu bah specifically
def test_s_mamadu_bah_specifically_works():
    view, frame = _view(33)
    assert view.primary == PLAYER
    m = view.metric("Non-penalty goals per 90")
    assert m is not None and m.value(PLAYER) is not None
    fig = charts.pizza_chart(view, viz.suggest_pizza_metrics(view, 10), _theme())
    assert len(ExportEngine().export(fig, PLAYER, fmt="png").data) > 0
    plt.close(fig)


# ================================================================ 1/2 integration (platform)
def test_integration_scouting_dataset_and_event_unchanged(tmp_path):
    from dataclasses import replace
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    from fap.bootstrap import init_platform
    from fap.identity.models import User
    from fap.identity.roles import Role
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"),
                       storage=StorageSettings(backend="local"))
    platform = init_platform(settings=settings)
    try:
        user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
        ws = platform.workspace_manager.ensure_workspace(user)
        frame, _schema = _make(33)
        csv = frame.to_csv(index=False).encode()
        ar = platform.datahub.analyze(csv, "board.csv")
        ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name="Board",
                                                    workspace_id=ws.id)
        platform.datahub.choose(user, ds.id)
        ctx = platform.scouting.active_scouting_dataset(user)
        assert ctx is not None and len(ctx["players"]) == 33 and ctx["frame"] is not None
        v = viz.build_view(ctx["frame"], ctx["schema"], [PLAYER])
        assert len(v.metrics) == len(_METRICS)
        # event dataset -> active_scouting_dataset must be None (unchanged behaviour)
        ev = (b"event_type,x,y,team,player,minute,match_id\n"
              b"pass,10,20,Home,S. Mamadu bah,1,M1\n")
        er = platform.datahub.analyze(ev, "match.csv")
        eds = platform.datahub.save_dataset(user, er.import_result, name="ev",
                                            workspace_id=ws.id, metadata={})
        platform.datahub.choose(user, eds.id)
        assert platform.scouting.active_scouting_dataset(user) is None
    finally:
        platform.db.close()
