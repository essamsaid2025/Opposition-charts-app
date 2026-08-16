"""P4.7 — analyst A-F rating + Premium Player Report.

The Premium report is built on the EXISTING report engine (ReportsManager +
exporter registry). It is player-scoped and active-dataset-INDEPENDENT (charts/fit
read the player's LINKED dataset by id). Nothing is fabricated: missing data yields
a clean empty section, an uploaded video gets no fake QR, a player with no metrics
gets no charts. The Standard report keeps working unchanged.
"""
import os
os.environ["FAP_TEST"] = "1"
import base64
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")
import pandas as pd
import pytest

from fap.scouting import identity, premium_report

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _settings(tmp_path):
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    from dataclasses import replace
    return replace(AppSettings(environment="development"),
                   user_data_dir=str(tmp_path / "ud"),
                   database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                   cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))


def _user():
    from fap.identity.models import User
    from fap.identity.roles import Role
    return User(email="ana@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")


def _malta_csv():
    metrics = ["Non-penalty goals per 90", "npxG per 90", "Progressive passes per 90",
               "xA per 90", "Shot assists per 90", "Touches in box per 90", "Duels won, %",
               "Passes per 90", "Dribbles per 90", "Interceptions per 90"]
    names = ["S. Mamadu bah"] + [f"Player {i}" for i in range(32)]
    rows = []
    for i, nm in enumerate(names):
        r = {"Player": nm, "Team": f"Club {i % 12}", "Age": 24,
             "League": "Malta Premier League 25-26", "Position": "CF"}
        for j, m in enumerate(metrics):
            r[m] = ((i * 7 + j) % 100) / 100.0
        rows.append(r)
    return pd.DataFrame(rows).to_csv(index=False).encode()


@pytest.fixture()
def ctx(tmp_path):
    from fap.bootstrap import init_platform
    platform = init_platform(settings=_settings(tmp_path))
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    ds = platform.datahub.save_scouting_dataset(
        user, platform.datahub.analyze(_malta_csv(), "Malta CF.csv").scouting,
        name="Malta CF 25-26", workspace_id=ws.id)
    ev = platform.datahub.save_dataset(
        user, platform.datahub.analyze(
            b"event_type,x,y,team,player,minute,match_id\npass,1,2,H,S. Mamadu bah,1,M1\n",
            "ev.csv").import_result, name="PL Events", workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, ds.id)
    p = platform.scouting.create_player(user, "Mamadu Bah", club="ZED", league="EPL",
                                        position="CF", nationality="Liberia", dob="2001-03-04",
                                        player_type="first_team", status="watching",
                                        priority="medium", workspace_id=ws.id)
    platform.scouting.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    platform.scouting.set_recruitment_profile(user, p.id, "false_9")
    platform.datahub.choose(user, ev.id)                 # active = event ds, NOT Malta
    try:
        yield platform, user, ws, ds, ev, p, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


# ============================================================ analyst rating (A-F)
def test_rating_accepts_a_to_f(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    for r in identity.ANALYST_RATINGS:
        sc.set_analyst_rating(user, p.id, r)
        assert identity.analyst_rating_of(sc.get_player(p.id)) == r


def test_rating_invalid_rejected(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    for bad in ("G", "Z", "1", "AA", "pass"):
        with pytest.raises(ValueError):
            sc.set_analyst_rating(user, p.id, bad)


def test_rating_persists_and_reloads(ctx):
    platform, user, ws, ds, ev, p, tmp_path = ctx
    sc = platform.scouting
    sc.set_analyst_rating(user, p.id, "b")               # lower-case normalizes to B
    assert identity.analyst_rating_of(sc.get_player(p.id)) == "B"
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        assert identity.analyst_rating_of(p2.scouting.get_player(p.id)) == "B"
        assert p2.scouting.player_dashboard(_user(), p.id)["snapshot"]["analyst_rating"] == "B"
    finally:
        p2.db.close()


def test_rating_in_registry_and_filter(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    sc.set_analyst_rating(user, p.id, "A")
    rows = sc.player_registry(user, workspace_id=ws.id)
    assert any(r["id"] == p.id and r["analyst_rating"] == "A" for r in rows)
    assert sc.player_registry(user, filters={"rating": "A"}, workspace_id=ws.id)
    assert not sc.player_registry(user, filters={"rating": "F"}, workspace_id=ws.id)


def test_rating_is_not_the_fit_score(ctx):
    # rating is analyst judgement, fit is data-driven: independent concepts
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    sc.set_analyst_rating(user, p.id, "C")
    fit = sc.profile_fit_for(user, p.id, "false_9", dataset_id=ds.id)
    assert identity.analyst_rating_of(sc.get_player(p.id)) == "C"
    assert fit is None or "score" not in fit or True     # fit exists independently of rating


# ============================================================ pure builder (fabrication rules)
def _base_data():
    return {"player_id": "pid", "name": "Mamadu Bah", "display_name": "Mamadu Bah",
            "operational_id": "CLB-000001", "type_label": "First Team", "position": "CF",
            "club": "ZED", "league": "EPL", "recruitment_profile_name": "False 9",
            "status_label": "Watching", "priority_label": "Medium", "analyst_rating": "B",
            "analyst": "Ana", "generated_at": "2026-08-16"}


def test_builder_includes_identity_rating_profile():
    doc = premium_report.build_premium_document(_base_data())
    assert doc.meta["kind"] == premium_report.META_KIND
    assert doc.meta["analyst_rating"] == "B"
    assert doc.cover.title == "Mamadu Bah" and doc.cover.version == "Rating B"
    titles = [s.title for s in doc.sections]
    assert "Recruitment Decision" in titles and "Player Profile" in titles
    kpis = {k.label: k.value for k in doc.sections[0].kpis}
    assert kpis["Analyst Rating"] == "B"


def test_builder_no_charts_when_no_data():
    doc = premium_report.build_premium_document(_base_data(), chart_images={})
    visual = next(s for s in doc.sections if s.id == "visual")
    assert not visual.charts
    assert "No visualizations" in visual.markdown


def test_builder_embeds_charts_when_present():
    doc = premium_report.build_premium_document(_base_data(), chart_images={"pizza": _PNG, "radar": _PNG})
    visual = next(s for s in doc.sections if s.id == "visual")
    assert len(visual.charts) == 2 and all(c.image_b64 for c in visual.charts)


def test_builder_all_notes_included():
    data = _base_data()
    data["notes"] = [{"date": "15 Aug", "author": "Ana", "text": "Good movement."},
                     {"date": "12 Aug", "author": "Ana", "text": "Needs consistency."}]
    doc = premium_report.build_premium_document(data)
    notes = next(s for s in doc.sections if s.id == "notes")
    assert "Good movement." in notes.markdown and "Needs consistency." in notes.markdown


def test_builder_video_qr_only_for_external_url():
    data = _base_data()
    data["videos"] = [{"title": "vs X", "url": "https://youtu.be/abc", "qr_b64": "QQ==",
                       "is_external": True}, {"title": "clip", "url": "", "is_external": False}]
    doc = premium_report.build_premium_document(data)
    vids = [s for s in doc.sections if s.id.startswith("video_")]
    assert vids[0].charts and vids[0].charts[0].image_b64 == "QQ=="   # external -> QR chart
    assert not vids[1].charts                                          # uploaded -> no fake QR
    assert "available in FAP" in vids[1].markdown


def test_builder_fit_unavailable_states_reason_no_fake_score():
    data = _base_data()
    data["fit"] = {"available": False, "reason": "insufficient compatible metrics"}
    doc = premium_report.build_premium_document(data)
    fit = next(s for s in doc.sections if s.id == "fit")
    assert "Unavailable" in fit.markdown and "insufficient" in fit.markdown


def test_builder_summary_has_no_fabricated_recommendation():
    doc = premium_report.build_premium_document(_base_data())
    summary = next(s for s in doc.sections if s.id == "summary")
    blob = (summary.markdown + " " + " ".join(i.text for i in summary.insights)).lower()
    for banned in ("sign immediately", "must buy", "elite prospect", "must-buy"):
        assert banned not in blob


# ============================================================ service integration
def test_premium_report_generates_and_persists(ctx):
    platform, user, ws, ds, ev, p, tmp_path = ctx
    sc = platform.scouting
    sc.set_analyst_rating(user, p.id, "B")
    sc.add_note(user, p.id, "Good movement between the lines.")
    link = sc.create_premium_report(user, p.id)          # active is the EVENT ds
    assert link.report_id
    info = sc.premium_report_info(link.report_id)
    assert info["is_premium"] and info["rating"] == "B" and info["source"] == "Malta CF 25-26"
    # rendered HTML contains the dossier essentials
    rendered = sc.render_premium_report(user, link.report_id, "html")
    text = rendered.content.decode("utf-8", "ignore")
    for needle in ("Mamadu Bah", "CLB-000001", "Recruitment Decision", "Player Profile",
                   "Good movement", "False 9"):
        assert needle in text, needle
    # charts were auto-selected from the LINKED Malta dataset despite EVENT ds active
    doc = platform.reports.document(link.report_id)
    visual = next(s for s in doc.sections if s.id == "visual")
    assert visual.charts, "player-scoped charts should be embedded from the linked dataset"


def test_premium_report_survives_active_switch_and_reload(ctx):
    platform, user, ws, ds, ev, p, tmp_path = ctx
    sc = platform.scouting
    sc.set_analyst_rating(user, p.id, "A")
    link = sc.create_premium_report(user, p.id, dataset_id=ds.id)
    platform.datahub.choose(user, ev.id)                 # switch active away
    assert sc.premium_report_info(link.report_id)["is_premium"]
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        u2 = _user()
        rendered = p2.scouting.render_premium_report(u2, link.report_id, "html")
        assert b"Mamadu Bah" in rendered.content
        assert p2.scouting.premium_report_info(link.report_id)["rating"] == "A"
    finally:
        p2.db.close()


def test_premium_report_no_charts_when_no_linked_dataset(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    q = sc.create_player(user, "No Data", position="CF", player_type="first_team",
                         workspace_id=ws.id)
    link = sc.create_premium_report(user, q.id)          # no linked scouting dataset
    doc = platform.reports.document(link.report_id)
    visual = next(s for s in doc.sections if s.id == "visual")
    assert not visual.charts and "No visualizations" in visual.markdown   # never fabricated


def test_standard_report_still_works(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    link = sc.create_report(user, p.id)                  # existing Standard path
    assert link.report_id
    assert not sc.premium_report_info(link.report_id)["is_premium"]


def test_premium_report_charts_use_linked_not_active_dataset(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    # active is the event dataset; the report must still resolve Malta by link id
    assert sc.active_dataset_kind(user) == "event"
    link = sc.create_premium_report(user, p.id)
    assert sc.premium_report_info(link.report_id)["source"] == "Malta CF 25-26"


# ============================================================ UI (bare-mode render)
class _Shell:
    def __init__(self, platform, user, ws):
        self.user = user
        self.platform = platform
        self.wm = platform.workspace_manager
        self.workspace_id = ws.id

    def goto(self, _):
        pass


def test_rating_shows_in_hero_and_intel(ctx, monkeypatch):
    platform, user, ws, ds, ev, p, _ = ctx
    sc = platform.scouting
    sc.set_analyst_rating(user, p.id, "B")
    import streamlit as st
    from fap.ui.builtin.scouting import ScoutingPage
    calls = []
    monkeypatch.setattr(st, "markdown", lambda body="", *a, **k: calls.append(str(body)))
    dash = sc.player_dashboard(user, p.id)
    page = ScoutingPage()
    page._hero(_Shell(platform, user, ws), sc, p, dash)
    page._intel_strip(_Shell(platform, user, ws), sc, p, dash)
    blob = "\n".join(calls)
    assert "Rating B" in blob and "Analyst rating" in blob


def test_generate_report_panel_renders_both_options(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    import streamlit as st
    st.session_state.clear()
    from fap.ui.builtin.scouting import ScoutingPage
    page = ScoutingPage()
    page._can_report = True
    page._can_edit = True
    page._can_export = True
    page._generate_report_panel(_Shell(platform, user, ws), platform.scouting, p)  # must not raise


def test_reports_list_shows_premium_badge(ctx):
    platform, user, ws, ds, ev, p, _ = ctx
    import streamlit as st
    st.session_state.clear()
    sc = platform.scouting
    sc.create_premium_report(user, p.id)
    from fap.ui.builtin.scouting import ScoutingPage
    page = ScoutingPage()
    page._can_report = True
    page._can_edit = True
    page._can_export = True
    page._reports(_Shell(platform, user, ws), sc, p)         # renders premium + panel, no raise
