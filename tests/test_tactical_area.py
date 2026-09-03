"""Pitch AREA (viewBox crop) — the half-pitch / final-third framing that fills the panel with no
wasted space, in both orientations. Coordinates stay 0-100 over the FULL pitch; only the visible
window shrinks. The default ``full`` stays byte-identical to before (critical back-compat)."""
import pytest

from fap.tactical import export_render
from fap.tactical.models import PITCH_AREAS, PitchSpec, new_board
from fap.tactical.ops import apply_command
from fap.tactical.render import area_window_display, board_svg


# ---------------------------------------------------------------- model round-trip
def test_pitchspec_area_defaults_full_and_round_trips():
    assert PitchSpec().area == "full"
    ps = PitchSpec(area="att_third")
    assert PitchSpec.from_dict(ps.to_dict()).area == "att_third"


def test_pitchspec_from_old_dict_without_area_is_full():
    # boards saved before this feature had no "area" key -> must load as "full"
    assert PitchSpec.from_dict({"kind": "full", "orientation": "horizontal"}).area == "full"


def test_pitchspec_from_dict_rejects_unknown_area():
    assert PitchSpec.from_dict({"area": "bogus"}).area == "full"


# ---------------------------------------------------------------- set_pitch op
def test_set_pitch_accepts_valid_area_and_ignores_invalid():
    b = new_board("t")
    apply_command(b, {"op": "set_pitch", "area": "att_half"})
    assert b.pitch.area == "att_half"
    apply_command(b, {"op": "set_pitch", "area": "not_a_real_area"})
    assert b.pitch.area == "att_half"                    # unchanged; junk ignored


# ---------------------------------------------------------------- window geometry
def test_full_area_is_uncropped_window_none():
    b = new_board("t")
    assert area_window_display(b, vertical=False) is None
    assert area_window_display(b, vertical=True) is None


def test_att_half_window_horizontal_is_right_half():
    b = new_board("t"); b.pitch.area = "att_half"
    assert area_window_display(b, vertical=False) == (525.0, 0.0, 525.0, 680.0)


def test_att_half_window_vertical_maps_through_rotation():
    # landscape right half (525,0,525,680) -> portrait (_H-0-680, 525, 680, 525) = (0,525,680,525)
    b = new_board("t"); b.pitch.area = "att_half"
    assert area_window_display(b, vertical=True) == (0.0, 525.0, 680.0, 525.0)


def test_image_board_is_never_cropped():
    b = new_board("t", pitch_kind="image"); b.pitch.area = "att_third"
    assert area_window_display(b, vertical=False) is None


@pytest.mark.parametrize("area", [a for a in PITCH_AREAS if a != "full"])
def test_every_area_yields_a_window(area):
    b = new_board("t"); b.pitch.area = area
    assert area_window_display(b, vertical=False) is not None


# ---------------------------------------------------------------- SVG viewBox wiring
def test_full_viewbox_is_byte_identical():
    b = new_board("t")
    assert 'viewBox="0 0 1050.0 680.0"' in board_svg(b, 0)
    b.pitch.orientation = "vertical"
    assert 'viewBox="0 0 680.0 1050.0"' in board_svg(b, 0)


def test_area_crops_the_viewbox_but_keeps_rotation():
    b = new_board("t"); b.pitch.area = "att_half"
    assert 'viewBox="525.0 0.0 525.0 680.0"' in board_svg(b, 0)
    b.pitch.orientation = "vertical"
    svg = board_svg(b, 0)
    assert 'viewBox="0.0 525.0 680.0 525.0"' in svg
    assert "rotate(90)" in svg                            # vertical board still rotates


# ---------------------------------------------------------------- export honours the crop
def test_export_with_area_produces_a_tighter_png():
    if not export_render.available():
        pytest.skip("matplotlib unavailable")
    b = new_board("t")
    full = export_render.board_image(b, 0, fmt="png")
    b.pitch.area = "att_third"
    cropped = export_render.board_image(b, 0, fmt="png")
    assert full[:8] == b"\x89PNG\r\n\x1a\n" and cropped[:8] == b"\x89PNG\r\n\x1a\n"
    assert cropped != full                                # a different (cropped) image
