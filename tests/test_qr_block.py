"""QR-code report block (a regular block kind, like image/chart).

Covers, per the same headless style as test_reports.py: QR PNG generation from a URL,
the qr_block factory + round-trip through editor_ops.add_block_to_page, the LayoutEngine
producing a correct "qr" RenderedElement, the player-external-video URL source path, and
the manual-URL fallback. The Streamlit picker itself isn't unit-testable, so we test the
pure data path it drives.
"""
import os
os.environ["FAP_TEST"] = "1"
import base64
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pytest

from fap.reports import (
    add_block, materialize_qr, qr_available, qr_block, qr_png,
)
from fap.reports.blocks import BLOCK_KINDS
from fap.reports.editor_ops import add_block_to_page
from fap.reports.layout import LayoutEngine
from fap.reports.models import Cover, ReportDocument
from fap.reports.studio import ReportStudio

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
URL = "https://youtu.be/dQw4w9WgXcQ"


# ---------------------------------------------------------------- generation
def test_qr_kind_registered():
    assert "qr" in BLOCK_KINDS


def test_qr_png_generates_valid_image_bytes():
    if not qr_available():
        pytest.skip("qrcode library not installed")
    data = qr_png(URL)
    assert data is not None and data[:8] == PNG_MAGIC and len(data) > 100


def test_qr_png_empty_url_returns_none():
    assert qr_png("") is None


# ---------------------------------------------------------------- factory + round-trip
def test_qr_block_factory_payload_shape():
    b = qr_block(URL, player_id="p1", video_id="v1", caption="Watch clip", title="QR Code")
    assert b.kind == "qr" and b.title == "QR Code"
    assert b.payload == {"url": URL, "player_id": "p1", "video_id": "v1", "caption": "Watch clip"}


def test_qr_block_round_trips_through_add_block_to_page():
    studio = ReportStudio.from_document(ReportDocument(id="d1", title="T", cover=Cover(title="T")))
    block = qr_block(URL, player_id="p1", video_id="v1", caption="cap")
    add_block_to_page(studio, block, width=200.0, height=200.0)
    # block landed on the document and got a square layout box
    assert studio.document.blocks[-1].id == block.id
    lay = studio.layouts[block.id]
    assert lay.width == 200.0 and lay.height == 200.0
    # and it survives a full JSON round-trip of the document
    restored = ReportDocument.from_dict(studio.to_document().to_dict())
    rb = restored.blocks[-1]
    assert rb.kind == "qr" and rb.payload["url"] == URL and rb.payload["video_id"] == "v1"


# ---------------------------------------------------------------- layout element
def test_layout_engine_produces_qr_element():
    if not qr_available():
        pytest.skip("qrcode library not installed")
    studio = ReportStudio.from_document(ReportDocument(id="d2", title="T", cover=Cover(title="T")))
    add_block_to_page(studio, qr_block(URL, caption="scan me"), width=200.0, height=200.0)
    doc = materialize_qr(studio.to_document())              # cache the PNG, like charts
    rd = LayoutEngine().build(doc)
    qr_els = [e for p in rd.pages for e in p.elements if e.kind == "qr"]
    assert len(qr_els) == 1
    el = qr_els[0]
    assert el.content["image_bytes"] and el.content["image_bytes"][:8] == PNG_MAGIC
    assert el.content["url"] == URL and el.content["caption"] == "scan me"
    assert el.content["fit"] == "contain"                  # QR must not be distorted


def test_qr_materialize_matches_direct_generation():
    if not qr_available():
        pytest.skip("qrcode library not installed")
    doc = ReportDocument(id="d3", title="T", cover=Cover(title="T"))
    add_block(doc, qr_block(URL))
    materialize_qr(doc)
    cached = base64.b64decode(doc.blocks[0].payload["image_b64"])
    assert cached == qr_png(URL)                            # deterministic + same bytes


# ---------------------------------------------------------------- player-video URL source
def test_qr_url_sourced_from_players_external_video(tmp_path):
    """The picker's data path: a player's external (link) video supplies the QR url,
    and its ids are recorded on the block for re-editing."""
    from fap.db.engine import Database
    from fap.identity.models import User
    from fap.identity.roles import Role
    from fap.scouting.models import Player, PlayerVideo
    from fap.scouting.repository import PlayerRepository, VideoRepository
    from fap.scouting.service import ScoutingService
    from fap.workspaces.audit import AuditService
    from fap.workspaces.repositories import AuditRepository

    class _AllowAll:
        def require(self, user, cap, scope=None): pass
        def can(self, user, cap, scope=None): return True

    db = Database(tmp_path / "s.sqlite3")
    try:
        PlayerRepository(db).save(Player(id="p1", name="Kwame Mensah", club="Right To Dream"))
        VideoRepository(db).add(PlayerVideo(id="v1", player_id="p1", kind="external",
                                            provider="youtube", url=URL, title="Match clip"))
        # an uploaded (non-external) video must NOT be offered as a QR link source
        VideoRepository(db).add(PlayerVideo(id="v2", player_id="p1", kind="upload",
                                            file_id="f1", filename="clip.mp4"))
        svc = ScoutingService(db, permissions=_AllowAll(),
                              audit=AuditService(AuditRepository(db)))

        externals = [v for v in svc.list_videos("p1") if v.kind == "external"]
        assert [v.id for v in externals] == ["v1"]         # only the external one
        vid = externals[0]

        block = qr_block(vid.url, player_id=vid.player_id, video_id=vid.id)
        assert block.payload["url"] == URL
        assert block.payload["player_id"] == "p1" and block.payload["video_id"] == "v1"
    finally:
        db.close()


# ---------------------------------------------------------------- manual-URL fallback
def test_qr_manual_url_fallback_has_no_player_reference():
    block = qr_block("https://vimeo.com/12345", player_id="", video_id="", caption="")
    assert block.payload["url"] == "https://vimeo.com/12345"
    assert block.payload["player_id"] == "" and block.payload["video_id"] == ""


def test_qr_renders_into_html_and_markdown_exports():
    if not qr_available():
        pytest.skip("qrcode library not installed")
    from fap.reports.renderer import ReportRenderer
    doc = ReportDocument(id="d4", title="Report", cover=Cover(title="Report"))
    add_block(doc, qr_block(URL, caption="Scan for video"))
    materialize_qr(doc)
    html = ReportRenderer().render(doc, "html").content
    assert b"data:image/png;base64," in html               # the QR PNG is embedded
    md = ReportRenderer().render(doc, "markdown").text
    assert "QR" in md and URL in md                         # url surfaced in markdown
