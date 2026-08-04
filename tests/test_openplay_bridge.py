"""Bridge between the newer plugin registry (``fap.visuals.base.visual_registry``)
and the legacy Open Play ``VIZ_REGISTRY`` (app.py).

Proves that after the bridge runs at engine registration every ``fap.visuals``
plugin — in particular the four ``comparisons.py`` Comparison charts — is exposed
through the legacy registry the Open Play Studio reads, with the right category,
that a bridged renderer produces a real Figure on the sample dataset through the
plugin's own ``.render`` (no duplicated drawing), and that the collision policy
(skip, prefer the existing legacy entry) makes the bridge idempotent.

``import app`` is allowed HERE only (FAP_TEST-guarded); the Studio never imports app.
"""
import os
import pathlib
import sys

os.environ["FAP_TEST"] = "1"
_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))                    # app.py
sys.path.insert(0, str(_ROOT / "src"))

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pytest
from matplotlib.figure import Figure

import app  # noqa: E402  (FAP_TEST-guarded; runs the bridge at import)
from fap.openplay.engine import default_ctx, get_engine  # noqa: E402
from fap.openplay.transforms import add_derived_columns  # noqa: E402
from fap.pipeline import schema  # noqa: E402

# name -> expected category, straight from src/fap/visuals/charts/comparisons.py
COMPARISON_CHARTS = {
    "Player Percentile Radar": "Comparison",
    "Player Comparison Bars": "Comparison",
    "Team Radar (Opponent Scouting)": "Comparison",
    "Rolling Form Trend": "Comparison",
}


def _sample_frame() -> pd.DataFrame:
    raw = pd.read_csv("data/sample_open_play_data.csv")
    return add_derived_columns(schema.coerce_schema(raw))


def _legacy_ctx() -> dict:
    """A legacy ctx dict exactly like the Studio/run_app build one."""
    vt = app.VIZ_THEMES["Opta Analyst"]
    return default_ctx(vt, app.PitchSpec())


# ---------------------------------------------------------------- registration
@pytest.mark.parametrize("name,category", list(COMPARISON_CHARTS.items()))
def test_comparison_charts_bridged_into_legacy_registry(name, category):
    assert name in app.VIZ_REGISTRY, f"{name} not bridged into VIZ_REGISTRY"
    entry = app.VIZ_REGISTRY[name]
    assert entry["category"] == category
    assert entry["uses_pitch"] is False               # charts are non-pitch
    assert callable(entry["render"])


def test_engine_exposes_bridged_charts_and_category():
    engine = get_engine()
    assert engine is not None
    names = set(engine.viz_names())
    assert set(COMPARISON_CHARTS) <= names
    assert "Comparison" in engine.categories()
    # category filtering surfaces exactly the comparison charts registered here
    assert set(COMPARISON_CHARTS) <= set(engine.viz_names("Comparison"))


# ---------------------------------------------------------------- rendering
@pytest.mark.parametrize("name", list(COMPARISON_CHARTS))
def test_bridged_renderer_returns_figure_on_sample_data(name):
    renderer = app.VIZ_REGISTRY[name]["render"]
    fig = renderer(_sample_frame(), _legacy_ctx())
    assert isinstance(fig, Figure)
    assert fig.axes                                   # produced a drawable figure
    plt.close(fig)


def test_bridged_renderer_survives_empty_frame():
    empty = schema.coerce_schema(pd.DataFrame({"event_type": [], "x": [], "y": []}))
    for name in COMPARISON_CHARTS:
        fig = app.VIZ_REGISTRY[name]["render"](empty, _legacy_ctx())
        assert isinstance(fig, Figure)
        plt.close(fig)


# ---------------------------------------------------------------- collision / idempotency
def test_bridge_is_idempotent_and_skips_collisions():
    before = dict(app.VIZ_REGISTRY)
    added = app._bridge_plugin_registry_into(app.VIZ_REGISTRY)
    # everything is already present from the import-time bridge, so a re-run adds nothing
    assert added == []
    assert set(app.VIZ_REGISTRY) == set(before)


def test_theme_translation_maps_legacy_vt_keys():
    vt = app.VIZ_THEMES["StatsBomb"]
    theme = app._theme_from_legacy_vt(vt)
    # required renames and bar fallback are honoured; all REQUIRED_COLORS present
    from fap.themes.theme import REQUIRED_COLORS
    assert set(REQUIRED_COLORS) <= set(theme.colors)
    assert theme.colors["lines"] == vt["line"]
    assert theme.colors["accent_2"] == vt["accent2"]
    assert theme.colors["bar"] == vt["accent"]        # legacy vt has no bar role
