"""Scouting Player Dossier UI redesign.

The player detail page renders a premium recruitment dossier: a hero (photo/crest,
name, pathway/status/priority badges, operational id, recruitment profile, football
context), a compact snapshot grid, a recruitment-intelligence strip, and five
sections (Overview, Analysis, Evidence, Media, Reports). These tests prove the hero
content is built from the real player/document (never fabricated), images fall back
safely, the same architecture works for first-team / academy / trialist pathways,
and the full page renders without raising. Backend services are untouched.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")
import pandas as pd
import pytest
import streamlit as st

from fap.theme import components as C
from fap.ui.builtin import scouting as SC
from fap.ui.builtin.scouting import ScoutingPage

# a valid 1x1 PNG
_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
        b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
        b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


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
    return User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")


def _malta_csv():
    metrics = ["Non-penalty goals per 90", "npxG per 90", "Progressive passes per 90",
               "xA per 90", "Shot assists per 90", "Touches in box per 90", "Duels won, %"]
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
    platform.datahub.choose(user, ds.id)
    try:
        yield platform, user, ws, ds, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


class _Shell:
    def __init__(self, platform, user, ws):
        self.user = user
        self.platform = platform
        self.wm = platform.workspace_manager
        self.workspace_id = ws.id

    def goto(self, _):
        pass


def _first_team(sc, user, ws, *, photo=True, logo=True, profile="false_9"):
    p = sc.create_player(user, "Mamadu Bah", club="ZED", league="EPL", position="CF",
                         nationality="Liberia", dob="2001-03-04", player_type="first_team",
                         status="watching", priority="medium", workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    if profile:
        sc.set_recruitment_profile(user, p.id, profile)
    if photo:
        sc.add_image(user, p.id, _PNG, "image/png", kind="profile")
    if logo:
        sc.set_club_logo(user, p.id, _PNG, "image/png")
    return sc.get_player(p.id)


def _capture(monkeypatch):
    """Collect every HTML string written through st.markdown (the dossier renders
    its hero/snapshot/intel via st.markdown)."""
    calls = []
    monkeypatch.setattr(st, "markdown", lambda body="", *a, **k: calls.append(str(body)))
    return calls


# --------------------------------------------------------------- _img_data_uri
def test_img_data_uri_png_and_safe_fallback():
    uri = SC._img_data_uri(_PNG)
    assert uri.startswith("data:image/png;base64,")
    assert SC._img_data_uri(None) == ""
    assert SC._img_data_uri(b"") == ""


# --------------------------------------------------------------- pure hero builder
def test_player_hero_html_shows_identity_and_photo():
    html = C.player_hero_html(
        "Mamadu Bah", position_line="CF · ZED", photo_uri="data:image/png;base64,AAA",
        initials="MB", logo_uri="data:image/png;base64,BBB",
        badges_html='<span class="fap-badge info">First Team</span>',
        operational_id="CLB-000001", profile_name="False 9",
        context=[("Club", "ZED"), ("Age", "25")])
    assert "CLB-000001" in html and "False 9" in html
    assert 'src="data:image/png;base64,AAA"' in html         # photo used
    assert "class=\"club\"" in html                          # club crest present
    assert "First Team" in html


def test_player_hero_html_initials_fallback_no_broken_image():
    html = C.player_hero_html("No Photo", initials="np")
    assert '<span class="ini">NP</span>' in html              # initials, upper-cased
    assert "<img" not in html                                 # never a broken <img>


def test_intel_strip_kinds():
    html = C.intel_strip_html([("Profile fit", "82%", "good"), ("Priority", "—", "muted")])
    assert "fap-intel good" in html and "82%" in html
    assert "fap-intel muted" in html


# --------------------------------------------------------------- hero from real data
def test_hero_renders_operational_id_and_profile_from_player(ctx, monkeypatch):
    platform, user, ws, ds, _ = ctx
    sc = platform.scouting
    p = _first_team(sc, user, ws)
    dash = sc.player_dashboard(user, p.id)
    calls = _capture(monkeypatch)
    ScoutingPage()._hero(_Shell(platform, user, ws), sc, p, dash)
    blob = "\n".join(calls)
    from fap.scouting import identity
    op = identity.operational_id_of(p)
    assert op and op.startswith("CLB-") and op in blob         # operational id visible
    assert "False 9" in blob                                   # recruitment profile visible
    assert "data:image/png;base64," in blob                    # stored photo used
    assert "First Team" in blob


def test_hero_falls_back_when_images_missing(ctx, monkeypatch):
    platform, user, ws, ds, _ = ctx
    sc = platform.scouting
    p = _first_team(sc, user, ws, photo=False, logo=False)
    dash = sc.player_dashboard(user, p.id)
    calls = _capture(monkeypatch)
    ScoutingPage()._hero(_Shell(platform, user, ws), sc, p, dash)   # must not raise
    blob = "\n".join(calls)
    assert '<span class="ini">' in blob                        # initials avatar
    assert "data:image" not in blob                            # no image emitted


# --------------------------------------------------------------- intel strip: real fit/coverage
def test_intel_strip_shows_coverage_and_fit(ctx, monkeypatch):
    platform, user, ws, ds, _ = ctx
    sc = platform.scouting
    p = _first_team(sc, user, ws)
    dash = sc.player_dashboard(user, p.id)
    calls = _capture(monkeypatch)
    ScoutingPage()._intel_strip(_Shell(platform, user, ws), sc, p, dash)
    blob = "\n".join(calls)
    assert "Recruitment intelligence" in blob
    assert "metrics" in blob                                   # data coverage from Malta
    assert "Watching" in blob                                  # status label


# --------------------------------------------------------------- full page render, all pathways
@pytest.mark.parametrize("ptype,prefix", [
    ("first_team", "CLB-"), ("academy", "ACD-"), ("trialist", "TRI-")])
def test_player_detail_renders_for_every_pathway(ctx, ptype, prefix):
    platform, user, ws, ds, _ = ctx
    sc = platform.scouting
    st.session_state.clear()
    p = sc.create_player(user, f"P {ptype}", club="ZED", position="CF",
                         player_type=ptype, workspace_id=ws.id)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    from fap.scouting import identity
    assert identity.operational_id_of(p).startswith(prefix)
    page = ScoutingPage()
    page._can_edit = True
    page._can_report = True
    page._can_export = True
    st.session_state[SC.SEL] = p.id
    page._player_detail(_Shell(platform, user, ws), sc, p.id)   # bare-mode; must not raise


def test_academy_intel_uses_development_emphasis(ctx, monkeypatch):
    platform, user, ws, ds, _ = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Youngster", position="CF", player_type="academy",
                         age_group="U18", workspace_id=ws.id)
    sc.set_academy_profile(user, p.id, stage="developing", technical_potential=80)
    dash = sc.player_dashboard(user, sc.get_player(p.id).id)
    calls = _capture(monkeypatch)
    ScoutingPage()._intel_strip(_Shell(platform, user, ws), sc, sc.get_player(p.id), dash)
    blob = "\n".join(calls)
    assert "Development intelligence" in blob                  # not recruitment framing
    assert "Technical" in blob and "80" in blob                # real potential shown
    assert "U18" in blob
