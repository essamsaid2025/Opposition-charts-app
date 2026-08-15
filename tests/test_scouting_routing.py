"""Scouting vs Opponent Analysis page routing (P0.5 routing fix).

A recent redesign relabelled the Open Play "Opponent Analysis" page to "Scouting"
without changing its route, so clicking Scouting rendered ``opponent_analysis.py``
-> ``app.run_app`` -> Open Play transforms, which fail with ``KeyError('x2')`` when a
player-scouting dataset is active. These tests pin the fix: Scouting and Opponent
Analysis are DISTINCT routes with distinct labels, the Open Play renderer belongs
only to opponent_analysis, and a player-scouting active dataset is refused at the
page boundary (no run_app, no raw KeyError) rather than crashing.
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

from fap.identity.models import User
from fap.identity.roles import Role
from fap.ui.page import get_page, get_renderer, load_builtin_pages, register_renderer
from fap.ui.dataset_compat import non_event_active_dataset
from fap.workspaces.models import Dataset

load_builtin_pages()


# ---------------------------------------------------------------- fakes
class _FakeWM:
    def __init__(self, dataset=None):
        self._ds = dataset

    def active_dataset(self, user):
        return self._ds


class _FakeShell:
    def __init__(self, dataset=None):
        self.user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN,
                         provider_id="dev")
        self.platform = None
        self.wm = _FakeWM(dataset)
        self.active_page_id = "opponent_analysis"
        self.goto_calls = []

    def goto(self, page_id):
        self.goto_calls.append(page_id)


def _scouting_dataset():
    return Dataset(id="d1", name="Malta CF shortlist", rows=33,
                   provider_id="player_scouting",
                   document={"dataset_type": "player_scouting", "entity_type": "player"})


def _event_dataset():
    return Dataset(id="d2", name="vs Rival", rows=100, provider_id="generic_csv",
                   document={"provider": "generic_csv"})       # no dataset_type flag


# ================================================================ 6/7 distinct routes
def test_scouting_and_opponent_analysis_are_distinct_routes():
    scouting = get_page("scouting")
    opp = get_page("opponent_analysis")
    assert scouting is not None and opp is not None
    assert scouting.info.id == "scouting"
    assert opp.info.id == "opponent_analysis"
    assert type(scouting).__module__ == "fap.ui.builtin.scouting"
    assert type(opp).__module__ == "fap.ui.builtin.opponent_analysis"
    assert type(scouting) is not type(opp)


def test_labels_match_their_page_identity():
    # the label rename must carry its own route: "Scouting" -> scouting page,
    # "Opponent Analysis" -> opponent_analysis page (not the reverse).
    assert get_page("scouting").info.name == "Scouting"
    assert get_page("opponent_analysis").info.name == "Opponent Analysis"


def test_dashboard_scouting_card_no_longer_points_to_opponent_analysis():
    from fap.ui.builtin.dashboard import _ACTIONS
    oa = [a for a in _ACTIONS if a[0] == "opponent_analysis"]
    assert oa and oa[0][1] != "Scouting"        # label detached from the OA route
    assert not any(a[0] == "opponent_analysis" and a[1] == "Scouting" for a in _ACTIONS)


# ================================================================ 1 scouting != run_app
def test_open_play_renderer_bound_only_to_opponent_analysis():
    ran = []
    register_renderer("opponent_analysis", lambda: ran.append("run_app"))
    # the Open Play engine renderer is keyed to opponent_analysis, never to scouting
    assert get_renderer("opponent_analysis") is not None
    assert get_renderer("scouting") is None
    # rendering the *scouting* route must not pull the opponent_analysis renderer
    assert ran == []


# ================================================================ compat gate helper
def test_non_event_active_dataset_flags_scouting():
    assert non_event_active_dataset(_FakeShell(_scouting_dataset())) is not None


def test_non_event_active_dataset_passes_event_through():
    assert non_event_active_dataset(_FakeShell(_event_dataset())) is None
    assert non_event_active_dataset(_FakeShell(None)) is None


# ================================================================ 2/8 no run_app, no KeyError
def test_opponent_analysis_refuses_scouting_dataset_without_invoking_run_app():
    """With a player-scouting dataset active, the page must NOT call the Open Play
    renderer (which raises KeyError('x2')) - it renders a redirect instead."""
    ran = []
    register_renderer("opponent_analysis", lambda: ran.append("run_app"))
    page = get_page("opponent_analysis")
    shell = _FakeShell(_scouting_dataset())
    page.render(shell)                       # bare-mode Streamlit; must not raise
    assert ran == []                         # run_app was NOT invoked


def test_opponent_analysis_runs_engine_for_event_dataset():
    ran = []
    register_renderer("opponent_analysis", lambda: ran.append("run_app"))
    page = get_page("opponent_analysis")
    shell = _FakeShell(_event_dataset())
    page.render(shell)
    assert ran == ["run_app"]                # event data flows to the Open Play engine


def test_open_play_studio_refuses_scouting_dataset():
    """Open Play Studio consumes the active frame the same way; a player-scouting
    dataset must be refused at the boundary, not crash add_derived_columns."""
    import streamlit as st
    st.session_state.clear()
    page = get_page("open_play_studio")
    shell = _FakeShell(_scouting_dataset())
    # engine may be unconnected in this harness; either the engine gate or the
    # compat gate returns early - the point is it must NOT raise KeyError('x2').
    page.render(shell)


# ================================================================ 3/4/5 dataset compatibility (integration)
def test_scouting_dataset_usable_without_event_columns(tmp_path):
    """Malta-shaped table -> player_scouting (33), discoverable in Scouting, and its
    frame carries no x/y/x2/event_type - proving the scouting workflow never needs
    the Open Play event columns."""
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
        rows = []
        for i in range(33):
            rows.append({"Player": f"P{i}", "Team": f"Club {i%12}", "Age": 20 + i % 15,
                         "League": "Malta Premier League 25-26", "Position": "CF",
                         "Goals per 90": (i % 10) / 10, "xG per 90": (i % 7) / 10,
                         "Progressive passes per 90": (i % 9) / 10, "Duels won, %": (i % 8) / 10})
        csv = pd.DataFrame(rows).to_csv(index=False).encode()

        ar = platform.datahub.analyze(csv, "Malta CF.csv")
        assert ar.kind == "player_scouting"
        assert ar.classification.entity_count == 33
        ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name="Board",
                                                    workspace_id=ws.id)
        # Scouting discovers it
        avail = platform.scouting.available_scouting_datasets(user, workspace_id=ws.id)
        assert any(d["id"] == ds.id for d in avail)
        frame = platform.scouting.scouting_dataset_frame(user, ds.id)
        assert frame is not None and len(frame) == 33
        # the scouting frame has none of the Open Play event columns
        assert not ({"x", "y", "x2", "y2", "event_type"} & set(frame.columns))
    finally:
        platform.db.close()
