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


# ---------------------------------------------------------- zone/shape stroke + fill styling
def _one_obj_svg(o):
    """board_svg for a blank board holding just ``o``, plus that object's <g> inner SVG."""
    import re
    b = new_board("t", pitch_kind="blank")
    b.frames[0].objects = [o]
    svg = board_svg(b, 0)
    m = re.search(r'<g data-oid="%s"[^>]*>(.*?)</g>' % o.id, svg)
    return b, svg, (m.group(1) if m else "")


def test_zone_shape_no_new_props_render_identical_to_before():
    """The no-regression guarantee: a zone/highlight/shape with only the classic props must
    render byte-identically (SVG) to before this change, and its PNG must be identical to the
    same object with the new props explicitly set to their documented defaults."""
    from fap.tactical import export_render
    # pinned 'before' SVG snapshots (captured from the pre-change renderer)
    zone = TacticalObject(id="z", type="zone", x=40.0, y=30.0,
                          props={"w": 20.0, "h": 16.0, "color": "", "opacity": 0.28, "shape": "rect"})
    _, _, zel = _one_obj_svg(zone)
    assert zel == ('<rect x="315.0" y="149.6" width="210.0" height="108.8" rx="6" '
                   'fill="#2f7bd6" fill-opacity="0.28" stroke="#2f7bd6" stroke-width="2"/>')
    hi = TacticalObject(id="h", type="highlight", x=60.0, y=50.0,
                        props={"w": 20.0, "h": 16.0, "color": "", "opacity": 0.28, "shape": "rect"})
    _, _, hel = _one_obj_svg(hi)
    assert hel == ('<ellipse cx="630.0" cy="340.0" rx="105.0" ry="54.4" '
                   'fill="#2f7bd6" fill-opacity="0.28" stroke="#2f7bd6" stroke-width="2"/>')
    # PNG: adding the new props at their defaults must not change a single byte (proves the
    # new code path is a no-op at defaults, robust across matplotlib versions/platforms)
    if export_render.available():
        b_old, _, _ = _one_obj_svg(zone)
        z_new = TacticalObject(id="z", type="zone", x=40.0, y=30.0,
                               props={"w": 20.0, "h": 16.0, "color": "", "opacity": 0.28,
                                      "shape": "rect", "filled": True, "stroke_color": "",
                                      "stroke_width": 2.0, "stroke_style": "solid"})
        b_new, _, _ = _one_obj_svg(z_new)
        assert export_render.board_image(b_old, 0, fmt="png") == \
            export_render.board_image(b_new, 0, fmt="png")


def test_zone_unfilled_has_no_fill_and_exports():
    from fap.tactical import export_render
    o = TacticalObject(id="u", type="zone", x=40.0, y=30.0,
                       props={"w": 20.0, "h": 16.0, "filled": False})
    b, _, el = _one_obj_svg(o)
    assert 'fill="none"' in el                          # outline only, no fill colour
    assert 'fill="#' not in el                          # the fill is not a colour
    if export_render.available():
        assert export_render.board_image(b, 0, fmt="png")[:8] == b"\x89PNG\r\n\x1a\n"


def test_zone_stroke_overrides_reflected_in_svg():
    o = TacticalObject(id="k", type="zone", x=40.0, y=30.0,
                       props={"w": 20.0, "h": 16.0, "stroke_color": "#ff0000",
                              "stroke_width": 5.0, "stroke_style": "dashed"})
    _, _, el = _one_obj_svg(o)
    assert 'stroke="#ff0000"' in el
    assert 'stroke-width="5"' in el                     # 5.0 -> "5"
    assert 'stroke-dasharray="10 8"' in el              # dashed border == dashed_arrow dash


def test_shape_triangle_renders_polygon_in_both_renderers():
    from fap.tactical import export_render
    o = TacticalObject(id="t", type="shape", x=50.0, y=40.0,
                       props={"w": 20.0, "h": 16.0, "shape": "triangle"})
    b, _, el = _one_obj_svg(o)
    assert "<polygon" in el and "points=" in el
    if export_render.available():
        assert export_render.board_image(b, 0, fmt="png")[:8] == b"\x89PNG\r\n\x1a\n"
        assert export_render.board_image(b, 0, fmt="pdf")[:5] == b"%PDF-"


def test_set_pitch_orientation_toggle_flips_and_exports():
    """The toolbar orientation toggle only calls the existing ``set_pitch`` op. Flipping to
    vertical updates the model and BOTH renderers (live SVG rotates; matplotlib PNG/GIF
    export doesn't raise); the default stays 'horizontal' so existing boards are unchanged."""
    from fap.tactical import export_render
    b = new_board("t")
    assert b.pitch.orientation == "horizontal"           # default: unchanged from today
    assert "rotate(90)" not in board_svg(b, 0)           # a horizontal board is not rotated

    apply_command(b, {"op": "set_pitch", "orientation": "vertical"})
    assert b.pitch.orientation == "vertical"
    assert "rotate(90)" in board_svg(b, 0)               # live board rotates to portrait
    if export_render.available():                        # PNG + GIF export come out (rotated)
        assert export_render.board_image(b, 0, fmt="png")[:8] == b"\x89PNG\r\n\x1a\n"
        assert export_render.board_gif(b)[:4] == b"GIF8"

    apply_command(b, {"op": "set_pitch", "orientation": "horizontal"})   # toggling back
    assert b.pitch.orientation == "horizontal"
    assert "rotate(90)" not in board_svg(b, 0)


def test_library_items_all_reachable_and_addable():
    """The icon-rail refactor must not drop or rename any library item: every
    ``(otype, extra)`` the old accordions exposed is still present AND still adds through
    the model via the same path ``_add`` uses (default_props + extra -> add_object)."""
    from fap.tactical.ops import default_props
    from fap.ui.builtin.tactical_board import _LIBRARY
    flat = [(otype, extra) for _t, _i, items in _LIBRARY for _l, otype, extra in items]
    assert [o for o, _ in flat] == [
        "player", "player", "player", "ball", "cone", "goal", "mannequin",
        "arrow", "curved_arrow", "dashed_arrow", "line", "zone", "highlight", "text", "shape"]
    b = new_board("t")
    for otype, extra in flat:
        props = default_props(otype); props.update(extra)
        res = apply_command(b, {"op": "add_object", "frame": 0, "type": otype,
                                "x": 50.0, "y": 50.0, "props": props})
        assert res.get("id")                       # each rail item is a real, addable object


def test_canvas_palette_output_unchanged():
    """The drag-to-canvas chips must be byte-for-byte identical after the rail refactor —
    ``_canvas_palette`` still derives the SAME {label,type,props,color} shape from _LIBRARY."""
    from fap.ui.builtin.tactical_board import _canvas_palette
    colors = {"home": "#111111", "away": "#222222", "ball": "#333333",
              "cone": "#444444", "zone": "#555555", "accent": "#666666"}
    assert _canvas_palette(colors) == [
        {"label": "Home player", "type": "player", "props": {"team": "home"}, "color": "#111111"},
        {"label": "Away player", "type": "player", "props": {"team": "away"}, "color": "#222222"},
        {"label": "Goalkeeper", "type": "player",
         "props": {"team": "home", "goalkeeper": True}, "color": "#111111"},
        {"label": "Ball", "type": "ball", "props": {}, "color": "#333333"},
        {"label": "Cone", "type": "cone", "props": {}, "color": "#444444"},
        {"label": "Goal", "type": "goal", "props": {}, "color": "#666666"},
        {"label": "Mannequin", "type": "mannequin", "props": {}, "color": "#666666"},
        {"label": "Arrow", "type": "arrow", "props": {}, "color": "#666666"},
        {"label": "Curved arrow", "type": "curved_arrow", "props": {}, "color": "#666666"},
        {"label": "Dashed arrow", "type": "dashed_arrow", "props": {}, "color": "#666666"},
        {"label": "Line", "type": "line", "props": {}, "color": "#666666"},
        {"label": "Zone", "type": "zone", "props": {}, "color": "#555555"},
        {"label": "Highlight", "type": "highlight",
         "props": {"shape": "ellipse"}, "color": "#555555"},
        {"label": "Text", "type": "text", "props": {"text": "Text"}, "color": "#666666"},
        {"label": "Shape", "type": "shape", "props": {}, "color": "#555555"},
    ]


def test_canvas_wrapper_never_raises():
    """``tactical_canvas`` always returns a (rendered, intent) tuple, even outside a
    live Streamlit run - so the page can always fall back gracefully."""
    from fap.ui.builtin.tactical_canvas import tactical_canvas
    out = tactical_canvas("<svg></svg>", [], key="k", colors={}, palette=[],
                          selected_id=None, snap=0.0, editable=True, nonce="n")
    assert isinstance(out, tuple) and len(out) == 2
    assert isinstance(out[0], bool) and (out[1] is None or isinstance(out[1], dict))


# ---------------------------------------------------------- purpose-built rail icons
def test_new_rail_icons_resolve():
    from fap.theme.icons import has_icon, icon
    for name in ("ball", "cone", "goal", "mannequin", "line-straight", "arrow-curved",
                 "arrow-dashed", "zone-marker", "shapes",
                 "arrow-straight", "circle", "square", "text"):   # reference-order additions
        assert has_icon(name), name
        svg = icon(name)
        assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>") and len(svg) > 40


def test_every_library_icon_has_a_real_path():
    """Guards against a future typo silently rendering a blank rail icon."""
    from fap.theme.icons import has_icon
    from fap.ui.builtin.tactical_board import _LIBRARY
    for _title, ic, _items in _LIBRARY:
        assert has_icon(ic), f"library category references missing icon {ic!r}"


# ---------------------------------------------------------- click-drag draw tool
def test_draw_tool_defaults_to_select_and_covers_real_types():
    from fap.ui.builtin.tactical_board import _DRAW_TOOLS
    assert _DRAW_TOOLS[0] == ("select", "Select / Move")    # persistent default = Select/Move (off)
    assert [k for k, _ in _DRAW_TOOLS[1:]] == [
        "zone", "shape", "arrow", "curved_arrow", "dashed_arrow", "line"]
    for key, _label in _DRAW_TOOLS[1:]:                     # each arms a real, addable type
        assert isinstance(default_props(key), dict)
    # the props the JS falls back to for a near-zero drag exist for each type
    assert {"w", "h"} <= set(default_props("zone")) and {"w", "h"} <= set(default_props("shape"))
    assert {"x2", "y2", "curvature"} <= set(default_props("curved_arrow"))


def test_escape_draw_reset_intent_round_trips_but_is_not_a_command():
    """Escape emits a UI-only ``draw_reset`` (like ``select``) - it must survive parse_result
    WITHOUT being turned into a board command, so the tool can be disarmed without mutating
    the board."""
    from fap.ui.builtin.tactical_canvas import parse_result
    r = parse_result({"ts": 9, "select": "__keep__", "commands": [], "draw_reset": True})
    assert r is not None and r.get("draw_reset") is True
    assert r["commands"] == [] and r["select"] == "__keep__"   # no board command produced
    # a plain empty payload is still nothing-actionable (draw_reset only when truthy)
    assert parse_result({"ts": 9, "select": "__keep__", "commands": []}) is None
    assert parse_result({"ts": 9, "commands": [], "draw_reset": False}) is None


def test_drawn_zone_command_round_trips_through_trust_boundary():
    """A drawn zone emits the SAME add_object shape as any other add, with the drawn w/h in
    props; it must survive parse_result and create a zone at that centre + size."""
    from fap.ui.builtin.tactical_canvas import parse_result
    b = new_board("t")
    drawn = {"op": "add_object", "type": "zone", "x": 55.0, "y": 42.0,
             "props": {"w": 30.0, "h": 18.0, "opacity": 0.28, "shape": "rect"}}
    r = parse_result({"ts": 1, "commands": [drawn]})
    assert r is not None
    oid = apply_command(b, {**r["commands"][0], "frame": 0})["id"]
    o = b.frames[0].object(oid)
    assert o.type == "zone" and (o.x, o.y) == (55.0, 42.0)
    assert o.props["w"] == 30.0 and o.props["h"] == 18.0


def test_drawn_vector_command_round_trips_through_trust_boundary():
    from fap.ui.builtin.tactical_canvas import parse_result
    b = new_board("t")
    drawn = {"op": "add_object", "type": "arrow", "x": 10.0, "y": 12.0,
             "props": {"x2": 44.0, "y2": 66.0, "curvature": 0.0}}
    r = parse_result({"ts": 2, "commands": [drawn]})
    oid = apply_command(b, {**r["commands"][0], "frame": 0})["id"]
    o = b.frames[0].object(oid)
    assert o.type == "arrow" and (o.x, o.y) == (10.0, 12.0)
    assert o.props["x2"] == 44.0 and o.props["y2"] == 66.0


def test_canvas_wrapper_accepts_draw_tool_arg():
    from fap.ui.builtin.tactical_canvas import tactical_canvas
    out = tactical_canvas("<svg></svg>", [], key="k", colors={}, palette=[],
                          selected_id=None, snap=0.0, editable=True, nonce="n",
                          draw_tool={"type": "zone", "props": default_props("zone")})
    assert isinstance(out, tuple) and len(out) == 2
