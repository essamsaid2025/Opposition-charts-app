"""Team-match-stats dataset support: classification, analyzer, Data Hub routing,
and dedicated Open Play comparison charts.

A "Team Stats" match export (rows are statistics, columns are the teams being
compared, no x/y and no player identity) previously fell through to the event
pipeline and failed with 'Missing required column: event_type; x; y'. These tests
pin the fix: the file is recognised as ``team_match_stats``, read by a dedicated
analyzer, saved as a first-class dataset, and drawn with team-comparison charts in
Open Play — never touching the event engine.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
from matplotlib.figure import Figure

from fap.datahub.classification import (
    PLAYER_SCOUTING, TEAM_MATCH_STATS, classify_frame,
)
from fap.datahub.team_stats_schema import PERCENT, COUNT, analyze_team_stats
from fap.identity.models import User
from fap.identity.roles import Role
from fap.openplay import team_compare as tc
from fap.ui.page import get_page, load_builtin_pages
from fap.workspaces.models import Dataset

load_builtin_pages()


# ---------------------------------------------------------------- sample data
_TEAM_STATS_CSV = """Category,Statistic,FC MASAR,ABU QIR
Summary,Goals,1,1
Summary,Possessions,56%,44%
Summary,Shots in total,6,11
Summary,Fouls,20,16
Summary,Corners,5,2
Offensive,Shots on target,2,5
Offensive,Shots inside PA,4,9
Offensive,Shot Conversion Rate,17%,9%
Defensive,Successful tackles,13,19
Defensive,Interceptions,10,11
Distribution,Successful passes,372,240
Distribution,Pass accuracy,72%,62%
Distribution,Field Tilt,57%,43%
"""


def _frame() -> pd.DataFrame:
    import io
    return pd.read_csv(io.StringIO(_TEAM_STATS_CSV))


def _scouting_frame() -> pd.DataFrame:
    return pd.DataFrame([
        {"Player": f"P{i}", "Team": f"Club {i%4}", "Position": "CF",
         "Goals per 90": (i % 10) / 10, "xG per 90": (i % 7) / 10} for i in range(12)
    ])


# ================================================================ classification
def test_team_stats_shape_is_recognised():
    cls = classify_frame(_frame())
    assert cls.dataset_type == TEAM_MATCH_STATS
    assert cls.confidence >= 0.8            # category column lifts confidence
    assert cls.signals["team_columns"] == ["FC MASAR", "ABU QIR"]
    assert cls.signals["stat_label_column"] == "Statistic"


def test_team_stats_without_category_still_recognised():
    df = _frame().drop(columns=["Category"])
    cls = classify_frame(df)
    assert cls.dataset_type == TEAM_MATCH_STATS
    assert cls.signals["category_column"] == ""


def test_scouting_table_not_misclassified_as_team_stats():
    # a player table has an identity column -> scouting, never team_match_stats
    assert classify_frame(_scouting_frame()).dataset_type == PLAYER_SCOUTING


def test_needs_two_team_columns():
    df = _frame().drop(columns=["ABU QIR"])          # only one team value column
    assert classify_frame(df).dataset_type != TEAM_MATCH_STATS


# ================================================================ analyzer
def test_analyzer_reads_teams_stats_units():
    analysis = analyze_team_stats(_frame())
    assert analysis.dataset_type == TEAM_MATCH_STATS
    assert analysis.teams == ["FC MASAR", "ABU QIR"]
    assert analysis.stat_count == 13
    assert set(analysis.schema.categories) == {"Summary", "Offensive", "Defensive", "Distribution"}
    poss = analysis.schema.stats[1]
    assert poss.name == "Possessions"
    assert poss.unit == PERCENT
    assert poss.value("FC MASAR") == 56.0          # face value, not divided by 100
    assert poss.raw["ABU QIR"] == "44%"
    goals = analysis.schema.stats[0]
    assert goals.unit == COUNT and goals.value("ABU QIR") == 1.0
    assert analysis.quality.grade in ("Good", "Fair")


def test_analyzer_summary_roundtrips_through_schema_dict():
    from fap.datahub.team_stats_schema import TeamStatsSchema
    schema = analyze_team_stats(_frame()).schema
    back = TeamStatsSchema.from_dict(schema.to_dict())
    assert back.teams == schema.teams
    assert len(back.stats) == len(schema.stats)
    assert back.stats[1].value("FC MASAR") == 56.0


# ================================================================ Data Hub routing (integration)
def _platform(tmp_path):
    from dataclasses import replace
    from fap.bootstrap import init_platform
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"),
                       storage=StorageSettings(backend="local"))
    return init_platform(settings=settings)


def test_analyze_routes_to_team_stats_and_saves(tmp_path):
    platform = _platform(tmp_path)
    try:
        user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
        ws = platform.workspace_manager.ensure_workspace(user)
        csv = _TEAM_STATS_CSV.encode()

        ar = platform.datahub.analyze(csv, "Masar Vs Abu Qir Team Stats.csv")
        assert ar.kind == TEAM_MATCH_STATS
        assert ar.team_stats is not None and ar.team_stats.teams == ["FC MASAR", "ABU QIR"]

        ds = platform.datahub.save_team_stats_dataset(
            user, ar.team_stats, name="Masar vs Abu Qir", workspace_id=ws.id)
        assert platform.datahub.dataset_type(ds) == TEAM_MATCH_STATS

        # discoverable by kind
        found = platform.datahub.list_team_stats_datasets(workspace_id=ws.id)
        assert any(d.id == ds.id for d in found)

        # health + compatibility grade it on team/stat coverage, not coordinates
        health = platform.datahub.health(ds.id)
        keys = {a.key for a in health.axes}
        assert {"teams", "statistics"} <= keys
        assert "coordinates" not in keys
        compat = {c.module: c.ready for c in platform.datahub.compatibility(ds.id)}
        assert compat["Open Play"] is True       # dedicated charts
        assert compat["Set Pieces"] is False

        # the stored frame carries none of the Open Play event columns
        frame = platform.datahub.repo.frame(ds.id)
        assert not ({"x", "y", "x2", "y2", "event_type"} & set(frame.columns))
    finally:
        platform.db.close()


# ================================================================ Open Play charts
def _comparison():
    return tc.TeamComparison.from_schema(analyze_team_stats(_frame()).schema,
                                         dataset_name="Masar vs Abu Qir")


class _Theme:
    colors = {"bg": "#0E1117", "panel": "#141A22", "text": "#FFF", "muted": "#AAB",
              "grid": "#2A3240", "accent": "#00C2FF", "warning": "#FACC15",
              "success": "#22C55E", "danger": "#FF5A5F"}
    fonts = {"body": "DejaVu Sans"}


def test_team_comparison_selection_helpers():
    cmp = _comparison()
    assert cmp.teams == ("FC MASAR", "ABU QIR")
    # "Shots in total" is unique here; a repeated label would be category-qualified
    labels = cmp.stat_labels()
    assert "Possessions" in labels
    assert cmp.resolve("Possessions").value("FC MASAR") == 56.0


def test_every_chart_type_renders():
    cmp = _comparison()
    theme = _Theme()
    for meta in tc.CHART_TYPES:
        opts = {"stat": "Possessions"} if meta["id"] == "donut" else {
            "stats": ["Goals", "Shots in total", "Successful passes", "Fouls", "Corners"]}
        fig = tc.render(meta["id"], cmp, theme, opts)
        assert isinstance(fig, Figure)
        import matplotlib.pyplot as plt
        plt.close(fig)


def test_diverging_needs_two_teams():
    schema = analyze_team_stats(_frame()).schema
    # one-team selection -> graceful empty figure, not a crash
    cmp = tc.TeamComparison.from_schema(schema, teams=["FC MASAR"])
    fig = tc.render("diverging", cmp, _Theme(), {"stats": ["Goals"]})
    assert isinstance(fig, Figure)


# ================================================================ page boundaries
class _FakeWM:
    def __init__(self, ds):
        self._ds = ds

    def active_dataset(self, user):
        return self._ds


class _FakeShell:
    def __init__(self, ds):
        self.user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN,
                         provider_id="dev")
        self.platform = None                 # themes unavailable -> graceful alert
        self.wm = _FakeWM(ds)
        self.workspace_id = "w1"
        self.active_page_id = "opponent_analysis"

    def goto(self, page_id):
        pass


def _team_stats_dataset():
    schema = analyze_team_stats(_frame()).schema
    return Dataset(id="t1", name="Masar vs Abu Qir", rows=13,
                   provider_id="team_match_stats",
                   document={"dataset_type": TEAM_MATCH_STATS, "entity_type": "team_stat",
                             "team_stats_schema": schema.to_dict(),
                             "team_stats_summary": analyze_team_stats(_frame()).summary()})


def test_opponent_analysis_renders_team_stats_without_run_app():
    """A team-stats active dataset must draw the comparison workspace, never call the
    Open Play event renderer (which would raise KeyError('x2'))."""
    from fap.ui.page import register_renderer
    ran = []
    register_renderer("opponent_analysis", lambda: ran.append("run_app"))
    page = get_page("opponent_analysis")
    page.render(_FakeShell(_team_stats_dataset()))       # must not raise
    assert ran == []


def test_open_play_studio_handles_team_stats_dataset():
    import streamlit as st
    st.session_state.clear()
    page = get_page("open_play_studio")
    page.render(_FakeShell(_team_stats_dataset()))       # must not raise
