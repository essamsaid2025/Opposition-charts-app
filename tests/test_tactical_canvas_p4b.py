"""Tactical Board — Phase 4B: live-canvas Python side (trust boundary + intent consumer).

The JS canvas now emits marquee/keyboard/group-drag intents; these tests lock the
Python that receives them: parse_result passes the UI-only undo/redo intents and the
multi-select list, and _commit_canvas applies batch commands, undo/redo, and the shared
selection (TB_SEL primary + TB_MULTI set) — all through apply_command/History. The JS
pointer/keyboard behaviour itself is browser-verified separately (see the report).
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")
import streamlit as st

from fap.tactical import History, apply_command, new_board
from fap.ui.builtin import tactical_board as TB
from fap.ui.builtin.tactical_canvas import parse_result


# ---- trust boundary: undo/redo UI-only intents ----
def test_parse_result_undo_redo_intents():
    assert parse_result({"ts": 1, "commands": [], "select": "__keep__", "undo": True})["undo"] is True
    assert parse_result({"ts": 2, "commands": [], "select": "__keep__", "redo": True})["redo"] is True
    # a bare keep with no action is still nothing
    assert parse_result({"ts": 3, "commands": [], "select": "__keep__"}) is None


def _seed(board=None):
    st.session_state.clear()
    b = board or new_board("P4B")
    st.session_state[TB.TB_BOARD] = b
    st.session_state[TB.TB_HIST] = History()
    st.session_state[TB.TB_FRAME] = 0
    st.session_state[TB.TB_SEL] = None
    st.session_state[TB.TB_CANVAS_TS] = None
    return b


# ---- consumer: shared selection (list + string + null) ----
def test_commit_canvas_multi_select_list():
    b = _seed()
    ids = [apply_command(b, {"op": "add_object", "type": "player", "x": i, "y": i})["id"]
           for i in range(3)]
    TB._commit_canvas({"ts": 10, "commands": [], "select": ids}, can_edit=True)
    assert st.session_state[TB.TB_MULTI] == ids
    assert st.session_state[TB.TB_SEL] == ids[-1]          # primary = last
    TB._commit_canvas({"ts": 11, "commands": [], "select": ids[0]}, can_edit=True)
    assert st.session_state[TB.TB_MULTI] == [ids[0]] and st.session_state[TB.TB_SEL] == ids[0]
    TB._commit_canvas({"ts": 12, "commands": [], "select": None}, can_edit=True)
    assert st.session_state[TB.TB_MULTI] == [] and st.session_state[TB.TB_SEL] is None


# ---- consumer: batch command from the canvas (marquee-delete) is ONE undo step ----
def test_commit_canvas_batch_delete_and_undo():
    b = _seed()
    ids = [apply_command(b, {"op": "add_object", "type": "player", "x": i, "y": i})["id"]
           for i in range(4)]
    TB._commit_canvas({"ts": 20, "commands": [{"op": "delete_objects", "ids": ids}],
                       "select": None}, can_edit=True)
    assert len(st.session_state[TB.TB_BOARD].frame(0).objects) == 0
    # Ctrl+Z intent from the canvas restores all four in one step
    TB._commit_canvas({"ts": 21, "commands": [], "select": "__keep__", "undo": True}, can_edit=True)
    assert len(st.session_state[TB.TB_BOARD].frame(0).objects) == 4


def test_commit_canvas_group_move_and_redo():
    b = _seed()
    a = apply_command(b, {"op": "add_object", "type": "player", "x": 10, "y": 10})["id"]
    c = apply_command(b, {"op": "add_object", "type": "player", "x": 20, "y": 20})["id"]
    TB._commit_canvas({"ts": 30, "commands": [{"op": "move_objects", "ids": [a, c], "dx": 5, "dy": 5}],
                       "select": [a, c]}, can_edit=True)
    bd = st.session_state[TB.TB_BOARD]
    assert (bd.frame(0).object(a).x, bd.frame(0).object(a).y) == (15, 15)
    TB._commit_canvas({"ts": 31, "commands": [], "select": "__keep__", "undo": True}, can_edit=True)
    assert st.session_state[TB.TB_BOARD].frame(0).object(a).x == 10
    TB._commit_canvas({"ts": 32, "commands": [], "select": "__keep__", "redo": True}, can_edit=True)
    assert st.session_state[TB.TB_BOARD].frame(0).object(a).x == 15


def test_commit_canvas_freehand_add_selects_it():
    b = _seed()
    TB._commit_canvas({"ts": 40, "commands": [
        {"op": "add_object", "type": "freehand", "x": 10, "y": 10,
         "props": {"points": [[10, 10], [20, 30], [40, 25]]}}], "select": "__keep__"}, can_edit=True)
    objs = st.session_state[TB.TB_BOARD].frame(0).objects
    assert len(objs) == 1 and objs[0].type == "freehand"
    assert st.session_state[TB.TB_MULTI] == [objs[0].id]   # freshly added stays selected


# ---- consumer respects permission ----
def test_commit_canvas_view_only_ignores_commands():
    b = _seed()
    a = apply_command(b, {"op": "add_object", "type": "player", "x": 1, "y": 1})["id"]
    TB._commit_canvas({"ts": 50, "commands": [{"op": "delete_objects", "ids": [a]}],
                       "select": "__keep__"}, can_edit=False)
    assert len(st.session_state[TB.TB_BOARD].frame(0).objects) == 1   # not deleted


# ---- objects panel sanitizes a stale canvas selection (no crash after delete) ----
def test_objects_panel_sanitizes_stale_multiselect():
    b = _seed()
    ids = [apply_command(b, {"op": "add_object", "type": "player", "x": i, "y": i})["id"]
           for i in range(2)]
    st.session_state[TB.TB_MULTI] = ids + ["ghost-id"]     # a stale id the canvas left behind
    page = TB.TacticalBoardPage()
    page._objects_panel(b, can_edit=True)                  # must not raise
    assert "ghost-id" not in st.session_state[TB.TB_MULTI]
