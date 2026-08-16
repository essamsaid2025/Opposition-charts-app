"""First-Team Player Intelligence — FT-P6: notes, attachments, media & external links.

All player-owned assets are anchored to player_id and are independent of the active
dataset. Notes are typed (player/match/video/event) with edit/delete; attachments'
binaries live in FileStorage (never in Player.document); external links are validated
(no javascript:); everything survives reload and active-dataset switching. Reuses the
existing repositories/storage — no second storage system. Scouting untouched.
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
    return User(email="coach@club.com", name="Coach", role=Role.SUPER_ADMIN, provider_id="dev")


def _viewer():
    from fap.identity.models import User
    from fap.identity.roles import Role
    return User(email="scout@club.com", name="Scout", role=Role.READ_ONLY, provider_id="dev")


@pytest.fixture()
def ctx(tmp_path):
    from fap.bootstrap import init_platform
    platform = init_platform(settings=_settings(tmp_path))
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    p = platform.players.create_player(user, display_name="Mamadu Bah", primary_position="CF",
                                       workspace_id=ws.id)
    try:
        yield platform, user, ws, p, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


# ---- notes: typed CRUD + persistence + ownership ----
def test_note_crud_and_types(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    n1 = sc.add_note(user, p.id, "Improving off-ball movement.", kind="player", title="Development")
    sc.add_note(user, p.id, "Strong progression vs Malta.", kind="match", match_id="M1")
    sc.add_note(user, p.id, "Excellent movement attacking depth.", kind="video", video_id="V1")
    assert len(sc.list_notes(p.id)) == 3
    assert len(sc.list_notes(p.id, kind="match")) == 1
    assert sc.list_notes(p.id, kind="player")[0].document.get("title") == "Development"
    sc.update_note(user, n1.id, body="Much improved off-ball movement.", category="technical")
    got = next(n for n in sc.list_notes(p.id) if n.id == n1.id)
    assert got.body == "Much improved off-ball movement." and got.document.get("category") == "technical"
    sc.delete_note(user, n1.id)
    assert len(sc.list_notes(p.id)) == 2 and all(n.id != n1.id for n in sc.list_notes(p.id))


def test_notes_persist_after_reload(ctx):
    platform, user, ws, p, tmp_path = ctx
    sc = platform.players
    sc.add_note(user, p.id, "Persistent note", kind="player", title="T")
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        notes = p2.players.list_notes(p.id)
        assert len(notes) == 1 and notes[0].document.get("title") == "T" and notes[0].kind == "player"
    finally:
        p2.db.close()


def test_notes_owned_by_player(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    q = sc.create_player(user, display_name="Other", primary_position="CB", workspace_id=ws.id)
    sc.add_note(user, p.id, "note for P", kind="player")
    assert sc.list_notes(q.id) == []                      # not leaked to another player


# ---- attachments: FileStorage binary, delete, ownership ----
def test_attachment_upload_retrieve_delete(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    d = sc.add_document(user, p.id, b"%PDF-1.4 fake", "Performance Report.pdf",
                        mime="application/pdf", kind="report")
    assert sc.document_bytes(d.id) == b"%PDF-1.4 fake"
    assert [x.filename for x in sc.list_documents(p.id)] == ["Performance Report.pdf"]
    sc.delete_document(user, d.id)
    assert sc.list_documents(p.id) == [] and sc.document_bytes(d.id) is None


def test_attachment_ownership_isolation(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    q = sc.create_player(user, display_name="Other", primary_position="CB", workspace_id=ws.id)
    sc.add_document(user, p.id, b"data", "p.pdf", mime="application/pdf")
    assert sc.list_documents(q.id) == []


def test_no_binary_in_document(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    sc.add_document(user, p.id, b"%PDF binary bytes here", "r.pdf", mime="application/pdf")
    sc.add_note(user, p.id, "note", kind="player")
    doc = sc.get_player(p.id).document
    blob = repr(doc)
    assert "%PDF" not in blob and "binary bytes" not in blob   # bytes stay in FileStorage

    def scan(o):
        import matplotlib.figure as mf
        if isinstance(o, (bytes, bytearray, pd.DataFrame, pd.Series, mf.Figure)):
            return True
        if isinstance(o, dict):
            return any(scan(x) for x in o.values())
        if isinstance(o, (list, tuple)):
            return any(scan(x) for x in o)
        return False
    assert scan(doc) is False


# ---- external links: CRUD + validation ----
def test_external_links_crud_and_validation(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    l = sc.add_link(user, p.id, "fbref.com/player/x", title="FBref", category="stats")
    assert l["url"] == "https://fbref.com/player/x" and l["title"] == "FBref"
    sc.add_link(user, p.id, "https://transfermarkt.com/x")
    assert len(sc.list_links(p.id)) == 2
    for bad in ("javascript:alert(1)", "data:text/html,x", "vbscript:x", "  "):
        with pytest.raises(ValueError):
            sc.add_link(user, p.id, bad)
    sc.delete_link(user, p.id, l["id"])
    assert len(sc.list_links(p.id)) == 1 and all(x["id"] != l["id"] for x in sc.list_links(p.id))


# ---- media: image + club logo persistence + delete ----
def test_image_and_logo_persist_and_delete(ctx):
    platform, user, ws, p, tmp_path = ctx
    sc = platform.players
    im = sc.add_image(user, p.id, _PNG, "image/png", kind="profile")
    sc.set_club_logo(user, p.id, _PNG, "image/png")
    pl = sc.get_player(p.id)
    assert pl.profile_image_id and pl.club_logo_id
    assert sc.image_bytes(pl.profile_image_id) == _PNG and sc.image_bytes(pl.club_logo_id) == _PNG
    # reload
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        pl2 = p2.players.get_player(p.id)
        assert pl2.profile_image_id and pl2.club_logo_id
        assert p2.players.image_bytes(pl2.club_logo_id) == _PNG
    finally:
        p2.db.close()


def test_missing_image_safe(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    assert sc.image_bytes("nonexistent-id") is None       # no exception, no fabrication


# ---- active-dataset independence of player-owned assets ----
def test_player_owned_assets_survive_active_switch(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    # some player-owned assets
    sc.add_note(user, p.id, "note", kind="player")
    sc.add_document(user, p.id, b"data", "a.pdf", mime="application/pdf")
    sc.add_link(user, p.id, "fbref.com/x")
    sc.add_image(user, p.id, _PNG, "image/png", kind="profile")
    # an event dataset activated, then switched — must not touch player-owned assets
    dh = platform.datahub
    _csv = b"event_type,x,y,team,player,minute,match_id\npass,1,2,H,X,1,M1\n"
    d1 = dh.save_dataset(user, dh.analyze(_csv, "d1.csv").import_result,
                         name="D1", workspace_id=ws.id, metadata={})
    d2 = dh.save_dataset(user, dh.analyze(_csv, "d2.csv").import_result,
                         name="D2", workspace_id=ws.id, metadata={})
    dh.choose(user, d1.id)
    dh.choose(user, d2.id)
    assert len(sc.list_notes(p.id)) == 1
    assert len(sc.list_documents(p.id)) == 1
    assert len(sc.list_links(p.id)) == 1
    assert sc.get_player(p.id).profile_image_id


# ---- permissions ----
def test_viewer_cannot_mutate(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    from fap.core.exceptions import AuthError
    viewer = _viewer()
    for call in (lambda: sc.add_note(viewer, p.id, "x", kind="player"),
                 lambda: sc.add_document(viewer, p.id, b"d", "f.pdf", mime="application/pdf"),
                 lambda: sc.add_link(viewer, p.id, "https://x.com"),
                 lambda: sc.set_club_logo(viewer, p.id, _PNG, "image/png")):
        with pytest.raises((AuthError, PermissionError, Exception)):
            call()
    # viewer CAN read
    sc.add_note(user, p.id, "readable", kind="player")
    assert len(sc.list_notes(p.id)) == 1


# ---- legacy player renders/reads cleanly ----
def test_legacy_player_reads_empty(ctx):
    platform, user, ws, p, _ = ctx
    sc = platform.players
    q = sc.create_player(user, display_name="Legacy", primary_position="CF", workspace_id=ws.id)
    assert sc.list_notes(q.id) == [] and sc.list_documents(q.id) == [] and sc.list_links(q.id) == []
    assert sc.list_player_visualizations(q.id) == [] and sc.player_matches(user, q.id) == []


# ---- UI render (bare mode; real Notes & Files tab) ----
class _Shell:
    def __init__(self, platform, user, ws):
        self.user = user
        self.platform = platform
        self.wm = platform.workspace_manager
        self.workspace_id = ws.id

    def goto(self, _):
        pass


def _page(edit=True):
    from fap.ui.builtin.players import FirstTeamPlayersPage
    pg = FirstTeamPlayersPage()
    pg._can_edit = edit
    pg._can_delete = edit
    pg._can_report = True
    return pg


def test_notes_files_tab_renders(ctx):
    import streamlit as st
    platform, user, ws, p, _ = ctx
    st.session_state.clear()
    sc = platform.players
    sc.add_note(user, p.id, "note", kind="player", title="Dev")
    sc.add_document(user, p.id, b"data", "a.pdf", mime="application/pdf", kind="report")
    sc.add_link(user, p.id, "fbref.com/x", title="FBref")
    _page(edit=True)._tab_notes_files(_Shell(platform, user, ws), sc, p.id, sc.get_player(p.id))


def test_notes_files_tab_legacy_clean(ctx):
    import streamlit as st
    platform, user, ws, p, _ = ctx
    st.session_state.clear()
    sc = platform.players
    q = sc.create_player(user, display_name="Legacy", primary_position="CF", workspace_id=ws.id)
    _page(edit=True)._tab_notes_files(_Shell(platform, user, ws), sc, q.id, sc.get_player(q.id))
