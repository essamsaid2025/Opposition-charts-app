"""Arrow styling the analysis UI now exposes: a ``dashed`` prop that dashes ANY vector (including a
curved arrow, which the type system couldn't dash before) and an explicit ``arrowhead`` kind. Both
must render in SVG and export without raising, and stay absent-safe (no prop = unchanged)."""
import pytest

from fap.tactical import export_render
from fap.tactical.geometry import ARROWHEAD_KINDS
from fap.tactical.models import Frame, TacticalObject, new_board
from fap.tactical.render import board_svg


def _board_with(obj):
    b = new_board("t", pitch_kind="blank")
    b.frames[0] = Frame(id="f", name="f", objects=[obj])
    return b


def test_curved_arrow_dashed_prop_renders_dashed():
    o = TacticalObject(id="a", type="curved_arrow", x=20, y=20,
                       props={"x2": 60, "y2": 40, "dashed": True})
    svg = board_svg(_board_with(o), 0)
    assert "stroke-dasharray" in svg                      # curved arrow is now dashable


def test_plain_curved_arrow_is_not_dashed():
    o = TacticalObject(id="a", type="curved_arrow", x=20, y=20, props={"x2": 60, "y2": 40})
    assert "stroke-dasharray" not in board_svg(_board_with(o), 0)


def test_straight_arrow_dashed_prop_renders_dashed():
    o = TacticalObject(id="a", type="arrow", x=20, y=20, props={"x2": 60, "y2": 20, "dashed": True})
    assert "stroke-dasharray" in board_svg(_board_with(o), 0)


@pytest.mark.parametrize("kind", ARROWHEAD_KINDS)
def test_every_arrowhead_kind_renders_and_exports(kind):
    o = TacticalObject(id="a", type="arrow", x=20, y=20,
                       props={"x2": 60, "y2": 30, "arrowhead": kind})
    svg = board_svg(_board_with(o), 0)
    assert "<svg" in svg
    if export_render.available():
        png = export_render.board_image(_board_with(o), 0, fmt="png")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_curved_dashed_with_circle_head_combines():
    o = TacticalObject(id="a", type="curved_arrow", x=20, y=20,
                       props={"x2": 60, "y2": 40, "dashed": True, "arrowhead": "circle"})
    svg = board_svg(_board_with(o), 0)
    assert "stroke-dasharray" in svg and "<circle" in svg
