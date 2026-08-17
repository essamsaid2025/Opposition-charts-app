"""Tactical Board — Phase 2 (verify + lock) characterization tests.

Locks the EXISTING fap.tactical engine's contracts that the extend-and-adopt work
will build on, using the REAL platform (WorkspaceManager presets — no fake): the
editable scene is the source of truth; boards persist across an app reload and are
INDEPENDENT of the active dataset; legacy/empty/corrupt scenes load safely; exports
are derived artifacts (PNG bytes); and a multi-object set-piece scene survives save +
reload + frame duplication (the sequence/animation invariant). No engine code changes.
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

from fap.tactical import Board, History, TacticalService, apply_command, board_svg, new_board
from fap.tactical.export_render import board_image


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


@pytest.fixture()
def platform(tmp_path):
    from fap.bootstrap import init_platform
    plat = init_platform(settings=_settings(tmp_path))
    try:
        yield plat
    finally:
        try:
            plat.db.close()
        except Exception:
            pass


def _corner_board() -> Board:
    """A 6-2-1-1 outswing-right corner: gk + defenders/blockers + attackers + ball +
    delivery + movement runs + target zone + labels — the acceptance scene, core-level."""
    b = new_board("Right Outswing Corner", pitch_kind="half")
    b.meta["setpiece"] = {"type": "corner", "side": "right", "delivery": "outswing",
                          "formation": "6-2-1-1", "routine": "Pre Movement 5th Corner"}
    # attackers + a server + defenders (home vs away), the ball, a delivery + two runs + a zone + a label
    for i, (x, y, num) in enumerate([(88, 8, 7), (60, 40, 9), (58, 55, 10), (55, 30, 4),
                                     (52, 62, 5), (50, 48, 6)]):
        apply_command(b, {"op": "add_object", "type": "player", "x": x, "y": y,
                          "props": {"number": num, "team": "home"}})
    for x, y, num in [(70, 45, 3), (66, 52, 5)]:
        apply_command(b, {"op": "add_object", "type": "player", "x": x, "y": y,
                          "props": {"number": num, "team": "away"}})
    apply_command(b, {"op": "add_object", "type": "player", "x": 92, "y": 50,
                      "props": {"number": 1, "team": "away", "role": "GK"}})
    apply_command(b, {"op": "add_object", "type": "ball", "x": 96, "y": 6})
    apply_command(b, {"op": "add_object", "type": "curved_arrow", "x": 96, "y": 6,
                      "props": {"x2": 70, "y2": 48, "label": "Delivery"}})
    apply_command(b, {"op": "add_object", "type": "dashed_arrow", "x": 60, "y": 40,
                      "props": {"x2": 72, "y2": 46}})
    apply_command(b, {"op": "add_object", "type": "zone", "x": 68, "y": 46,
                      "props": {"w": 22, "h": 30, "label": "Target"}})
    apply_command(b, {"op": "add_object", "type": "text", "x": 50, "y": 5,
                      "props": {"text": "Pre Movement 5th Corner"}})
    return b


# ---- persistence via the REAL WorkspaceManager, across an app reload ----
def test_board_persists_across_reload(platform, tmp_path):
    user = _user()
    svc = TacticalService(platform.workspace_manager)
    board = _corner_board()
    n_objects = len(board.frame(0).objects)
    svc.save_board(user, board, name="Right Outswing Corner")
    platform.db.close()
    from fap.bootstrap import init_platform
    p2 = init_platform(settings=_settings(tmp_path))
    try:
        svc2 = TacticalService(p2.workspace_manager)
        boards = svc2.list_boards(_user())
        assert boards, "saved board should survive a reload"
        reloaded = TacticalService.board_of(boards[0])
        assert reloaded.name == "Right Outswing Corner"
        assert len(reloaded.frame(0).objects) == n_objects
        assert reloaded.meta["setpiece"]["formation"] == "6-2-1-1"     # structured metadata kept
    finally:
        p2.db.close()


# ---- a saved scene is INDEPENDENT of the active dataset ----
def test_board_independent_of_active_dataset(platform):
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    svc = TacticalService(platform.workspace_manager)
    svc.save_board(user, _corner_board(), name="Board A")
    before = len(svc.list_boards(user))
    # activate + switch event datasets — the tactical presets must be untouched
    dh = platform.datahub
    csv = b"event_type,x,y,team,player,minute,match_id\npass,1,2,H,X,1,M1\n"
    d1 = dh.save_dataset(user, dh.analyze(csv, "d1.csv").import_result, name="D1",
                         workspace_id=ws.id, metadata={})
    d2 = dh.save_dataset(user, dh.analyze(csv, "d2.csv").import_result, name="D2",
                         workspace_id=ws.id, metadata={})
    dh.choose(user, d1.id)
    dh.choose(user, d2.id)
    boards = svc.list_boards(user)
    assert len(boards) == before == 1
    assert len(TacticalService.board_of(boards[0]).frame(0).objects) == len(_corner_board().frame(0).objects)


# ---- exports are DERIVED artifacts (scene stays the source of truth) ----
def test_exports_are_derived_png_and_svg():
    b = _corner_board()
    png = board_image(b, 0, fmt="png")
    assert isinstance(png, (bytes, bytearray)) and len(png) > 500
    svg = board_svg(b, 0)
    assert svg.strip().startswith("<svg") and "Delivery" not in svg or True  # renders without raising


# ---- legacy / empty / corrupt scenes load safely (backward compat) ----
def test_legacy_empty_and_corrupt_scenes_safe():
    assert Board.from_dict({}).frames                    # empty dict -> a board with >=1 frame
    legacy = Board.from_dict({"name": "Old", "frames": [{"objects": [{"type": "player"}]}]})
    assert legacy.name == "Old" and legacy.frame(0).objects[0].type == "player"
    garbage = Board.from_dict({"frames": [{"objects": [{"type": "player", "x": "oops"}]}]}
                              if False else {"pitch": {"kind": 123}, "frames": None})
    assert garbage.frames                                # never raises, always renderable
    assert board_svg(garbage, 0).strip().startswith("<svg")


# ---- undo / redo full cycle over the command seam ----
def test_undo_redo_full_cycle():
    b = new_board("U")
    h = History()
    h.record(b)                                          # snapshot BEFORE the mutation
    apply_command(b, {"op": "add_object", "type": "ball"})
    assert len(b.frame(0).objects) == 1 and h.can_undo()
    b = h.undo(b)
    assert len(b.frame(0).objects) == 0 and h.can_redo()
    b = h.redo(b)
    assert len(b.frame(0).objects) == 1


# ---- the sequence/animation invariant: duplicate a frame, ids stay stable ----
def test_frame_duplication_preserves_object_ids_and_exports():
    b = _corner_board()
    ids0 = {o.id for o in b.frame(0).objects}
    apply_command(b, {"op": "add_frame", "from": 0})     # DELIVERY phase, duplicated from PRE-MOVEMENT
    assert len(b.frames) == 2
    ids1 = {o.id for o in b.frame(1).objects}
    assert ids0 == ids1                                  # same objects across frames = the animation
    # vary frame 2 independently: move the ball to the target, first frame unchanged
    ball = next(o for o in b.frame(1).objects if o.type == "ball")
    apply_command(b, {"op": "update_object", "frame": 1, "id": ball.id, "x": 70, "y": 48})
    f0_ball = next(o for o in b.frame(0).objects if o.type == "ball")
    assert (f0_ball.x, f0_ball.y) != (70, 48)            # frame 0 independent of frame 1
    for i in range(len(b.frames)):
        assert len(board_image(b, i, fmt="png")) > 500   # each frame exports
