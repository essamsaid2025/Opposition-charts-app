"""Player Evaluation report for a Teams roster player (fap.teams.player_report + service).

A professional dossier for the technical director: the player's profile + photo + team
crest, the Development trend, saved charts, video QR codes, notes and an analyst-authored
evaluation, rendered to PDF through the EXISTING report engine. These tests pin the
document structure, the no-fabrication rule, the persisted evaluation round-trip and a
real PDF render.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.db.engine import Database
from fap.teams.service import TeamService
from fap.teams.player_report import build_player_report_document, META_KIND

_USER = SimpleNamespace(email="coach@club.com")


def _full_data():
    return {"name": "Ahmed Sami", "team_name": "Al Ahly U19", "position": "CM", "age": 18,
            "foot": "right", "height_cm": 178, "shirt": "8", "contract": "2027",
            "dashboard": {"appearances": 4, "minutes": 320, "goals": 1, "assists": 0,
                          "passes": 160, "pass_completion": 81.0, "shots": 6,
                          "team_matches": 4, "linked_matches": 4},
            "development_columns": ["Match", "Passes"], "development_table": [["vs Opp1", 43]],
            "form": [{"label": "Passes", "last5": "50", "season": "45", "trend": "↑"}],
            "videos": [{"title": "Goal", "url": "https://x.y/z", "qr_b64": "QUJD", "match_label": "vs Opp3"}],
            "player_notes": [{"date": "2026-08-01", "author": "coach", "text": "Good."}],
            "team_notes": [{"date": "2026-08-02", "text": "Pressing improved."}],
            "evaluation": {"rating": "B+", "summary": "Reliable.", "strengths": "Vision\nPressing",
                           "dev_areas": "Aerial", "recommendation": "develop", "author": "coach"}}


def test_document_has_expected_sections_in_order():
    doc = build_player_report_document(_full_data(),
                                       chart_images={"development": b"x", "heatmap": b"y"},
                                       saved_charts=[{"title": "Pass map", "png": b"p"}])
    ids = [s.id for s in doc.sections]
    assert ids == ["summary", "evaluation", "profile", "development", "form", "heatmap",
                   "visual", "video_1", "notes"]
    assert doc.meta["kind"] == META_KIND
    assert doc.title == "Player Evaluation — Ahmed Sami"
    assert doc.cover.player == "Ahmed Sami" and doc.cover.club == "Al Ahly U19"


def test_no_fabrication_when_data_is_empty():
    # a player with only a name: no dashboard/charts/videos/notes/evaluation.
    doc = build_player_report_document({"name": "X"})
    ids = [s.id for s in doc.sections]
    # only summary KPIs (honest "—") + the profile (just the name) — nothing invented:
    # no charts, no heatmap, no videos, no notes, no evaluation.
    assert ids == ["summary", "profile"]
    for banned in ("visual", "heatmap", "video_1", "notes", "evaluation", "development", "form"):
        assert banned not in ids


def test_evaluation_included_verbatim():
    doc = build_player_report_document(_full_data())
    ev = next(s for s in doc.sections if s.id == "evaluation")
    md = ev.markdown
    assert "Reliable." in md and "Vision" in md and "Aerial" in md
    labels = {k.label: k.value for k in ev.kpis}
    assert labels["Overall rating"] == "B+"
    assert labels["Recommendation"] == "Develop — targeted improvement plan"


def test_evaluation_roundtrip_and_pdf_render(tmp_path):
    svc = TeamService(Database(tmp_path / "t.sqlite3"))
    team = svc.create_team(_USER, "U19", kind="academy", age_group="U19")
    mem = svc.add_member(_USER, team.id, player_name="Ahmed Sami", role="CM", shirt_number="8")
    svc.set_player_evaluation(_USER, team.id, mem.id,
                              {"rating": "A-", "summary": "Top", "recommendation": "promote"})
    got = svc.get_player_evaluation(team.id, mem.id)
    assert got["rating"] == "A-" and got["recommendation"] == "promote"
    # saving again replaces (only the latest is kept)
    svc.set_player_evaluation(_USER, team.id, mem.id, {"rating": "B"})
    assert svc.get_player_evaluation(team.id, mem.id)["rating"] == "B"
    assert len(svc.list_media(team.id, kind="evaluation", member_id=mem.id)) == 1
    # full render path → a real PDF, even with no linked match data (sections just omit)
    rep = svc.render_player_report(_USER, team.id, mem.id, fmt="pdf")
    assert rep.content[:4] == b"%PDF" and rep.filename.endswith(".pdf")
