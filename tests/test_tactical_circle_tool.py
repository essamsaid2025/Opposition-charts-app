"""Circle/ring draw tool + lazy-export toolbar signature (post-Increment-B follow-ups).

The circle is a first-class object type that reuses the zone/ellipse renderer (a true
ring by default), reachable as a non-vector draw tool (so the JS box-draws it). The
export is now prepared lazily, keyed by a board+frame+format signature.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")

from fap.tactical import apply_command, board_svg, new_board
from fap.tactical.export_render import board_image
from fap.tactical.models import OBJECT_TYPES
from fap.tactical.ops import default_props


def test_circle_is_a_registered_type_with_ring_defaults():
    assert "circle" in OBJECT_TYPES
    d = default_props("circle")
    assert d["shape"] == "ellipse" and d["filled"] is False   # outline ring by default
    assert d["w"] == d["h"]                                    # a true circle at default size


def test_circle_renders_as_ellipse_in_svg_and_png():
    b = new_board("t")
    cid = apply_command(b, {"op": "add_object", "type": "circle", "x": 50, "y": 50,
                            "props": default_props("circle")})["id"]
    svg = board_svg(b, 0)
    assert "<ellipse" in svg and 'fill="none"' in svg        # ring: ellipse, unfilled
    assert board_image(b, 0, fmt="png").startswith(b"\x89PNG")
    # a circle can still be filled/coloured like any zone (full flexibility)
    apply_command(b, {"op": "update_object", "frame": 0, "id": cid,
                      "props": {"filled": True, "color": "#3366ff"}})
    assert "#3366ff" in board_svg(b, 0)


def test_circle_draw_tool_is_non_vector_so_js_box_draws_it():
    from fap.ui.builtin.tactical_board import _DRAW_TOOLS, _TOOL_ICONS
    keys = [k for k, _ in _DRAW_TOOLS]
    assert "circle" in keys and "circle" in _TOOL_ICONS
    # near-zero-drag fallback needs w/h (the JS reads them for a click-placed circle)
    assert {"w", "h"} <= set(default_props("circle"))
