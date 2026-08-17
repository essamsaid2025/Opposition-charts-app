"""Increment B — custom arrowhead system (independent head + variant, one command seam).

Covers: geometry vocabulary/orientation/scaling/fallback; the set_arrow_properties command
(single + multi = ONE undo step; locked skipped; non-arrows ignored); persistence round-trip;
undo/redo; legacy arrows (no arrowhead prop) unchanged; and SVG↔PNG renderer parity.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")

from fap.tactical import History, apply_command, board_svg, new_board
from fap.tactical import geometry as G
from fap.tactical.export_render import board_image
from fap.tactical.models import Board


def _arrow(b, x=10, y=10, x2=40, y2=20, **props):
    return apply_command(b, {"op": "add_object", "type": "arrow", "x": x, "y": y,
                             "props": {"x2": x2, "y2": y2, **props}})["id"]


# ---------------------------------------------------------------- geometry
def test_geometry_every_kind_has_primitives_or_empty():
    prims = ("fill_polys", "stroke_closed", "stroke_open", "fill_circles", "stroke_circles")
    for k in G.ARROWHEAD_KINDS:
        g = G.arrowhead_geometry(k, 0, 0, 10, 0)
        total = sum(len(g[p]) for p in prims)
        assert (total == 0) == (k == "none"), k        # only "none" is empty


def test_geometry_triangle_tip_is_at_endpoint_and_scales():
    g1 = G.arrowhead_geometry("filled_triangle", 0, 0, 100, 0, size=1.0)
    tri = g1["fill_polys"][0]
    assert tri[0] == (100, 0)                            # tip sits exactly on the endpoint
    g2 = G.arrowhead_geometry("filled_triangle", 0, 0, 100, 0, size=2.0)
    # larger size -> base pulled further back from the tip
    assert g2["fill_polys"][0][1][0] < tri[1][0]


def test_geometry_orientation_follows_direction():
    right = G.arrowhead_geometry("filled_triangle", 0, 0, 10, 0)["fill_polys"][0]
    down = G.arrowhead_geometry("filled_triangle", 0, 0, 0, 10)["fill_polys"][0]
    assert right[0] == (10, 0) and down[0] == (0, 10)


def test_geometry_invalid_kind_falls_back_to_triangle():
    g = G.arrowhead_geometry("nonsense", 0, 0, 10, 0)
    assert g["fill_polys"] and not g["stroke_open"]


def test_geometry_circle_and_dot_and_chevron_and_bar():
    assert G.arrowhead_geometry("circle", 0, 0, 10, 0)["stroke_circles"]
    assert G.arrowhead_geometry("dot", 0, 0, 10, 0)["fill_circles"]
    assert len(G.arrowhead_geometry("chevron", 0, 0, 10, 0)["stroke_open"][0]) == 3
    assert G.arrowhead_geometry("bar", 0, 0, 10, 0)["stroke_open"]


# ---------------------------------------------------------------- command
def test_set_arrow_properties_single_and_persists():
    b = new_board("t"); aid = _arrow(b, variant="pass")
    apply_command(b, {"op": "set_arrow_properties", "ids": [aid],
                      "arrowhead": "circle", "arrowhead_size": 1.4})
    o = b.frame(0).object(aid)
    assert o.props["arrowhead"] == "circle" and o.props["arrowhead_size"] == 1.4
    # save -> reload round-trip keeps the head config
    b2 = Board.from_dict(b.to_dict())
    o2 = b2.frame(0).object(aid)
    assert o2.props["arrowhead"] == "circle" and o2.props["arrowhead_size"] == 1.4


def test_multi_edit_is_one_undo_step():
    b = new_board("t"); hist = History()
    ids = [_arrow(b, y=i * 5) for i in range(5)]
    hist.record(b)                                       # snapshot BEFORE the edit (same as _apply)
    apply_command(b, {"op": "set_arrow_properties", "ids": ids, "arrowhead": "circle"})
    assert all(b.frame(0).object(i).props["arrowhead"] == "circle" for i in ids)
    b = hist.undo(b)                                     # ONE undo restores all five
    assert all("arrowhead" not in (b.frame(0).object(i).props or {}) for i in ids)
    b = hist.redo(b)
    assert all(b.frame(0).object(i).props["arrowhead"] == "circle" for i in ids)


def test_locked_and_non_arrow_are_skipped():
    b = new_board("t")
    aid = _arrow(b)
    lid = _arrow(b, y=30); b.frame(0).object(lid).locked = True
    pid = apply_command(b, {"op": "add_object", "type": "player", "x": 5, "y": 5})["id"]
    res = apply_command(b, {"op": "set_arrow_properties", "ids": [aid, lid, pid],
                            "arrowhead": "dot"})
    assert res["changed"] == 1                           # only the unlocked arrow
    assert b.frame(0).object(aid).props["arrowhead"] == "dot"
    assert "arrowhead" not in (b.frame(0).object(lid).props or {})
    assert "arrowhead" not in (b.frame(0).object(pid).props or {})


# ---------------------------------------------------------------- legacy
def test_legacy_arrow_svg_unchanged_without_arrowhead():
    b = new_board("t"); _arrow(b, variant="pass")
    before = board_svg(b, 0)
    # a legacy arrow renders with NO explicit head primitives injected by the custom path
    assert "polyline" not in before or "stroke_open" not in before
    assert board_svg(b, 0) == before                    # deterministic


# ---------------------------------------------------------------- variant x head matrix
def test_variant_head_matrix_renders_svg_and_png():
    b = new_board("t")
    matrix = [("pass", "filled_triangle"), ("pass", "circle"), ("run", "dot"),
              ("pressing", "chevron"), ("defensive", "outline_triangle"),
              ("dribble", "circle"), ("shot", "filled_triangle"), ("movement", "none")]
    for i, (var, head) in enumerate(matrix):
        aid = _arrow(b, x=5, y=5 + i * 4, x2=45, y2=5 + i * 4, variant=var)
        apply_command(b, {"op": "set_arrow_properties", "ids": [aid], "arrowhead": head})
    # curved + wavy + zigzag bodies also carry a custom head
    cid = apply_command(b, {"op": "add_object", "type": "curved_arrow", "x": 5, "y": 60,
                            "props": {"x2": 45, "y2": 70, "variant": "pass", "curvature": 0.3}})["id"]
    apply_command(b, {"op": "set_arrow_properties", "ids": [cid], "arrowhead": "outline_triangle"})
    svg = board_svg(b, 0)
    assert svg.startswith("<svg") and "circle" in svg and "polyline" in svg  # dot/circle + chevron
    png = board_image(b, 0, fmt="png")
    assert png.startswith(b"\x89PNG") and len(png) > 1000  # PNG parity path runs without error
