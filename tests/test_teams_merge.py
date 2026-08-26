"""Players folded into Teams: two team groups (Opponents vs Our teams), a per-match
player development trend, and the standalone Players page hidden from nav (still
registered). The player detail stays active-independent and keeps the player id.
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

from fap.teams.models import OPPONENT_KIND, TEAM_KINDS, team_group
from fap.teams.service import TeamService


# ================================================================ team groups
def test_opponent_kind_and_grouping():
    assert "opponent" in TEAM_KINDS and OPPONENT_KIND == "opponent"
    assert team_group("opponent") == "opponents"
    assert team_group("club") == "our_teams" and team_group("academy") == "our_teams"


# ================================================================ per-match metrics
def test_match_player_metrics_are_honest_counts():
    df = pd.DataFrame({
        "event_type": ["pass", "pass", "pass", "shot", "carry"],
        "outcome": ["successful", "unsuccessful", "successful", "goal", ""],
        "minute": [5, 20, 35, 60, 70]})
    m = TeamService._match_player_metrics(df)
    assert m["events"] == 5 and m["passes"] == 3 and m["completed_passes"] == 2
    assert m["shots"] == 1 and m["goals"] == 1 and m["minutes"] == 70
    assert m["pass_completion"] == round(200 / 3, 1)


def test_metrics_skip_absent_columns():
    m = TeamService._match_player_metrics(pd.DataFrame({"event_type": ["carry", "carry"]}))
    assert m["events"] == 2 and m["passes"] == 0 and m["pass_completion"] is None


# ================================================================ players folded into Teams
def test_players_page_hidden_but_registered():
    from fap.identity.roles import Role
    from fap.ui.page import HIDDEN_PAGE_IDS, get_page, load_builtin_pages, visible_pages
    load_builtin_pages()
    assert "players" in HIDDEN_PAGE_IDS
    assert get_page("players") is not None                     # still resolvable
    ids = {p.info.id for p in visible_pages(Role.SUPER_ADMIN)}
    assert "players" not in ids and "teams" in ids             # Teams is the home


# ================================================================ progression (integration)
def test_player_progression_across_matches(tmp_path):
    from dataclasses import replace
    from fap.bootstrap import init_platform
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
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
        teams = platform.teams
        team = teams.create_team(user, "First Team", kind="club")
        teams.add_member(user, team.id, player_name="Messi")

        # two matches, each with its own linked event dataset containing Messi events
        for i, (passes, opp) in enumerate([(3, "Rival A"), (6, "Rival B")], 1):
            rows = [{"event_type": "pass", "player": "Messi", "outcome": "successful",
                     "x": 20 + j, "y": 30 + j, "minute": j, "team": "First Team",
                     "match_id": f"m{i}"} for j in range(passes)]   # distinct (no dedup)
            csv = pd.DataFrame(rows).to_csv(index=False).encode()
            ar = platform.datahub.analyze(csv, f"match{i}.csv")
            ds = platform.datahub.save_dataset(user, ar.import_result, name=f"Match {i}",
                                               workspace_id=ws.id)
            teams.create_match(user, team.id, opponent=opp, match_date=f"2025-0{i}-01",
                               dataset_id=ds.id, match_id=f"m{i}")

        member = teams.list_members(team.id)[0]
        prog = teams.player_progression(team.id, member.id)
        assert len(prog) == 2
        assert prog[0]["passes"] == 3 and prog[1]["passes"] == 6     # oldest -> newest
        assert prog[0]["opponent"] == "Rival A"
        dash = teams.player_dashboard(team.id, member.id)
        assert dash["appearances"] == 2 and dash["passes"] == 9      # dashboard = sum

        # the premium hero + dashboard must render without error (bare mode)
        import streamlit as st
        from types import SimpleNamespace
        from fap.ui.page import get_page, load_builtin_pages
        st.session_state.clear()
        load_builtin_pages()
        page = get_page("teams")
        page._can_edit = True
        shell = SimpleNamespace(user=user, wm=platform.workspace_manager,
                                workspace_id=ws.id,
                                platform=SimpleNamespace(teams=teams), goto=lambda *a: None)
        page._member_hero(shell, teams, team, member)       # premium hero + snapshot
        page._player_overview(shell, teams, member)         # dossier dashboard
    finally:
        platform.db.close()
