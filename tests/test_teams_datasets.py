"""Teams — active-independent linked datasets (migration 20 + TeamService).

A team can link one or more Data Hub datasets (an opposition team's data file). The
link lives in ``teams.document['datasets']`` and is read BY dataset_id, so the data
keeps showing regardless of which dataset is active in the Data Hub — the same
behaviour the scouting/first-team modules already provide.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.db.engine import Database
from fap.teams.service import TeamService

_USER = SimpleNamespace(email="coach@club.com")


class _WM:
    """Minimal WorkspaceManager stand-in: datasets by id + frames by id + an active id."""
    def __init__(self, datasets, frames, active=None):
        self._d = {d.id: d for d in datasets}
        self._f = frames
        self._active = active

    def get_dataset(self, ds_id):
        return self._d.get(ds_id)

    def list_datasets(self, workspace_id=None, include_archived=False):
        return list(self._d.values())

    def dataset_frame(self, ds_id):
        return self._f.get(ds_id)

    def active_dataset_id(self, user):
        return self._active

    def next_counter(self, key):
        return 1


def _ds(ds_id, name, rows):
    return SimpleNamespace(id=ds_id, name=name, rows=rows, status="active")


def _frame(player):
    return pd.DataFrame([{"event_type": "pass", "x": 1, "y": 2, "player": player, "match_id": "M1"}])


@pytest.fixture()
def ctx(tmp_path):
    frames = {"A": _frame("Opp Winger"), "B": _frame("Our Striker")}
    wm = _WM([_ds("A", "Opposition XI vs Us.csv", 900), _ds("B", "Our League Data.csv", 1200)],
             frames, active="B")                          # B is the ACTIVE dataset in the hub
    svc = TeamService(Database(tmp_path / "t.sqlite3"), workspaces=wm)
    team = svc.create_team(_USER, "Rivals FC", kind="club", competition="League")
    return svc, wm, team


def test_link_persists_and_lists(ctx):
    svc, wm, team = ctx
    svc.link_dataset(_USER, team.id, "A", match_id="M1")
    links = svc.list_linked_datasets(team.id, user=_USER)
    assert len(links) == 1
    l = links[0]
    assert l["dataset_id"] == "A" and l["available"] is True
    assert l["current_name"] == "Opposition XI vs Us.csv" and l["match_id"] == "M1"
    assert l["is_active"] is False                         # A is linked but B is active


def test_document_round_trips_through_db(ctx):
    svc, wm, team = ctx
    svc.link_dataset(_USER, team.id, "A")
    reloaded = svc.get_team(team.id)                       # re-read from the DB
    assert reloaded.document["datasets"][0]["dataset_id"] == "A"


def test_data_shows_regardless_of_active_dataset(ctx):
    """The core ask: link A, keep B active — A's data still reads back by id."""
    svc, wm, team = ctx
    svc.link_dataset(_USER, team.id, "A")
    assert wm.active_dataset_id(_USER) == "B"              # a different dataset is active
    frame = svc.team_dataset_frame(team.id, "A")
    assert frame is not None and frame.iloc[0]["player"] == "Opp Winger"


def test_frame_only_for_linked_datasets(ctx):
    svc, wm, team = ctx
    # B is active in the hub but NOT linked to this team -> no team frame for it
    assert svc.team_dataset_frame(team.id, "B") is None
    svc.link_dataset(_USER, team.id, "B")
    assert svc.team_dataset_frame(team.id, "B") is not None


def test_relink_is_idempotent_and_refreshes(ctx):
    svc, wm, team = ctx
    svc.link_dataset(_USER, team.id, "A")
    wm._d["A"].name = "Opposition XI (renamed).csv"        # dataset renamed in the hub
    svc.link_dataset(_USER, team.id, "A")                  # re-link, not a duplicate
    links = svc.list_linked_datasets(team.id, user=_USER)
    assert len(links) == 1 and links[0]["current_name"] == "Opposition XI (renamed).csv"


def test_unlink_removes(ctx):
    svc, wm, team = ctx
    svc.link_dataset(_USER, team.id, "A")
    svc.unlink_dataset(_USER, team.id, "A")
    assert svc.list_linked_datasets(team.id, user=_USER) == []


def test_link_missing_dataset_raises(ctx):
    svc, wm, team = ctx
    with pytest.raises(ValueError):
        svc.link_dataset(_USER, team.id, "does-not-exist")


def test_available_datasets_excludes_nothing_here(ctx):
    svc, wm, team = ctx
    avail = svc.available_datasets(workspace_id=None)
    assert {d.id for d in avail} == {"A", "B"}
