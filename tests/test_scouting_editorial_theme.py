"""Phase C — 'The Athletic — Editorial' Scouting chart theme (additive asset).

Locks: the editorial theme loads with all REQUIRED colours, is a LIGHT theme with an
ORANGE accent, renders the scouting-native charts, and — critically — adds itself WITHOUT
disturbing any existing theme (global app theme / Open Play themes untouched).
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")
import pandas as pd

from fap.themes.theme import REQUIRED_COLORS, ThemeManager
from fap.scouting import charts, viz

_ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets" / "themes"


def _tm():
    return ThemeManager(_ASSETS)


def test_editorial_theme_loads_light_and_orange():
    t = _tm().get("athletic_editorial")
    assert t.name and getattr(t, "dark", True) is False          # a LIGHT theme
    for c in REQUIRED_COLORS:
        assert c in t.colors                                     # complete palette (else it wouldn't build)
    assert t.colors["accent"].lower() == "#e8552b"               # the editorial orange
    assert t.colors["bg"].lower() in ("#f7f5f0", "#faf8f3")      # warm off-white ground


def test_existing_themes_still_present():
    ids = set(_tm().ids())
    for e in ("opta_dark", "opta_light", "hudl", "athletic", "light", "dark"):
        assert e in ids                                          # nothing removed/renamed


def _view():
    n = 16
    frame = pd.DataFrame({"player": [f"P{i}" for i in range(n)],
                          "passes": [5 + i for i in range(n)],
                          "tackles": [i % 6 for i in range(n)],
                          "goals": [i % 4 for i in range(n)]})
    schema = {"id_field": "player", "value_scale": viz.SCALE_RAW, "dimensions": {},
              "metrics": [{"source": "passes"}, {"source": "tackles"}, {"source": "goals"}]}
    return viz.build_view(frame, schema, ["P8"], dataset_name="Set")


def test_scouting_charts_render_with_editorial_theme():
    t = _tm().get("athletic_editorial")
    view = _view()
    for ct in ("bar", "percentile_bar", "radar"):
        fig = charts.render(ct, view, t, {"metrics": ["passes", "tackles", "goals"]})
        assert fig is not None                                   # renders through the EXISTING engine
