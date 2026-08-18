"""Teams T1 — Team model + storage (migration 14) + service CRUD + roster + page registration."""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.db.engine import Database
from fap.teams.service import TeamService

_USER = SimpleNamespace(email="coach@club.com")


def test_migration_14_creates_team_tables(tmp_path):
    db = Database(tmp_path / "t.sqlite3")                  # applies all migrations incl. 14
    rows = db.query("SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('teams','team_members')")
    assert {r["name"] for r in rows} == {"teams", "team_members"}


def test_team_crud_and_roster(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"))
    t = svc.create_team(_USER, "U19", kind="academy", age_group="U19", competition="Youth League")
    assert t.id and t.kind == "academy" and t.age_group == "U19"
    assert [x.id for x in svc.list_teams()] == [t.id]

    svc.update_team(_USER, t.id, season="2025/26", info="high-potential group")
    got = svc.get_team(t.id)
    assert got.season == "2025/26" and got.info == "high-potential group"

    m = svc.add_member(_USER, t.id, player_name="John Doe", operational_id="ACD-000001",
                       shirt_number="7", role="CM")
    assert m.id and svc.list_members(t.id)[0].player_name == "John Doe"

    summ = svc.team_summaries()[0]
    assert summ["members"] == 1 and summ["age_group"] == "U19" and summ["kind"] == "academy"

    svc.remove_member(_USER, m.id)
    assert svc.list_members(t.id) == []

    svc.delete_team(_USER, t.id)
    assert svc.list_teams() == []


class _Counter:
    """Minimal stand-in for WorkspaceManager.next_counter (monotonic per key)."""
    def __init__(self):
        self._c = {}

    def next_counter(self, key):
        self._c[key] = self._c.get(key, 0) + 1
        return self._c[key]


def test_member_gets_auto_unique_operational_id(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"), workspaces=_Counter())
    acad = svc.create_team(_USER, "U19", kind="academy", age_group="U19")
    club = svc.create_team(_USER, "First Team", kind="club")
    # no id supplied -> auto-assigned by squad kind (academy -> ACD, club -> CLB)
    a1 = svc.add_member(_USER, acad.id, player_name="A")
    b1 = svc.add_member(_USER, club.id, player_name="B")
    assert a1.operational_id.startswith("ACD-") and b1.operational_id.startswith("CLB-")
    # a second academy player gets a DIFFERENT (unique) ACD id
    a2 = svc.add_member(_USER, acad.id, player_name="C")
    assert a2.operational_id != a1.operational_id
    # an explicitly supplied id (e.g. an existing scouting player) is respected
    linked = svc.add_member(_USER, acad.id, player_name="D", operational_id="SCT-000042")
    assert linked.operational_id == "SCT-000042"


def test_linked_player_keeps_id_source_and_operational_id(tmp_path):
    # the T2 picker passes an existing player's id + operational id + source -> stored verbatim
    svc = TeamService(Database(tmp_path / "t.sqlite3"), workspaces=_Counter())
    t = svc.create_team(_USER, "First Team", kind="club")
    m = svc.add_member(_USER, t.id, player_name="Salah", operational_id="SCT-000007",
                       player_id="pid-123", source="scouting")
    got = svc.list_members(t.id)[0]
    assert got.player_id == "pid-123" and got.operational_id == "SCT-000007"
    assert got.source == "scouting" and got.player_name == "Salah"


def test_create_team_requires_name(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"))
    with pytest.raises(ValueError):
        svc.create_team(_USER, "   ")


def test_delete_team_cascades_members(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"))
    t = svc.create_team(_USER, "First Team", kind="club")
    svc.add_member(_USER, t.id, player_name="A", operational_id="CLB-000001")
    svc.add_member(_USER, t.id, player_name="B", operational_id="SCT-000002")
    assert len(svc.list_members(t.id)) == 2
    svc.delete_team(_USER, t.id)
    assert svc.list_members(t.id) == []                    # members removed with the team


def test_match_crud_score_and_result(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"))
    t = svc.create_team(_USER, "First Team", kind="club")
    m = svc.create_match(_USER, t.id, opponent="Barcelona", match_date="2025-09-14",
                         competition="La Liga", venue="home", our_score=2, opp_score=1,
                         formation="4-3-3", notes="great press")
    assert m.opponent == "Barcelona" and m.scoreline == "2-1" and m.result == "W"
    assert [x.id for x in svc.list_matches(t.id)] == [m.id]
    # summaries count matches
    assert svc.team_summaries()[0]["matches"] == 1
    # update: change score -> result flips; link a dataset (active-independent)
    svc.update_match(_USER, m.id, our_score=0, opp_score=3, dataset_id="ds-9", match_id="16073")
    g = svc.get_match(m.id)
    assert g.result == "L" and g.dataset_id == "ds-9" and g.match_id == "16073"
    svc.delete_match(_USER, m.id)
    assert svc.list_matches(t.id) == []


def test_match_requires_opponent_and_score_optional(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"))
    t = svc.create_team(_USER, "U19", kind="academy")
    with pytest.raises(ValueError):
        svc.create_match(_USER, t.id, opponent="  ")
    # score omitted -> no scoreline/result fabricated
    m = svc.create_match(_USER, t.id, opponent="Real Madrid")
    assert m.scoreline == "" and m.result == ""


def test_delete_team_cascades_matches(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"))
    t = svc.create_team(_USER, "First Team", kind="club")
    svc.create_match(_USER, t.id, opponent="A")
    svc.create_match(_USER, t.id, opponent="B")
    assert len(svc.list_matches(t.id)) == 2
    svc.delete_team(_USER, t.id)
    assert svc.list_matches(t.id) == []


class _MemStore:
    """In-memory ImageStorage/FileStorage stand-in (save/load/delete)."""
    def __init__(self):
        self._d = {}

    def save(self, fid, data, **kw):
        self._d[fid] = data

    def load(self, fid):
        return self._d.get(fid)

    def delete(self, fid):
        self._d.pop(fid, None)


def test_media_notes_videos_charts(tmp_path):
    imgs, files = _MemStore(), _MemStore()
    svc = TeamService(Database(tmp_path / "t.sqlite3"), images=imgs, files=files)
    t = svc.create_team(_USER, "First Team", kind="club")
    mt = svc.create_match(_USER, t.id, opponent="Barca")
    # team-level note + video-link ; match-level chart
    svc.add_note(_USER, t.id, title="Plan", body="press high")
    svc.add_video(_USER, t.id, url="https://youtu.be/abc", title="Full match")
    svc.add_chart(_USER, t.id, b"\x89PNG-bytes", "image/png", title="xG", match_id=mt.id)
    assert len(svc.list_media(t.id)) == 3
    assert len(svc.list_media(t.id, match_id="")) == 2          # team-level only
    match_media = svc.list_media(t.id, match_id=mt.id)
    assert len(match_media) == 1 and match_media[0].kind == "chart"
    assert svc.media_bytes(match_media[0]) == b"\x89PNG-bytes"   # image bytes round-trip
    # delete removes the row and the stored bytes
    svc.delete_media(_USER, match_media[0].id)
    assert svc.list_media(t.id, match_id=mt.id) == []


def test_add_note_requires_content(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"))
    t = svc.create_team(_USER, "X", kind="club")
    with pytest.raises(ValueError):
        svc.add_note(_USER, t.id, title="", body="")


def test_team_record_and_comparison(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"))
    t = svc.create_team(_USER, "First Team", kind="club")
    svc.create_match(_USER, t.id, opponent="A", our_score=2, opp_score=0)   # W
    svc.create_match(_USER, t.id, opponent="B", our_score=1, opp_score=1)   # D
    svc.create_match(_USER, t.id, opponent="C", our_score=0, opp_score=3)   # L
    svc.create_match(_USER, t.id, opponent="D")                            # no score -> not counted
    rec = svc.team_record(t.id)
    assert rec["played"] == 3 and rec["wins"] == 1 and rec["draws"] == 1 and rec["losses"] == 1
    assert rec["gf"] == 3 and rec["ga"] == 4 and rec["gd"] == -1 and rec["points"] == 4
    comp = svc.teams_comparison()
    assert comp[0]["name"] == "First Team" and comp[0]["played"] == 3 and comp[0]["points"] == 4


def test_delete_team_cascades_media(tmp_path):
    imgs = _MemStore()
    svc = TeamService(Database(tmp_path / "t.sqlite3"), images=imgs)
    t = svc.create_team(_USER, "X", kind="club")
    svc.add_note(_USER, t.id, title="n", body="b")
    svc.add_chart(_USER, t.id, b"img", "image/png", title="c")
    assert len(svc.list_media(t.id)) == 2
    svc.delete_team(_USER, t.id)
    assert svc.list_media(t.id) == []


def test_teams_page_is_the_real_page_not_the_placeholder():
    from fap.ui.page import load_builtin_pages, page_registry
    load_builtin_pages()
    assert "teams" in page_registry
    page = page_registry.create("teams")
    assert page.info.name == "Teams" and page.section == "Squad"
    # the REAL page lives in fap.ui.builtin.teams (not the removed placeholder)
    assert type(page).__module__ == "fap.ui.builtin.teams"
