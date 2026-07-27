"""Phase 12.2 - Set Pieces reads from the active dataset (single source of truth).

Verifies the Set Piece module derives its set pieces from the platform's active
canonical frame (WorkspaceManager.active_frame) instead of a separate import, with
NO duplicated state, while every analytics/validation plugin keeps consuming
SetPiece objects unchanged. When no dataset is active it falls back to the manual
store (so manual-only tagging still works).
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
from fap.setpieces.derivation import derive_set_pieces
from fap.setpieces.models import SetPieceFilter
from fap.setpieces.service import SetPieceService
from fap.setpieces.viz_validation import coverage_counts
from fap.workspaces.audit import AuditService
from fap.workspaces.repositories import AuditRepository

FRAME = pd.DataFrame({
    "event_type": ["corner", "free_kick", "throw-in", "penalty", "pass", "shot", "pass"],
    "set_piece": ["corner", "free_kick", "throw_in", "penalty", "", "", ""],
    "x": [99, 70, 20, 88, 50, 80, 40], "y": [50, 40, 80, 50, 50, 45, 30],
    "end_x": [95, 75, 25, None, 60, None, 44], "end_y": [45, 50, 70, None, 55, None, 32],
    "team": ["Home", "Home", "Away", "Away", "Home", "Home", "Home"],
    "opponent": ["Away"] * 7, "player": ["A", "B", "C", "D", "A", "A", "B"],
    "minute": [1, 2, 3, 4, 5, 6, 7], "second": [0] * 7, "period": [1, 1, 1, 1, 1, 1, 2],
    "match_id": ["M1"] * 7, "shot_result": ["goal", "", "", "", "", "goal", ""]})


def test_derivation_is_pure_and_projects_set_pieces():
    d = derive_set_pieces(FRAME, workspace_id="w")
    assert len(d) == 4
    assert {s.type for s in d} == {"corner", "free_kick", "throw_in", "penalty"}
    assert [s for s in d if s.type == "corner"][0].goal is True
    # primary team (Home) -> offensive/own; the other -> defensive/opposition
    assert all(s.phase == "offensive" for s in d if s.team == "Home")
    assert all(s.phase == "defensive" for s in d if s.team == "Away")


@pytest.fixture()
def ctx(tmp_path):
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))
    platform = init_platform(settings=settings)
    db = platform.db
    svc = SetPieceService(db, permissions=platform.permissions,
                          audit=AuditService(AuditRepository(db)), reports=None,
                          workspaces=platform.workspace_manager, cache=platform.cache)
    user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
    ws = platform.workspace_manager.ensure_workspace(user)
    try:
        yield platform, svc, user, ws
    finally:
        db.close()


def _activate(platform, user, ws):
    csv = FRAME.to_csv(index=False).encode()
    res = platform.datahub.run_import(csv, "match.csv")
    ds = platform.datahub.save_dataset(user, res, name="vs Away", workspace_id=ws.id,
                                       metadata={"opponent": "Away"})
    platform.datahub.choose(user, ds.id)
    return ds


def test_no_active_dataset_falls_back_to_store(ctx):
    _, svc, user, _ = ctx
    assert svc.has_active_dataset(user) is False
    assert svc.dashboard(user)["total"] == 0          # empty store, not an error


def test_set_pieces_read_from_active_dataset(ctx):
    platform, svc, user, ws = ctx
    _activate(platform, user, ws)
    assert svc.has_active_dataset(user) is True
    dash = svc.dashboard(user)
    assert dash["total"] == 4
    assert set(dash["by_type"]) == {"corner", "free_kick", "throw_in", "penalty"}
    assert dash["offensive"] == 2 and dash["defensive"] == 2
    assert len(svc.search(user)) == 4
    assert len(svc.search(user, filters={"type": "corner"})) == 1


def test_analytics_and_coverage_flow_through_active_source(ctx):
    platform, svc, user, ws = ctx
    _activate(platform, user, ws)
    off = svc.analytics_overview(user, SetPieceFilter(phase="offensive"), workspace_id=ws.id)
    assert off["count"] == 2
    cov = coverage_counts(svc, user, None, ws.id)          # viz health via _filtered
    assert cov["events"] == 4
    assert cov["positions"]["n"] == 0                      # derived: no manual box tags


def test_clearing_active_dataset_restores_store(ctx):
    platform, svc, user, ws = ctx
    _activate(platform, user, ws)
    platform.workspace_manager.clear_active_dataset(user)
    assert svc.has_active_dataset(user) is False
    assert svc.dashboard(user)["total"] == 0
