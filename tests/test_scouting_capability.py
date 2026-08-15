"""Scouting dataset-capability boundary (P0.5).

Player-scouting datasets (one row per player, metric columns) and event datasets
(one row per on-ball event) are DIFFERENT capabilities. Opening a scouting player
while a player-scouting dataset is active must read the player's metric profile
from that dataset - never run the event lookup, and never report "No events found".
Event datasets keep working exactly as before, and the two are never mixed.

Uses the exact player name from the uploaded file, "S. Mamadu bah" (unchanged).
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pandas as pd
import pytest

from fap.config.settings import (
    AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
from fap.bootstrap import init_platform
from fap.identity.models import User
from fap.identity.roles import Role

PLAYER = "S. Mamadu bah"                       # exact name in the file - never changed


def _malta_like_csv() -> bytes:
    """A Malta-shaped player-scouting table (index artifact + identity + metrics),
    including a row for the exact player name. Synthetic - no filename dependency."""
    metrics = ["Non-penalty goals per 90", "npxG per 90", "Progressive passes per 90",
               "Progressive runs per 90", "xA per 90", "Passes per 90", "Duels won, %"]
    rows = []
    names = [PLAYER] + [f"Player {i}" for i in range(32)]
    for i, nm in enumerate(names):
        r = {"Unnamed: 0": i, "Player": nm, "Age": 20 + i % 15,
             "League": "Malta Premier League 25-26", "Position": "CF, RAMF, AMF",
             "Team": "Sliema Wanderers", "Birth country": "United States"}
        for j, m in enumerate(metrics):
            r[m] = ((i * 7 + j * 3) % 100) / 100.0
        rows.append(r)
    return pd.DataFrame(rows).to_csv(index=False).encode()


_EVENT_CSV = (b"event_type,x,y,team,player,minute,match_id\n"
              b"pass,10,20,Home,S. Mamadu bah,1,M1\n"
              b"shot,90,45,Home,S. Mamadu bah,2,M1\n")


@pytest.fixture()
def ctx(tmp_path):
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"),
                       storage=StorageSettings(backend="local"))
    platform = init_platform(settings=settings)
    user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
    ws = platform.workspace_manager.ensure_workspace(user)
    try:
        yield platform, user, ws
    finally:
        platform.db.close()


def _active_scouting(ctx):
    """Save + activate the Malta-like scouting dataset; return (platform,user,ws,ds)."""
    platform, user, ws = ctx
    ar = platform.datahub.analyze(_malta_like_csv(), "Malta CF.csv")
    ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name="Malta CF",
                                                workspace_id=ws.id)
    platform.datahub.choose(user, ds.id)
    return platform, user, ws, ds, ar


# ================================================================ 1 classification
def test_malta_like_is_player_scouting(ctx):
    platform, user, ws, ds, ar = _active_scouting(ctx)
    assert ar.kind == "player_scouting"
    assert ar.classification.entity_count == 33
    assert platform.scouting.active_dataset_kind(user) == "player_scouting"


# ================================================================ 2 exact-name resolve
def test_player_resolves_exactly_from_player_column(ctx):
    platform, user, ws, ds, ar = _active_scouting(ctx)
    p = platform.scouting.create_player(user, PLAYER, workspace_id=ws.id)
    profile = platform.scouting.active_scouting_profile(user, p.id)
    assert profile is not None
    assert profile["player"] == PLAYER          # exact, unchanged spelling
    assert profile["dimensions"]["team"] == "Sliema Wanderers"


# ================================================================ 3 no event lookup
def test_scouting_dataset_does_not_run_event_lookup(ctx):
    platform, user, ws, ds, ar = _active_scouting(ctx)
    p = platform.scouting.create_player(user, PLAYER, workspace_id=ws.id)
    # the event lookup returns None (it is never applied to player-scouting data)
    assert platform.scouting.player_event_frame(user, p.id) is None
    assert platform.scouting.active_player_stats(user, p.id) == {"events": 0, "matches": 0}


# ================================================================ 4 profile from metrics
def test_profile_renders_scouting_metrics(ctx):
    platform, user, ws, ds, ar = _active_scouting(ctx)
    p = platform.scouting.create_player(user, PLAYER, workspace_id=ws.id)
    profile = platform.scouting.active_scouting_profile(user, p.id)
    assert len(profile["metrics"]) == 7
    units = {m["unit"] for m in profile["metrics"]}
    assert "per_90" in units and "percent" in units
    assert profile["value_scale"] == "normalized"


# ================================================================ 5 no "No events" error (UI routing)
def test_ui_routes_scouting_dataset_to_profile_not_event_path(ctx):
    """The player detail must take the scouting-profile branch (no event lookup,
    no 'No events found') when a player-scouting dataset is active."""
    platform, user, ws, ds, ar = _active_scouting(ctx)
    p = platform.scouting.create_player(user, PLAYER, workspace_id=ws.id)

    from fap.ui.builtin.scouting import ScoutingPage

    class _Spy:
        def __init__(self, svc):
            self._svc = svc
            self.event_lookup_called = False

        def active_dataset_kind(self, u):
            return self._svc.active_dataset_kind(u)

        def active_scouting_profile(self, u, pid):
            return self._svc.active_scouting_profile(u, pid)

        def dataset_link_status(self, u, pid):          # P4.2.1 dataset-identity panel
            return self._svc.dataset_link_status(u, pid)

        def active_player_stats(self, u, pid):          # the event path - must NOT run
            self.event_lookup_called = True
            return self._svc.active_player_stats(u, pid)

    class _Shell:
        def __init__(self, u):
            self.user = u

        def goto(self, _):
            pass

    spy = _Spy(platform.scouting)
    page = ScoutingPage()
    page._active_analysis(_Shell(user), spy, p)         # bare-mode Streamlit
    assert spy.event_lookup_called is False             # event lookup was NOT invoked


# ================================================================ 6/7 event capability intact
def test_event_dataset_still_uses_event_lookup(ctx):
    platform, user, ws = ctx
    p = platform.scouting.create_player(user, PLAYER, workspace_id=ws.id)
    er = platform.datahub.analyze(_EVENT_CSV, "match.csv")
    eds = platform.datahub.save_dataset(user, er.import_result, name="ev",
                                        workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, eds.id)
    assert platform.scouting.active_dataset_kind(user) == "event"
    frame = platform.scouting.player_event_frame(user, p.id)
    assert frame is not None and len(frame) == 2       # events resolved as before
    # a scouting profile is NOT produced from an event dataset
    assert platform.scouting.active_scouting_profile(user, p.id) is None


# ================================================================ 8 capabilities separated
def test_capabilities_are_separated(ctx):
    platform, user, ws, ds, ar = _active_scouting(ctx)
    p = platform.scouting.create_player(user, PLAYER, workspace_id=ws.id)
    # player-scouting active: profile yes, event no
    assert platform.scouting.active_scouting_profile(user, p.id) is not None
    assert platform.scouting.player_event_frame(user, p.id) is None
    # a player not in the scouting dataset -> None, not an error/raise
    other = platform.scouting.create_player(user, "Someone Else", workspace_id=ws.id)
    assert platform.scouting.active_scouting_profile(user, other.id) is None
