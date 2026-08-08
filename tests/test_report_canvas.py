"""Report Studio free-form canvas — Phase 1 (MOVE only).

The JS drag surface itself (src/fap/ui/builtin/frontend/report_canvas/index.html) is
browser interaction and is NOT meaningfully unit-testable here — we do NOT fake coverage
for it. These tests cover the pure Python that guards the model:

(a) a "free" page is NEVER touched by any ``_reflow()``-calling action (the single most
    important regression-safety guarantee — free blocks keep their manual x/y);
(b) a "flow" page's stacking is completely unchanged (deterministic, and unperturbed by the
    presence of free pages);
(c) the ``update_layout`` trust boundary validates/normalizes and rejects malformed input,
    the same defensive way tactical_canvas.py's parse_result does;
(d) a legacy saved page with no "kind" key loads as "flow" (backward compatible);
plus the render path (LayoutEngine) already positions free blocks with zero changes.

Follows the headless style of test_report_editor.py / test_reports.py.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.reports import text_block, image_block
from fap.reports.editor_ops import create_page
from fap.reports.layout import LayoutEngine
from fap.reports.models import Cover, ReportDocument
from fap.reports.studio import Page, ReportStudio, new_page
from fap.ui.builtin.report_canvas import parse_result
from fap.ui.studio import editor as ED


def _studio(*blocks):
    doc = ReportDocument(id="d1", title="T", cover=Cover(title="T"))
    studio = ReportStudio.from_document(doc)
    for b in blocks:
        studio.document.blocks.append(b)
    ED._reflow(studio)
    return studio


# ---------------------------------------------------------------- (d) backward compat
def test_page_without_kind_loads_as_flow():
    assert Page.from_dict({"id": "p1", "title": "Legacy"}).kind == "flow"


def test_page_kind_round_trips():
    assert Page.from_dict(new_page(kind="free").to_dict()).kind == "free"
    assert Page.from_dict(new_page().to_dict()).kind == "flow"


def test_default_page_is_flow():
    studio = _studio(text_block("hi", title="A"))
    assert studio.pages[0].kind == "flow"


# ---------------------------------------------------------------- (b) flow unchanged
def test_flow_reflow_is_deterministic_vertical_stack():
    a, b, c = text_block("one", title="A"), image_block("", title="Img"), text_block("two", title="B")
    studio = _studio(a, b, c)
    la, lb, lc = studio.layouts[a.id], studio.layouts[b.id], studio.layouts[c.id]
    # left margin + full content width for every flow block, stacked top-to-bottom
    pw, _ = studio.pages[0].dimensions()
    assert la.x == lb.x == lc.x == ED._MARGIN
    assert la.width == lb.width == lc.width == pw - 2 * ED._MARGIN
    assert la.y < lb.y < lc.y                       # strictly increasing (stacked)
    assert la.y == ED._MARGIN                        # first block at the top margin
    # image height default is 260; the text below it starts after image + gap
    assert lc.y == lb.y + lb.height + ED._GAP


def test_flow_blocks_unperturbed_by_a_free_page():
    """Adding a free page + free blocks must not move ANY flow block by a single pixel."""
    a, b = text_block("one", title="A"), text_block("two", title="B")
    studio = _studio(a, b)
    before = {bid: (l.page_id, l.x, l.y, l.width, l.height) for bid, l in studio.layouts.items()}

    create_page(studio, title="Free", kind="free")            # active page is now the free one
    ED._add_block(studio, text_block("free", title="F"))       # lands on the free page
    ED._add_block(studio, image_block("", title="FreeImg"))
    ED._reflow(studio)                                          # the action every edit triggers

    after = {bid: (studio.layouts[bid].page_id, studio.layouts[bid].x, studio.layouts[bid].y,
                   studio.layouts[bid].width, studio.layouts[bid].height)
             for bid in before}
    assert after == before                                     # flow blocks byte-identical


# ---------------------------------------------------------------- (a) free never reflowed
def test_free_block_keeps_manual_xy_through_every_reflow_action():
    studio = _studio(text_block("flow", title="Flow"))
    create_page(studio, title="Free", kind="free")
    free_id = studio.editor.active_page
    blk = text_block("free", title="F")
    ED._add_block(studio, blk)
    # user drags it somewhere specific
    studio.layouts[blk.id].x, studio.layouts[blk.id].y = 321.0, 654.0

    # exercise EVERY code path that unconditionally called _reflow before this phase
    ED._reflow(studio)
    ED._add(studio, text_block("more-flow"))                   # flow add
    ED._move(studio, studio.document.blocks[0].id, +1)         # reorder
    ED._duplicate(studio, studio.document.blocks[0].id)
    ED._set_text(studio, studio.document.blocks[0].id, "t", "changed\nlines\nhere")
    ED._delete(studio, studio.document.blocks[-1].id)

    lay = studio.layouts[blk.id]
    assert lay.page_id == free_id
    assert (lay.x, lay.y) == (321.0, 654.0)                     # never reflowed


def test_add_block_on_free_page_places_without_stacking():
    studio = _studio()
    create_page(studio, title="Free", kind="free")
    free = studio.pages[-1]
    b1 = text_block("a", title="A"); b2 = text_block("b", title="B")
    ED._add_block(studio, b1)
    ED._add_block(studio, b2)
    l1, l2 = studio.layouts[b1.id], studio.layouts[b2.id]
    assert l1.page_id == free.id and l2.page_id == free.id
    # cascaded, not stacked to a shared left margin/full width
    assert (l1.x, l1.y) != (l2.x, l2.y)
    assert l1.width != (free.dimensions()[0] - 2 * ED._MARGIN)  # NOT the flow full-width


def test_persistence_round_trip_preserves_free_page_and_positions():
    studio = _studio(text_block("flow", title="Flow"))
    create_page(studio, title="Canvas", kind="free")
    blk = text_block("free", title="F")
    ED._add_block(studio, blk)
    studio.layouts[blk.id].x, studio.layouts[blk.id].y = 200.0, 300.0

    doc = studio.to_document()                                  # folds overlay into meta
    restored = ReportStudio.from_document(ReportDocument.from_dict(doc.to_dict()))
    free = next(p for p in restored.pages if p.kind == "free")
    assert restored.layouts[blk.id].page_id == free.id
    assert (restored.layouts[blk.id].x, restored.layouts[blk.id].y) == (200.0, 300.0)


# ---------------------------------------------------------------- render path (zero changes)
def test_layout_engine_positions_free_blocks_at_their_xy():
    studio = _studio()
    create_page(studio, title="Free", kind="free")
    free = studio.pages[-1]
    blk = text_block("hello", title="F")
    ED._add_block(studio, blk)
    studio.layouts[blk.id].x, studio.layouts[blk.id].y = 120.0, 240.0
    lay = studio.layouts[blk.id]

    rd = LayoutEngine().build(studio.to_document())
    pw, ph = free.dimensions()
    # find the rendered page for the free page and the element for our block
    el = next(e for p in rd.pages for e in p.elements
              if e.content.get("text") == "hello")
    assert abs(el.fx - lay.x / pw) < 1e-6 and abs(el.fy - lay.y / ph) < 1e-6


# ---------------------------------------------------------------- (c) trust boundary
def test_parse_result_accepts_valid_update_layout():
    r = parse_result({"ts": 7, "commands": [{"op": "update_layout", "id": "b1", "x": 12, "y": 34}]})
    assert r == {"ts": 7.0, "commands": [{"op": "update_layout", "id": "b1", "x": 12.0, "y": 34.0}]}


def test_parse_result_rejects_malformed_and_foreign_ops():
    # no ts
    assert parse_result({"commands": [{"op": "update_layout", "id": "a", "x": 1, "y": 2}]}) is None
    # foreign op (resize/z-order are out of scope in phase 1)
    assert parse_result({"ts": 1, "commands": [{"op": "resize", "id": "a", "x": 1, "y": 2}]}) is None
    # missing id
    assert parse_result({"ts": 1, "commands": [{"op": "update_layout", "x": 1, "y": 2}]}) is None
    # missing coordinate
    assert parse_result({"ts": 1, "commands": [{"op": "update_layout", "id": "a", "x": 1}]}) is None
    # bool is not a coordinate (bool is an int subclass — must be rejected)
    assert parse_result({"ts": 1, "commands": [{"op": "update_layout", "id": "a",
                                               "x": True, "y": 2}]}) is None
    # nothing actionable / junk
    assert parse_result({"ts": 1, "commands": []}) is None
    assert parse_result(None) is None
    assert parse_result("nope") is None


def test_apply_layout_cmds_snaps_and_clamps():
    studio = _studio()
    create_page(studio, title="Free", kind="free")
    blk = text_block("x", title="X")
    ED._add_block(studio, blk)
    studio.editor.snap_to_grid = True
    studio.editor.grid_size = 8
    # snap to grid of 8
    ED._apply_layout_cmds(studio, [{"op": "update_layout", "id": blk.id, "x": 101.0, "y": 205.0}])
    assert studio.layouts[blk.id].x == 104 and studio.layouts[blk.id].y == 208
    # clamp beyond the page keeps the block on-page
    pw, ph = studio.pages[-1].dimensions()
    ED._apply_layout_cmds(studio, [{"op": "update_layout", "id": blk.id, "x": 99999, "y": 99999}])
    assert studio.layouts[blk.id].x <= pw - studio.layouts[blk.id].width
    assert studio.layouts[blk.id].y <= ph - studio.layouts[blk.id].height


def test_apply_layout_cmds_ignores_locked_block():
    studio = _studio()
    create_page(studio, title="Free", kind="free")
    blk = text_block("x", title="X")
    ED._add_block(studio, blk)
    studio.layouts[blk.id].x, studio.layouts[blk.id].y = 50.0, 60.0
    studio.layouts[blk.id].locked = True
    ED._apply_layout_cmds(studio, [{"op": "update_layout", "id": blk.id, "x": 500, "y": 500}])
    assert (studio.layouts[blk.id].x, studio.layouts[blk.id].y) == (50.0, 60.0)   # unmoved
