"""Phase 12.3 - Players & Scouting consume the active dataset (single source of truth).

Both modules now read match/event data from WorkspaceManager.active_frame and join
it IN MEMORY to their persistent records (first-team squad / recruitment DB), which
stay untouched. No duplicated dataframe state; when no dataset is active the modules
report no event data (Players still honours explicit per-player dataset links).
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pandas as pd
import pytest

from fap.config.settings import AppSettings, CacheSettings, DatabaseSettings, StorageSettings
from fap.bootstrap import init_platform
from fap.identity.models import User
from fap.identity.roles import Role
from fap.players.service import PlayersService
from fap.scouting.service import ScoutingService
from fap.workspaces.audit import AuditService
from fap.workspaces.repositories import AuditRepository

FRAME = pd.DataFrame({
    "event_type": ["pass", "shot", "pass", "carry", "pass", "shot"],
    "x": [10, 90, 20, 60, 30, 80], "y": [20, 45, 80, 50, 30, 45],
    "end_x": [15, None, 25, 70, 44, None], "end_y": [22, None, 70, 55, 32, None],
    "team": ["Home"] * 6, "opponent": ["Away"] * 6,
    "player": ["Salah", "Salah", "Mane", "Salah", "Mane", "Mane"],
    "minute": [1, 2, 3, 4, 5, 6], "second": [0] * 6, "period": [1] * 6, "match_id": ["M1"] * 6})


@pytest.fixture()
def ctx(tmp_path):
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))
    platform = init_platform(settings=settings)
    db = platform.db
    aud = AuditService(AuditRepository(db))
    players = PlayersService(db, permissions=platform.permissions, audit=aud, reports=None,
                             images=None, files=None, workspaces=platform.workspace_manager,
                             scouting=None, cache=platform.cache)
    scouting = ScoutingService(db, permissions=platform.permissions, audit=aud, reports=None,
                               images=None, videos=None, attachments=None,
                               workspaces=platform.workspace_manager)
    user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
    ws = platform.workspace_manager.ensure_workspace(user)
    hub = platform.datahub
    ds = hub.save_dataset(user, hub.run_import(FRAME.to_csv(index=False).encode(), "m.csv"),
                          name="vs Away", workspace_id=ws.id, metadata={"opponent": "Away"})
    try:
        yield platform, players, scouting, user, ws, ds
    finally:
        db.close()


def test_players_consume_active_dataset_joined_by_name(ctx):
    platform, players, _, user, ws, ds = ctx
    platform.workspace_manager.choose = None  # not used; explicit for clarity
    platform.datahub.choose(user, ds.id)
    ft = players.create_player(user, first_name="Mo", last_name="Salah",
                               display_name="Salah", workspace_id=ws.id)
    frame = players.player_event_frame(user, ft.id)
    assert frame is not None and len(frame) == 3
    assert set(frame["player"].str.lower()) == {"salah"}
    src = players.player_data_source(user, ft.id)
    assert src["active"] and src["active_name"] == "vs Away" and src["linked"] == 0
    assert players.get_player(ft.id).last_name == "Salah"          # persistent DB untouched


def test_scouting_consume_active_dataset_joined_by_name(ctx):
    platform, _, scouting, user, ws, ds = ctx
    platform.datahub.choose(user, ds.id)
    p = scouting.create_player(user, "Mane", workspace_id=ws.id)
    assert scouting.has_active_dataset(user) is True
    frame = scouting.player_event_frame(user, p.id)
    assert frame is not None and set(frame["player"].str.lower()) == {"mane"}
    stats = scouting.active_player_stats(user, p.id)
    assert stats["events"] == 3 and stats["matches"] == 1
    unknown = scouting.create_player(user, "Nobody", workspace_id=ws.id)
    assert scouting.player_event_frame(user, unknown.id) is None    # no fabrication
    assert scouting.get_player(p.id).name == "Mane"                 # persistent DB untouched


def test_single_source_and_no_duplication(ctx):
    platform, players, scouting, user, ws, ds = ctx
    wm = platform.workspace_manager
    platform.datahub.choose(user, ds.id)
    ft = players.create_player(user, first_name="Mo", last_name="Salah", workspace_id=ws.id)
    sc = scouting.create_player(user, "Salah", workspace_id=ws.id)
    # active-only resolves once (3 rows), not doubled
    assert len(players.player_event_frame(user, ft.id)) == 3
    # clear the active dataset -> event data disappears (no alternative path / cache)
    wm.clear_active_dataset(user)
    assert players.player_event_frame(user, ft.id) is None          # no links
    assert scouting.player_event_frame(user, sc.id) is None
    assert scouting.has_active_dataset(user) is False
    assert players.player_data_source(user, ft.id)["active"] is False
