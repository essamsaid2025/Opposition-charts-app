"""Persistent Report Builder / visual editor (Phase 5.3).

Blocks are pure data, layout ops are pure functions, and every edit is written
straight to the platform database - so a report survives restart and never
depends on session_state. Charts stay references and are regenerated from the
saved dataset at export.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pytest

from fap.core.exceptions import AuthError
from fap.db.engine import Database
from fap.identity.models import User
from fap.identity.roles import Role
from fap.reports import (
    BuildContext, DocumentBuilder, ReportDocument, ReportsManager, add_block,
    chart_block, delete_block, duplicate_block, image_block, move_block,
    reorder_blocks, set_hidden, text_block, visible_blocks,
)


def _df(n=120, seed=4):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "event_type": rng.choice(["pass", "carry", "shot", "duel"], n),
        "x": rng.uniform(0, 100, n), "y": rng.uniform(0, 100, n),
        "end_x": rng.uniform(0, 100, n), "end_y": rng.uniform(0, 100, n),
        "player": rng.choice(["A", "B"], n), "team": "Rival",
        "outcome": rng.choice(["successful", "unsuccessful"], n),
        "shot_result": rng.choice(["goal", ""], n),
    })


def _user(role=Role.PERFORMANCE_ANALYST, email="a@club.com"):
    return User(email=email, name=email.split("@")[0], role=role, provider_id="dev")


@pytest.fixture()
def editor(tmp_path) -> ReportsManager:
    """ReportsManager wired like the platform: persistent frames + images."""
    from fap.storage import LocalImageStorage, ParquetDatasetStorage
    from fap.theme import DEFAULT_BRANDING
    store = ParquetDatasetStorage(tmp_path / "ds")
    store.save("ds1", _df())
    return ReportsManager(Database(tmp_path / "e.sqlite3"), branding=DEFAULT_BRANDING,
                          frame_provider=store.load,
                          images=LocalImageStorage(tmp_path / "img"))


def _report(mgr, user=None):
    return mgr.create(user or _user(), template="weekly_report", df=_df(), dataset_id="ds1")


# ---------------------------------------------------------------- block model
def test_block_document_json_roundtrip():
    doc = DocumentBuilder().build("weekly_report", BuildContext(df=_df()))
    add_block(doc, text_block("# Hi\n- a", title="T"))
    add_block(doc, chart_block("pass_map", {"opt": 1}, caption="c", title="C"))
    add_block(doc, image_block("img1", caption="cap", width_pct=50))
    doc.notes = "n"
    restored = ReportDocument.from_dict(doc.to_dict())
    assert [b.kind for b in restored.blocks] == ["text", "chart", "image"]
    assert restored.blocks[0].payload["text"].startswith("# Hi")
    assert restored.blocks[1].payload["viz_id"] == "pass_map"
    assert restored.blocks[2].payload["width_pct"] == 50
    assert restored.notes == "n"


def test_layout_operations_are_pure_and_ordered():
    doc = ReportDocument(id="d", title="t")
    a = add_block(doc, text_block("a", title="A"))
    b = add_block(doc, text_block("b", title="B"))
    c = add_block(doc, text_block("c", title="C"))
    assert [x.title for x in doc.blocks] == ["A", "B", "C"]
    move_block(doc, c.id, -1)
    assert [x.title for x in doc.blocks] == ["A", "C", "B"]
    dup = duplicate_block(doc, a.id)
    assert dup.id != a.id and [x.title for x in doc.blocks] == ["A", "A", "C", "B"]
    set_hidden(doc, b.id, True)
    assert len(visible_blocks(doc)) == 3
    reorder_blocks(doc, [b.id, c.id])                     # drag-reorder primitive
    assert doc.blocks[0].id == b.id and doc.blocks[1].id == c.id
    assert delete_block(doc, b.id) and len(doc.blocks) == 3
    assert delete_block(doc, "missing") is False


def test_move_block_clamps_at_edges():
    doc = ReportDocument(id="d", title="t")
    a = add_block(doc, text_block("a"))
    add_block(doc, text_block("b"))
    assert move_block(doc, a.id, -1) is False
    assert [x.payload["text"] for x in doc.blocks] == ["a", "b"]


# ---------------------------------------------------------------- persistence
def test_edits_persist_and_survive_restart(editor, tmp_path):
    u = _user()
    rec = _report(editor, u)
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("# Analysis", title="A")))
    editor.update_blocks(u, rec.id, lambda d: add_block(d, chart_block("pass_map", title="P")))
    editor.update_blocks(u, rec.id, lambda d: setattr(d, "notes", "coach notes"))

    from fap.theme import DEFAULT_BRANDING
    reborn = ReportsManager(Database(tmp_path / "e.sqlite3"), branding=DEFAULT_BRANDING)
    doc = reborn.document(rec.id)                          # application restart
    assert [b.title for b in doc.blocks] == ["A", "P"]
    assert doc.notes == "coach notes"
    assert doc.blocks[1].payload["viz_id"] == "pass_map"


def test_autosave_persists_every_change(editor):
    u = _user()
    rec = _report(editor, u)
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("one")))
    assert len(editor.document(rec.id).blocks) == 1        # durable with no Save
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("two")))
    assert len(editor.document(rec.id).blocks) == 2


def test_save_as_creates_independent_copy(editor):
    u = _user()
    rec = _report(editor, u)
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("original")))
    copy = editor.save_as(u, rec.id, "My Copy")
    assert copy.id != rec.id and copy.title == "My Copy"
    editor.update_blocks(u, copy.id, lambda d: add_block(d, text_block("extra")))
    assert len(editor.document(rec.id).blocks) == 1        # source untouched
    assert len(editor.document(copy.id).blocks) == 2


# ---------------------------------------------------------------- versions
def test_version_history_save_list_restore(editor):
    u = _user()
    rec = _report(editor, u)
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("v1", title="A")))
    v1 = editor.save_version(u, rec.id, note="baseline")
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("v2", title="B")))
    assert len(editor.document(rec.id).blocks) == 2

    editor.restore_version(u, rec.id, v1.version)
    assert [b.title for b in editor.document(rec.id).blocks] == ["A"]
    versions = editor.list_versions(rec.id)
    assert [v.version for v in versions] == [2, 1]         # restore snapshots first
    assert versions[-1].note == "baseline"


# ---------------------------------------------------------------- images
def test_image_stored_once_and_referenced(editor):
    u = _user()
    data = b"\x89PNG\r\n\x1a\n" + b"x" * 40
    img = editor.upload_image(u, data, "badge.png", "image/png")
    assert editor.image_bytes(img.id) == data
    assert editor.image_mime(img.id) == "image/png"
    assert [i.filename for i in editor.list_images()] == ["badge.png"]

    rec = _report(editor, u)
    editor.update_blocks(u, rec.id, lambda d: add_block(d, image_block(img.id, caption="Badge")))
    block = editor.document(rec.id).blocks[0]
    assert block.payload["image_id"] == img.id
    assert "image_b64" not in block.payload                # a reference, not the bytes


def test_unsupported_image_type_rejected(editor):
    with pytest.raises(ValueError):
        editor.upload_image(_user(), b"x", "bad.exe", "application/x-msdownload")


# ---------------------------------------------------------------- export
def test_export_renders_blocks_and_embeds_assets(editor):
    u = _user()
    rec = _report(editor, u)
    img = editor.upload_image(u, b"\x89PNG\r\n\x1a\n" + b"y" * 30, "l.png", "image/png")
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("# Summary\n- point", title="S")))
    editor.update_blocks(u, rec.id, lambda d: add_block(d, image_block(img.id, caption="Logo")))
    editor.update_blocks(u, rec.id, lambda d: setattr(d, "notes", "final notes"))

    out = editor.render(u, rec.id, "html")
    assert b"<h2>Summary</h2>" in out.content and b"<li>point</li>" in out.content
    assert b"data:image/png;base64," in out.content        # embedded from image storage
    assert b"final notes" in out.content
    # the stored document keeps only references
    stored = editor.get(rec.id).document["blocks"][1]["payload"]
    assert "image_b64" not in stored and stored["image_id"] == img.id


def test_export_is_deterministic(editor):
    u = _user()
    rec = _report(editor, u)
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("stable")))
    assert editor.render(u, rec.id, "html").content == editor.render(u, rec.id, "html").content


def test_hidden_blocks_are_not_exported(editor):
    u = _user()
    rec = _report(editor, u)
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("VISIBLETEXT", title="V")))
    editor.update_blocks(u, rec.id, lambda d: add_block(d, text_block("HIDDENTEXT", title="H")))
    editor.update_blocks(u, rec.id, lambda d: set_hidden(d, d.blocks[1].id, True))
    out = editor.render(u, rec.id, "html")
    assert b"VISIBLETEXT" in out.content and b"HIDDENTEXT" not in out.content


def test_markdown_export_includes_blocks(editor):
    u = _user()
    rec = _report(editor, u)
    editor.update_blocks(u, rec.id, lambda d: add_block(d, chart_block("pass_map", title="Chart")))
    text = editor.render(u, rec.id, "markdown").text
    assert "## Chart" in text and "pass_map" in text


def test_chart_blocks_regenerate_from_saved_dataset(editor):
    """The report stores a reference; export regenerates the image from the
    persisted dataset - reusing the platform renderer, never a stored copy."""
    u = _user()
    rec = _report(editor, u)
    editor.update_blocks(u, rec.id, lambda d: add_block(d, chart_block("pass_map", title="P")))
    out = editor.render(u, rec.id, "html")
    stored = editor.get(rec.id).document["blocks"][0]["payload"]
    assert "image_b64" not in stored                        # nothing duplicated on disk
    assert editor.dataset_frame("ds1") is not None          # the dataset is the source
    assert b"<h2>P</h2>" in out.content


# ---------------------------------------------------------------- permissions / state
def test_read_only_cannot_edit_blocks(editor):
    rec = _report(editor)
    with pytest.raises(AuthError):
        editor.update_blocks(_user(Role.READ_ONLY, "r@club.com"), rec.id,
                             lambda d: add_block(d, text_block("nope")))


def test_editor_page_keeps_no_report_content_in_session_state():
    src = pathlib.Path("src/fap/ui/builtin/report_editor.py").read_text(encoding="utf-8")
    assert "OPEN_REPORT" in src and "SELECTED_BLOCK" in src      # ids only
    assert "reports.document(" in src and "update_blocks" in src  # content from the DB
    for banned in ("st.session_state['blocks']", 'st.session_state["blocks"]',
                   'st.session_state["document"]'):
        assert banned not in src


def test_chart_picker_uses_the_visualization_registry():
    src = pathlib.Path("src/fap/ui/builtin/report_editor.py").read_text(encoding="utf-8")
    assert "visual_registry" in src and "infos()" in src         # no hardcoded chart list
