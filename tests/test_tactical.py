"""Phase 14 - Tactical Board CORE (pure, interaction-agnostic).

Proves the production-ready core independent of any UI: serialization round-trips,
the command dispatcher + undo/redo, the SVG renderer for every pitch/object, the
built-in templates, and WorkspaceManager-backed persistence + export. The Streamlit
page is a thin layer over this and is not exercised here.
"""
import os
import pathlib
import sys

os.environ["FAP_TEST"] = "1"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from fap.tactical import (
    Board, History, TacticalService, apply_command, board_svg, builtin_names,
    builtin_template, new_board,
)
from fap.tactical.models import PITCH_KINDS, TacticalObject
from fap.tactical.ops import default_props


def test_board_roundtrips_json():
    b = builtin_template("4-3-3")
    b2 = Board.from_dict(b.to_dict())
    assert b2.to_dict() == b.to_dict()
    assert len(b2.frames[0].objects) == 11


def test_add_update_delete_duplicate_commands():
    b = new_board("t")
    r = apply_command(b, {"op": "add_object", "type": "player", "x": 40, "y": 60})
    oid = r["id"]
    assert b.frames[0].object(oid).x == 40
    apply_command(b, {"op": "update_object", "id": oid, "x": 12, "props": {"number": 9}})
    assert b.frames[0].object(oid).x == 12 and b.frames[0].object(oid).props["number"] == 9
    d = apply_command(b, {"op": "duplicate_object", "id": oid})
    assert len(b.frames[0].objects) == 2 and d["id"] != oid
    apply_command(b, {"op": "delete_object", "id": oid})
    assert b.frames[0].object(oid) is None


def test_frames_and_object_persistence_across_frames():
    b = new_board("t")
    r = apply_command(b, {"op": "add_object", "type": "player", "x": 10, "y": 10})
    oid = r["id"]
    apply_command(b, {"op": "add_frame", "from": 0})            # duplicates objects
    assert len(b.frames) == 2
    # same object id exists in frame 2 (the animation contract)
    assert b.frames[1].object(oid) is not None
    # moving it in frame 2 does not change frame 1
    apply_command(b, {"op": "update_object", "frame": 1, "id": oid, "x": 90})
    assert b.frames[0].object(oid).x == 10 and b.frames[1].object(oid).x == 90


def test_undo_redo():
    b = new_board("t")
    h = History()
    h.record(b)
    apply_command(b, {"op": "add_object", "type": "ball"})
    assert len(b.frames[0].objects) == 1
    b = h.undo(b)
    assert len(b.frames[0].objects) == 0 and h.can_redo()
    b = h.redo(b)
    assert len(b.frames[0].objects) == 1


def test_render_all_pitches_and_objects():
    for kind in PITCH_KINDS:
        b = new_board("t", pitch_kind=kind)
        for t in ("player", "ball", "cone", "goal", "mannequin", "arrow", "curved_arrow",
                  "dashed_arrow", "line", "zone", "highlight", "text", "shape"):
            b.frames[0].objects.append(TacticalObject(id=t, type=t, props=default_props(t)))
        svg = board_svg(b, 0, grid=True, selected_id="player")
        assert svg.startswith("<svg") and "xmlns=" in svg and "</svg>" in svg
    # vertical orientation renders too
    b = new_board("v")
    b.pitch.orientation = "vertical"
    assert "rotate(90)" in board_svg(b, 0)


def test_templates_build():
    for name in builtin_names():
        b = builtin_template(name)
        assert isinstance(b, Board) and b.frames and any(o.type == "player" for o in b.frames[0].objects)


def test_service_persistence_and_export():
    class FakePreset:
        def __init__(s, i, n, d): s.id, s.name, s.document, s.kind = i, n, d, "tactical_board"

    class FakeWM:
        def __init__(s): s.store = {}; s.auto = {}
        def save_preset(s, u, *, kind, name, document, scope="user", preset_id=None):
            pid = preset_id or f"p{len(s.store)}"
            s.store[pid] = FakePreset(pid, name, document); return s.store[pid]
        def list_presets(s, u, *, kind=None): return list(s.store.values())
        def delete_preset(s, u, pid): s.store.pop(pid, None)
        def load_autosave(s, u, scope="session"): return dict(s.auto.get(scope, {}))
        def autosave(s, u, doc, scope="session"): s.auto[scope] = dict(doc)

    svc = TacticalService(FakeWM())
    user = object()
    b = builtin_template("4-4-2")
    pr = svc.save_board(user, b, name="My Board")
    assert svc.list_boards(user) and svc.board_of(pr).to_dict() == b.to_dict()
    svc.toggle_favorite(user, pr.id)
    assert pr.id in svc.favorites(user)
    data, mime, fname = svc.export(b, 0, fmt="svg")
    assert data.startswith(b"<svg") and mime == "image/svg+xml" and fname.endswith(".svg")
    assert "svg" in svc.export_formats()


def test_page_registers_under_analysis():
    from fap.ui.page import load_builtin_pages, page_registry, get_page
    load_builtin_pages()
    assert "tactical_board" in page_registry.ids()
    page = get_page("tactical_board")
    assert page.info.name == "Tactical Board" and page.section == "Analysis"


# ----------------------------------------------------------------- Phase 15 (canvas)
# The JS drag-and-drop canvas is interaction-only: it emits the SAME JSON commands the
# model already understands. ``parse_result`` is the trust boundary between the browser
# and the model, so it is unit-tested here without a browser.
def test_parse_result_accepts_valid_intent():
    from fap.ui.builtin.tactical_canvas import parse_result
    r = parse_result({"ts": 3, "select": "obj_1",
                      "commands": [{"op": "update_object", "id": "obj_1", "x": 22, "y": 71}]})
    assert r is not None and r["ts"] == 3.0 and r["select"] == "obj_1"
    assert r["commands"] == [{"op": "update_object", "id": "obj_1", "x": 22.0, "y": 71.0}]


def test_parse_result_filters_and_sanitizes():
    from fap.ui.builtin.tactical_canvas import parse_result
    r = parse_result({"ts": 1, "commands": [
        {"op": "add_frame", "index": 0},                 # not allow-listed -> dropped
        {"op": "set_pitch", "kind": "half"},             # not allow-listed -> dropped
        {"op": "update_object"},                         # missing id -> dropped
        {"op": "add_object"},                            # missing type -> dropped
        {"op": "add_object", "type": "player", "x": 5, "y": 6,
         "evil": "rm -rf", "props": {"team": "away"}},   # extra field stripped
    ]})
    assert r is not None
    assert r["commands"] == [{"op": "add_object", "type": "player", "x": 5.0, "y": 6.0,
                              "props": {"team": "away"}}]
    assert "select" in r and r["select"] == "__keep__"


def test_parse_result_rejects_junk():
    from fap.ui.builtin.tactical_canvas import parse_result
    assert parse_result(None) is None
    assert parse_result({"commands": []}) is None            # no ts
    assert parse_result({"ts": 2, "commands": []}) is None   # nothing actionable
    # a selection-only report (no commands) is still actionable
    assert parse_result({"ts": 2, "select": None})["select"] is None


def test_canvas_commands_round_trip_through_model():
    """Everything the canvas is allowed to emit must be a legal model command."""
    from fap.ui.builtin.tactical_canvas import parse_result
    b = new_board("t")
    add = parse_result({"ts": 1, "commands": [{"op": "add_object", "type": "player",
                                               "x": 40, "y": 60, "props": {"number": 9}}]})
    oid = apply_command(b, {**add["commands"][0], "frame": 0})["id"]
    assert b.frames[0].object(oid).x == 40 and b.frames[0].object(oid).props["number"] == 9
    mv = parse_result({"ts": 2, "commands": [{"op": "update_object", "id": oid, "x": 10, "y": 12}]})
    apply_command(b, {**mv["commands"][0], "frame": 0})
    assert b.frames[0].object(oid).x == 10
    dl = parse_result({"ts": 3, "commands": [{"op": "delete_object", "id": oid}]})
    apply_command(b, {**dl["commands"][0], "frame": 0})
    assert b.frames[0].object(oid) is None


# ---------------------------------------------------------- Phase 15b (curve handle + colour)
def test_curve_control_point_roundtrips():
    """The JS curve handle derives ``curvature`` from a dragged control point by inverting
    the renderer's forward formula. A purely-perpendicular drag must round-trip EXACTLY so
    the on-canvas handle and Python rendering stay in perfect sync."""
    from fap.tactical import curve_control_point, curvature_from_control_point
    cases = [(0, 0, 100, 0, 0.3), (10, 20, 90, 60, -0.45), (0, 0, 50, 50, 0.8),
             (33, 77, 12, 4, 0.0), (200, 50, 50, 300, -1.0)]
    for x1, y1, x2, y2, k in cases:
        cx, cy = curve_control_point(x1, y1, x2, y2, k)
        back = curvature_from_control_point(x1, y1, x2, y2, cx, cy)
        assert abs(back - k) < 1e-9
    # exact forward values for the renderer's default curvature (0.3), horizontal line
    assert curve_control_point(0, 0, 100, 0, 0.3) == (50.0, -30.0)
    # degenerate zero-length line -> 0 curvature, no division by zero
    assert curvature_from_control_point(5, 5, 5, 5, 9, 9) == 0.0


def test_render_curved_arrow_uses_shared_control_point():
    """render.py must draw the quadratic through exactly ``curve_control_point`` (single
    source of truth shared with the canvas handle)."""
    from fap.tactical import curve_control_point
    from fap.tactical.render import _px
    b = new_board("t")
    b.frames[0].objects.append(TacticalObject(
        id="a", type="curved_arrow", x=10.0, y=20.0,
        props={**default_props("curved_arrow"), "x2": 80.0, "y2": 60.0, "curvature": 0.4}))
    svg = board_svg(b, 0)
    x1, y1 = _px(10.0, 20.0); x2, y2 = _px(80.0, 60.0)
    cx, cy = curve_control_point(x1, y1, x2, y2, 0.4)
    assert f"Q {cx} {cy}" in svg


def test_canvas_curvature_command_survives_parse():
    """A curve-handle drag emits an ``update_object`` with a ``curvature`` prop; it must
    pass the trust boundary and reach the model."""
    from fap.ui.builtin.tactical_canvas import parse_result
    r = parse_result({"ts": 5, "commands": [
        {"op": "update_object", "id": "a", "props": {"curvature": 0.42}}]})
    assert r is not None
    assert r["commands"] == [{"op": "update_object", "id": "a", "props": {"curvature": 0.42}}]


def test_colour_override_round_trips_through_commands():
    """The per-object colour pickers (Part 3) are plain ``props["color"]`` overrides. They
    must round-trip through add/update, and clearing back to '' must stick (so render.py's
    ``p.get('color') or _c(...)`` falls back to the team/theme colour)."""
    b = new_board("t")
    pid = apply_command(b, {"op": "add_object", "type": "player", "x": 40, "y": 60,
                            "props": {"team": "home", "color": "#ff8800"}})["id"]
    assert b.frames[0].object(pid).props["color"] == "#ff8800"
    apply_command(b, {"op": "update_object", "id": pid, "props": {"color": "#00aaff"}})
    assert b.frames[0].object(pid).props["color"] == "#00aaff"
    apply_command(b, {"op": "update_object", "id": pid, "props": {"color": ""}})
    assert b.frames[0].object(pid).props["color"] == ""
    zid = apply_command(b, {"op": "add_object", "type": "zone", "x": 30, "y": 30,
                            "props": {"color": "#123456"}})["id"]
    apply_command(b, {"op": "update_object", "id": zid, "props": {"color": "#654321"}})
    assert b.frames[0].object(zid).props["color"] == "#654321"


def test_colour_override_reflected_in_render():
    """A set override paints that colour; clearing it falls back to the default team colour."""
    from fap.tactical.render import DEFAULT_COLORS
    b = new_board("t")
    pid = apply_command(b, {"op": "add_object", "type": "player", "x": 50, "y": 50,
                            "props": {"team": "home", "color": "#abcdef"}})["id"]
    assert "#abcdef" in board_svg(b, 0)
    apply_command(b, {"op": "update_object", "id": pid, "props": {"color": ""}})
    assert DEFAULT_COLORS["home"] in board_svg(b, 0)


def test_matplotlib_export_png_pdf():
    """PNG/PDF export draws the board model via matplotlib (no cairo needed)."""
    from fap.tactical import export_render
    if not export_render.available():
        return                                   # environment without matplotlib: skip
    b = builtin_template("4-3-3")
    png = export_render.board_image(b, 0, fmt="png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000
    pdf = export_render.board_image(b, 0, fmt="pdf")
    assert pdf[:5] == b"%PDF-" and len(pdf) > 500
    # a vertical board still exports (rotated) without error
    b.pitch.orientation = "vertical"
    assert export_render.board_image(b, 0, fmt="png")[:8] == b"\x89PNG\r\n\x1a\n"


def test_service_export_formats_and_png():
    from fap.tactical import export_render
    svc = TacticalService(None)
    fmts = svc.export_formats()
    assert "svg" in fmts
    b = builtin_template("4-4-2")
    if export_render.available():
        assert "png" in fmts and "pdf" in fmts
        data, mime, fname = svc.export(b, 0, fmt="png")
        assert mime == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n" and fname.endswith(".png")
        data, mime, fname = svc.export(b, 0, fmt="pdf")
        assert mime == "application/pdf" and data[:5] == b"%PDF-" and fname.endswith(".pdf")
    # svg always works and requesting an unavailable fmt degrades to svg
    data, mime, fname = svc.export(b, 0, fmt="svg")
    assert mime == "image/svg+xml" and data.startswith(b"<svg")


def test_canvas_wrapper_never_raises():
    """``tactical_canvas`` always returns a (rendered, intent) tuple, even outside a
    live Streamlit run - so the page can always fall back gracefully."""
    from fap.ui.builtin.tactical_canvas import tactical_canvas
    out = tactical_canvas("<svg></svg>", [], key="k", colors={}, palette=[],
                          selected_id=None, snap=0.0, editable=True, nonce="n")
    assert isinstance(out, tuple) and len(out) == 2
    assert isinstance(out[0], bool) and (out[1] is None or isinstance(out[1], dict))
