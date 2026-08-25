"""Custom-dashboard composition: lay out already-rendered chart PNGs on one grid
and export PNG/PDF. Pure image composition — reused by the Open Play Studio's
custom dashboard builder.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys
import pathlib
from io import BytesIO

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib.pyplot as plt

from fap.ui.components.dashboard_compose import compose_grid


def _png(color) -> bytes:
    fig = plt.figure(figsize=(2, 1.4))
    fig.add_subplot(111).scatter([1, 2, 3], [1, 2, 1], c=color)
    buf = BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    return buf.getvalue()


def test_compose_png_grid():
    items = [("Pass Map", _png("blue")), ("Shot Map", _png("red")),
             ("Heatmap", _png("green"))]
    out = compose_grid(items, title="My Dashboard", columns=2, fmt="png")
    assert out[:4] == b"\x89PNG" and len(out) > 1000       # a real PNG


def test_compose_pdf():
    out = compose_grid([("A", _png("blue")), ("B", _png("red"))], title="D", fmt="pdf")
    assert out[:4] == b"%PDF"


def test_empty_and_bad_panels():
    assert compose_grid([]) == b""
    assert compose_grid([("x", b"")]) == b""               # empty png filtered out
    # a bad PNG degrades to a placeholder panel, still produces a sheet
    out = compose_grid([("ok", _png("blue")), ("bad", b"not-a-png")], fmt="png")
    assert out[:4] == b"\x89PNG"


def test_columns_clamped():
    out = compose_grid([("A", _png("blue"))], columns=9, fmt="png")   # clamps to 3
    assert out[:4] == b"\x89PNG"


def test_studio_registers_dashboard_panel():
    from fap.ui.builtin.openplay_studio import PANELS
    ids = [p[0] for p in PANELS["bottom"]]
    assert "dashboard" in ids and "match_stats" in ids
