"""Tactical Board — Phase 4 engine + trust-boundary tests.

Adds alignment/distribute as first-class engine commands (batch, one undo step) and
extends parse_result — the JS→Python trust boundary — to accept the Phase-3 BATCH
commands and MULTI-select the canvas marquee/keyboard layer will emit, while still
rejecting anything unsafe. Everything flows through apply_command/History; legacy
single-object intents are unchanged.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")

from fap.tactical import History, apply_command, new_board
from fap.ui.builtin.tactical_canvas import parse_result


def _b():
    return new_board("P4")


def _players(b, coords):
    return [apply_command(b, {"op": "add_object", "type": "player", "x": x, "y": y})["id"]
            for x, y in coords]


# ---- alignment ----
def test_align_left_right_center():
    for how, expect in (("left", 10), ("right", 50), ("center_h", 30)):
        b = _b()                                       # fresh board per case
        ids = _players(b, [(10, 10), (30, 20), (50, 40)])
        apply_command(b, {"op": "align_objects", "ids": ids, "align": how})
        assert {round(b.frame(0).object(i).x) for i in ids} == {expect}


def test_align_top_bottom_skips_locked():
    b = _b()
    ids = _players(b, [(10, 10), (20, 40), (30, 70)])
    apply_command(b, {"op": "update_object", "id": ids[2], "locked": True})
    apply_command(b, {"op": "align_objects", "ids": ids, "align": "top"})
    assert b.frame(0).object(ids[0]).y == 10 and b.frame(0).object(ids[1]).y == 10
    assert b.frame(0).object(ids[2]).y == 70          # locked -> unchanged


def test_distribute_horizontal_even_spacing():
    b = _b()
    ids = _players(b, [(10, 50), (12, 50), (90, 50), (40, 50)])   # unevenly placed
    apply_command(b, {"op": "distribute_objects", "ids": ids, "axis": "horizontal"})
    xs = sorted(b.frame(0).object(i).x for i in ids)
    gaps = [round(xs[i + 1] - xs[i], 3) for i in range(len(xs) - 1)]
    assert len(set(gaps)) == 1 and xs[0] == 10 and xs[-1] == 90   # equal gaps, extremes fixed


def test_align_is_single_undo_step():
    b = _b()
    ids = _players(b, [(10, 10), (30, 30), (50, 50)])
    h = History(); h.record(b)
    apply_command(b, {"op": "align_objects", "ids": ids, "align": "left"})
    assert {b.frame(0).object(i).x for i in ids} == {10}
    b = h.undo(b)
    assert sorted(b.frame(0).object(i).x for i in ids) == [10, 30, 50]   # ONE undo restores all


# ---- trust boundary: batch + multi-select accepted, junk rejected ----
def test_parse_result_accepts_batch_ops():
    val = {"ts": 5, "commands": [
        {"op": "delete_objects", "ids": ["a", "b"]},
        {"op": "move_objects", "ids": ["a"], "dx": 3, "dy": -2},
        {"op": "align_objects", "ids": ["a", "b"], "align": "center_h"},
        {"op": "distribute_objects", "ids": ["a", "b", "c"], "axis": "vertical"},
        {"op": "reorder_object", "id": "a", "dir": "front"},
        {"op": "set_hidden", "ids": ["a"], "hidden": True},
        {"op": "group_objects", "ids": ["a", "b"]},
    ]}
    out = parse_result(val)
    ops = [c["op"] for c in out["commands"]]
    assert ops == ["delete_objects", "move_objects", "align_objects", "distribute_objects",
                   "reorder_object", "set_hidden", "group_objects"]
    mv = out["commands"][1]
    assert mv["ids"] == ["a"] and mv["dx"] == 3.0 and mv["dy"] == -2.0
    assert out["commands"][0]["ids"] == ["a", "b"]
    assert out["commands"][4]["ids"] == ["a"]          # lone id promoted to ids


def test_parse_result_multi_select_list():
    out = parse_result({"ts": 1, "select": ["p1", "p2", 7, ""], "commands": []})
    assert out["select"] == ["p1", "p2"]               # non-str / empty dropped


def test_parse_result_rejects_and_sanitizes_junk():
    out = parse_result({"ts": 2, "commands": [
        {"op": "delete_objects"},                      # no ids -> dropped
        {"op": "delete_objects", "ids": []},           # empty ids -> dropped
        {"op": "set_pitch", "kind": "half"},           # frame/pitch op -> not allowed from canvas
        {"op": "align_objects", "ids": ["a", "b"], "align": "diagonal"},   # bad align -> defaulted
        {"op": "reorder_object", "id": "a", "dir": "sideways"},            # bad dir -> defaulted
        "notadict",
    ]})
    ops = [c["op"] for c in out["commands"]]
    assert ops == ["align_objects", "reorder_object"]
    assert out["commands"][0]["align"] == "left" and out["commands"][1]["dir"] == "forward"


def test_parse_result_single_ops_unchanged():
    out = parse_result({"ts": 3, "commands": [
        {"op": "update_object", "id": "x", "x": 10, "y": 20, "rotation": 90},
        {"op": "add_object", "type": "player", "x": 5, "y": 5},
    ]})
    assert out["commands"][0]["rotation"] == 90.0 and out["commands"][1]["type"] == "player"


# ---- Objects panel renders alignment controls when 2+ selected ----
def test_objects_panel_alignment_bare():
    import streamlit as st
    from fap.ui.builtin import tactical_board as TB
    st.session_state.clear()
    b = _b()
    ids = _players(b, [(10, 10), (30, 30), (50, 50)])
    st.session_state[TB.TB_BOARD] = b
    st.session_state[TB.TB_HIST] = History()
    st.session_state[TB.TB_FRAME] = 0
    st.session_state[TB.TB_SEL] = None
    st.session_state[TB.TB_MULTI] = ids                # 3 selected -> align + distribute rows
    TB.TacticalBoardPage()._objects_panel(b, can_edit=True)   # must not raise
