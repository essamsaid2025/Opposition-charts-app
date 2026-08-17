"""Tactical Board — Phase 3 (object palette + interaction) engine tests.

Everything is a first-class capability of the shared fap.tactical engine (no per-
consumer special-casing): semantic arrow VARIANTS (pass/run/movement/pressing/…),
freehand paths, and multi-object / group / z-order / visibility commands — each a
single undo step through apply_command. Legacy arrows (no variant) render byte-
identically. All additive via props; no model field, no migration.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")
import pytest

from fap.tactical import (
    ARROW_VARIANT_KEYS, Board, History, apply_command, board_svg, new_board, variant_spec,
)
from fap.tactical import geometry as geo
from fap.tactical.export_render import board_image
from fap.tactical.models import OBJECT_TYPES


def _b():
    return new_board("P3")


def _oid(b, res):
    return res["id"]


# ---- geometry (pure) ----
def test_variant_table_and_specs():
    assert set(ARROW_VARIANT_KEYS) == {"pass", "run", "movement", "pressing", "defensive",
                                       "dribble", "shot"}
    assert variant_spec("PASS")["color"] == "#2f6fdb"       # case-insensitive
    assert variant_spec("") is None and variant_spec("nope") is None   # legacy/unknown


def test_wave_points_endpoints_and_shape():
    straight = geo.wave_points(0, 0, 100, 0, "")
    assert straight == [(0, 0), (100, 0)]
    wavy = geo.wave_points(0, 0, 100, 0, "wavy")
    assert len(wavy) > 2 and wavy[0] == (0, 0) and wavy[-1] == (100, 0)   # ends exact
    assert any(abs(y) > 1 for _, y in wavy)                 # actually ripples off the line
    zig = geo.wave_points(0, 0, 100, 0, "zigzag")
    assert zig[0] == (0, 0) and zig[-1] == (100, 0) and len(zig) > 2


def test_arrowhead_and_freehand_points():
    head = geo.arrowhead_points(0, 0, 10, 0)
    assert head[0] == (10, 0) and len(head) == 3           # tip at the end
    assert geo.freehand_points({"points": [[1, 2], {"x": 3, "y": 4}, "junk", [None, 1]]}) == [(1, 2), (3, 4)]


# ---- legacy byte-compat: an arrow with no variant is UNCHANGED ----
def test_legacy_arrow_svg_unchanged():
    b = _b()
    apply_command(b, {"op": "add_object", "type": "arrow", "x": 10, "y": 10,
                      "props": {"x2": 40, "y2": 40}})
    svg = board_svg(b, 0)
    assert "marker-end=\"url(#arrowhead)\"" in svg and "<line" in svg   # classic path
    assert "polygon" not in svg.split("<line")[1][:200]     # no variant head polygon


# ---- variants render (SVG) + export (PNG) ----
@pytest.mark.parametrize("variant", list(ARROW_VARIANT_KEYS))
def test_each_variant_renders_and_exports(variant):
    b = _b()
    apply_command(b, {"op": "add_object", "type": "arrow", "x": 10, "y": 20,
                      "props": {"x2": 60, "y2": 55, "variant": variant, "label": variant}})
    svg = board_svg(b, 0)
    spec = variant_spec(variant)
    assert (spec["color"] in svg) and variant in svg        # variant colour + label present
    assert len(board_image(b, 0, fmt="png")) > 500          # exporter draws it too


# ---- freehand is a first-class object ----
def test_freehand_object_type_render_export():
    assert "freehand" in OBJECT_TYPES
    b = _b()
    apply_command(b, {"op": "add_object", "type": "freehand",
                      "props": {"points": [[10, 10], [20, 30], [40, 25], [55, 50]], "closed": False}})
    svg = board_svg(b, 0)
    assert "<path" in svg and "stroke-linecap=\"round\"" in svg
    assert len(board_image(b, 0, fmt="png")) > 500


# ---- multi-object commands (one undo step each) ----
def test_delete_and_duplicate_objects_batch():
    b = _b()
    ids = [apply_command(b, {"op": "add_object", "type": "player", "x": i * 5, "y": 10})["id"]
           for i in range(4)]
    dup = apply_command(b, {"op": "duplicate_objects", "ids": ids[:2]})
    assert len(dup["ids"]) == 2 and len(b.frame(0).objects) == 6
    apply_command(b, {"op": "delete_objects", "ids": ids})
    assert len(b.frame(0).objects) == 2                     # the two originals gone, dups remain


def test_move_objects_respects_lock_and_clamps():
    b = _b()
    a = apply_command(b, {"op": "add_object", "type": "player", "x": 50, "y": 50})["id"]
    c = apply_command(b, {"op": "add_object", "type": "player", "x": 98, "y": 50})["id"]
    apply_command(b, {"op": "update_object", "id": c, "locked": True})
    apply_command(b, {"op": "move_objects", "ids": [a, c], "dx": 10, "dy": 5})
    oa = b.frame(0).object(a); oc = b.frame(0).object(c)
    assert (oa.x, oa.y) == (60, 55)                         # moved
    assert (oc.x, oc.y) == (98, 50)                         # locked -> unchanged (clamp would cap anyway)


# ---- group / ungroup ----
def test_group_and_ungroup():
    b = _b()
    a = apply_command(b, {"op": "add_object", "type": "player", "x": 10, "y": 10})["id"]
    c = apply_command(b, {"op": "add_object", "type": "player", "x": 20, "y": 20})["id"]
    g = apply_command(b, {"op": "group_objects", "ids": [a, c]})["group"]
    assert g and b.frame(0).object(a).props["group"] == g == b.frame(0).object(c).props["group"]
    # duplicating a grouped selection makes a NEW group
    dup = apply_command(b, {"op": "duplicate_objects", "ids": [a, c]})
    assert dup["group"] and dup["group"] != g
    apply_command(b, {"op": "ungroup_objects", "group": g})
    assert "group" not in b.frame(0).object(a).props


# ---- z-order ----
def test_reorder_zorder():
    b = _b()
    ids = [apply_command(b, {"op": "add_object", "type": "player", "x": i, "y": i})["id"]
           for i in range(3)]
    apply_command(b, {"op": "reorder_object", "id": ids[0], "dir": "front"})
    zmax = max(o.z for o in b.frame(0).objects)
    assert b.frame(0).object(ids[0]).z == zmax
    apply_command(b, {"op": "reorder_object", "id": ids[0], "dir": "back"})
    assert b.frame(0).object(ids[0]).z == 0


# ---- visibility / lock ----
def test_hidden_objects_not_rendered_or_exported():
    b = _b()
    a = apply_command(b, {"op": "add_object", "type": "player", "x": 30, "y": 30,
                          "props": {"number": 7}})["id"]
    svg_before = board_svg(b, 0)
    assert f'data-oid="{a}"' in svg_before
    apply_command(b, {"op": "set_hidden", "ids": [a], "hidden": True})
    assert f'data-oid="{a}"' not in board_svg(b, 0)         # hidden -> not drawn
    assert len(board_image(b, 0, fmt="png")) > 200          # still exports (pitch), no raise
    apply_command(b, {"op": "set_hidden", "ids": [a], "hidden": False})
    assert f'data-oid="{a}"' in board_svg(b, 0)             # shown again


def test_set_locked_batch():
    b = _b()
    ids = [apply_command(b, {"op": "add_object", "type": "player", "x": i, "y": i})["id"]
           for i in range(2)]
    apply_command(b, {"op": "set_locked", "ids": ids, "locked": True})
    assert all(o.locked for o in b.frame(0).objects)


# ---- undo/redo is one step for a batch op ----
def test_batch_op_is_single_undo_step():
    b = _b()
    ids = [apply_command(b, {"op": "add_object", "type": "player", "x": i, "y": i})["id"]
           for i in range(3)]
    h = History()
    h.record(b)                                             # snapshot before the batch delete
    apply_command(b, {"op": "delete_objects", "ids": ids})
    assert len(b.frame(0).objects) == 0
    b = h.undo(b)                                           # ONE undo restores all three
    assert len(b.frame(0).objects) == 3


# ---- persistence round-trip of new props ----
def test_new_props_roundtrip_json():
    b = _b()
    apply_command(b, {"op": "add_object", "type": "arrow",
                      "props": {"variant": "run", "label": "Overlap"}})
    apply_command(b, {"op": "add_object", "type": "freehand", "props": {"points": [[1, 2], [3, 4]]}})
    b2 = Board.from_dict(b.to_dict())
    kinds = {o.type for o in b2.frame(0).objects}
    assert "freehand" in kinds
    arr = next(o for o in b2.frame(0).objects if o.type == "arrow")
    assert arr.props["variant"] == "run" and arr.props["label"] == "Overlap"


# ---- UI: the Objects/Layers panel renders in bare mode ----
def test_objects_panel_renders_bare():
    import streamlit as st
    from fap.ui.builtin import tactical_board as TB
    st.session_state.clear()
    b = _b()
    for i in range(3):
        apply_command(b, {"op": "add_object", "type": "player", "x": i * 10, "y": 10,
                          "props": {"number": i}})
    apply_command(b, {"op": "add_object", "type": "arrow", "props": {"variant": "run"}})
    st.session_state[TB.TB_BOARD] = b
    st.session_state[TB.TB_HIST] = History()
    st.session_state[TB.TB_FRAME] = 0
    st.session_state[TB.TB_SEL] = None
    page = TB.TacticalBoardPage()
    page._objects_panel(b, can_edit=True)          # must not raise
    page._objects_panel(b, can_edit=False)         # view-only path
