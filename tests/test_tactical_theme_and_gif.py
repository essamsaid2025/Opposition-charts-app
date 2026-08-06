"""Tactical Board Part 1 (theme colours) + Part 2 (animated GIF export).

Follows tests/test_tactical.py: build boards through the model/service, gate the
matplotlib-dependent bits on ``export_render.available()``. The single most
important assertion here is the backward-compat one - a board with no theme
selected resolves to byte-identical ``DEFAULT_COLORS``.
"""
import io
import os
import pathlib
import sys
import types

os.environ["FAP_TEST"] = "1"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pytest

from fap.tactical import apply_command, new_board
from fap.tactical.models import Frame
from fap.tactical.render import DEFAULT_COLORS
from fap.tactical.theme_colors import tactical_colors_from_theme
from fap.tactical.service import TacticalService
from fap.tactical import export_render
from fap.themes import ThemeManager
from fap.ui.builtin.tactical_board import _resolve_board_colors

THEMES = ThemeManager("assets/themes")
REAL_THEME_IDS = ("opta_light", "opta_dark", "hudl")


def _shell_with_themes(tm):
    services = types.SimpleNamespace(get=lambda name: tm if name == "themes" else None)
    return types.SimpleNamespace(platform=types.SimpleNamespace(services=services))


# ================================================================ Part 1: theme colours
@pytest.mark.parametrize("theme_id", REAL_THEME_IDS)
def test_mapping_is_complete_for_real_themes(theme_id):
    theme = THEMES.get(theme_id)
    colors = tactical_colors_from_theme(theme)
    # exactly the tactical roles, all present, all non-empty strings
    assert set(colors) == set(DEFAULT_COLORS)
    assert all(isinstance(v, str) and v.strip() for v in colors.values())
    # the two team colours come from the theme's accent pair
    assert colors["home"] == theme.colors["accent"]
    assert colors["away"] == theme.colors["accent_2"]
    assert colors["grass"] == theme.colors["pitch"]


def test_no_theme_selected_is_byte_identical_to_default():
    """CRITICAL backward-compat: a board with no theme in meta == today's palette."""
    board = new_board("plain")
    assert board.meta.get("theme") in (None, "")
    resolved = _resolve_board_colors(_shell_with_themes(THEMES), board)
    assert resolved == DEFAULT_COLORS                       # exact dict equality
    # and with no shell at all it still returns the default (never crashes)
    assert _resolve_board_colors(None, board) == DEFAULT_COLORS


def test_no_theme_export_bytes_match_todays_default():
    if not export_render.available():
        pytest.skip("matplotlib unavailable")
    board = new_board("plain")
    resolved = _resolve_board_colors(None, board)
    with_resolved = export_render.board_image(board, 0, fmt="png", colors=resolved)
    todays = export_render.board_image(board, 0, fmt="png")   # how it's called today (no colors)
    assert with_resolved == todays                           # byte-for-byte identical


def test_incomplete_or_malformed_theme_falls_back_per_key():
    # missing several keys -> those fall back to DEFAULT_COLORS, dict still complete
    partial = types.SimpleNamespace(colors={"pitch": "#123456", "accent": "#abcdef"})
    colors = tactical_colors_from_theme(partial)
    assert set(colors) == set(DEFAULT_COLORS)
    assert colors["grass"] == "#123456" and colors["home"] == "#abcdef"
    assert colors["cone"] == DEFAULT_COLORS["cone"]          # 'warning' absent -> default
    assert colors["mannequin"] == DEFAULT_COLORS["mannequin"]  # 'grey' absent -> default
    # malformed theme (colors is None / not a dict) must not crash
    assert set(tactical_colors_from_theme(types.SimpleNamespace(colors=None))) == set(DEFAULT_COLORS)
    assert set(tactical_colors_from_theme(object())) == set(DEFAULT_COLORS)


def test_selected_theme_is_applied_and_bad_theme_degrades():
    board = new_board("themed")
    board.meta["theme"] = "opta_dark"
    resolved = _resolve_board_colors(_shell_with_themes(THEMES), board)
    assert resolved != DEFAULT_COLORS
    assert resolved["grass"] == THEMES.get("opta_dark").colors["pitch"]
    # an unknown theme id degrades to the default palette, no crash
    board.meta["theme"] = "does_not_exist"
    assert _resolve_board_colors(_shell_with_themes(THEMES), board) == DEFAULT_COLORS


# ================================================================ Part 2: GIF export
def _multiframe_board(n=3):
    """A board whose frames actually DIFFER (a moving ball). Identical frames get
    merged by the GIF encoder, so a realistic animation moves something each frame."""
    b = new_board("anim")
    apply_command(b, {"op": "add_object", "frame": 0, "type": "ball",
                      "x": 10.0, "y": 50.0, "props": {}})
    ball_id = b.frames[0].objects[-1].id
    for k in range(1, n):
        apply_command(b, {"op": "add_frame", "from": k - 1})   # duplicate previous frame
        apply_command(b, {"op": "update_object", "frame": k, "id": ball_id,
                          "x": 10.0 + k * 20.0, "y": 50.0})     # move it so the frame differs
    return b


def _gif_frame_count(data: bytes) -> int:
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    return getattr(img, "n_frames", 1)


def test_board_gif_multi_frame():
    if not export_render.available():
        pytest.skip("matplotlib unavailable")
    b = _multiframe_board(3)
    gif = export_render.board_gif(b, dpi=60)
    assert gif[:6] in (b"GIF87a", b"GIF89a") and len(gif) > 100
    assert _gif_frame_count(gif) == 3


def test_board_gif_single_frame_is_valid():
    if not export_render.available():
        pytest.skip("matplotlib unavailable")
    b = new_board("solo")                                    # exactly one frame
    gif = export_render.board_gif(b, dpi=60)
    assert gif[:6] in (b"GIF87a", b"GIF89a")
    assert _gif_frame_count(gif) == 1                        # static but valid


def test_board_gif_uses_per_frame_duration():
    if not export_render.available():
        pytest.skip("matplotlib unavailable")
    b = _multiframe_board(2)
    b.frames[0].duration_ms = 200
    b.frames[1].duration_ms = 1500
    from PIL import Image
    img = Image.open(io.BytesIO(export_render.board_gif(b, dpi=60)))
    img.seek(0); first = img.info.get("duration")
    img.seek(1); second = img.info.get("duration")
    assert first == 200 and second == 1500


def test_gif_wired_into_service_export():
    if not export_render.available():
        pytest.skip("matplotlib unavailable")
    svc = TacticalService(None)
    assert "gif" in svc.export_formats()
    b = _multiframe_board(2)
    data, mime, fname = svc.export(b, 0, fmt="gif")
    assert mime == "image/gif" and data[:6] in (b"GIF87a", b"GIF89a") and fname.endswith(".gif")


def test_png_pdf_export_unaffected():
    """Regression: adding gif must not change PNG/PDF behaviour."""
    if not export_render.available():
        pytest.skip("matplotlib unavailable")
    svc = TacticalService(None)
    b = _multiframe_board(2)
    png, pmime, pfn = svc.export(b, 0, fmt="png")
    assert pmime == "image/png" and png[:8] == b"\x89PNG\r\n\x1a\n" and pfn.endswith(".png")
    pdf, dmime, dfn = svc.export(b, 0, fmt="pdf")
    assert dmime == "application/pdf" and pdf[:5] == b"%PDF-" and dfn.endswith(".pdf")


# ================================================================ model: Frame.duration_ms
def test_frame_duration_defaults_and_roundtrips():
    # old saved frame with NO duration_ms loads with the default (backward-compat)
    old = Frame.from_dict({"id": "f1", "name": "F1", "objects": []})
    assert old.duration_ms == 800
    # explicit value round-trips through to_dict/from_dict
    fr = Frame.from_dict({"id": "f2", "duration_ms": 1200, "objects": []})
    assert fr.duration_ms == 1200 and fr.to_dict()["duration_ms"] == 1200
    # garbage/non-positive falls back to the default, never crashes
    assert Frame.from_dict({"id": "f3", "duration_ms": "oops"}).duration_ms == 800
    assert Frame.from_dict({"id": "f4", "duration_ms": 0}).duration_ms == 800
    # a whole old board dict (frames without duration_ms) still loads
    b = new_board("t")
    d = b.to_dict()
    for f in d["frames"]:
        f.pop("duration_ms", None)
    from fap.tactical.models import Board
    assert Board.from_dict(d).frames[0].duration_ms == 800
