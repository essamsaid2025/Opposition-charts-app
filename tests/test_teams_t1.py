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


def test_teams_page_is_registered():
    from fap.ui.page import load_builtin_pages, page_registry
    load_builtin_pages()
    assert "teams" in page_registry
    page = page_registry.create("teams")
    assert page.info.name == "Teams" and page.section == "Squad"
