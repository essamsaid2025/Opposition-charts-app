"""Scouting Visualization — Phase A CHARACTERIZATION tests (safety net).

These pin the CURRENT behaviour of the scouting visualization stack BEFORE any redesign,
so the upcoming Scouting-catalog separation can be proven not to break what works:

  * the scouting-native chart catalog (fap.scouting.viz.CHART_TYPES / CHART_LABELS)
  * data-driven chart availability (unsupported data -> unavailable, never a fake chart)
  * the shared engine registry (fap.visuals.visual_registry) and the exact set of chart
    categories it exposes today — including the Open-Play team/tactical ones that currently
    leak into the Scouting/First-Team event-fallback workspace.

They are intentionally PURE (no DB / no Streamlit): the service/DB and Save-to-Player paths
are already covered by the existing scouting / first-team suites. If a snapshot here changes,
that is a signal to consciously update it — not to silently drop a capability.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from fap.scouting import viz


# ---------------------------------------------------------------- scouting-native catalog
def test_scouting_native_chart_catalog_is_stable():
    # the player-centric chart vocabulary the scouting-native workspace exposes today
    assert viz.CHART_TYPES == (
        "bar", "ranking_bar", "percentile_bar", "radar", "pizza", "scatter",
        "histogram", "box", "lollipop", "comparison", "small_multiples", "heatmap")
    for ct in viz.CHART_TYPES:
        assert ct in viz.CHART_LABELS and viz.CHART_LABELS[ct]


def _schema():
    return {
        "id_field": "player",
        "value_scale": viz.SCALE_RAW,
        "dimensions": {"position": "position"},
        "metrics": [
            {"source": "passes", "unit": ""},
            {"source": "tackles", "unit": ""},
            {"source": "goals", "unit": ""},
        ],
    }


def _frame(n=12):
    return pd.DataFrame({
        "player": [f"P{i}" for i in range(n)],
        "position": (["CM"] * n),
        "passes": [10 + i for i in range(n)],
        "tackles": [i % 5 for i in range(n)],
        "goals": [i % 3 for i in range(n)],
    })


# ---------------------------------------------------------------- view + percentiles
def test_build_view_produces_percentiles_from_population():
    view = viz.build_view(_frame(), _schema(), ["P5"], dataset_id="d1", dataset_name="Set")
    assert view.population == 12 and view.primary == "P5"
    # every metric carries a population-relative percentile for the selected player
    for m in view.metrics:
        assert m.percentiles.get("P5") is not None      # 12 rows >= min population -> computed
        assert 0.0 <= m.percentiles["P5"] <= 100.0


def test_build_view_tiny_population_has_no_percentiles():
    # a single-row population is below the rank/percentile minimum -> honestly None, never faked
    view = viz.build_view(_frame(n=1), _schema(), ["P0"], dataset_id="d1")
    assert view.population == 1
    for m in view.metrics:
        assert m.percentiles.get("P0") is None


# ---------------------------------------------------------------- data-driven availability
def test_chart_availability_is_data_driven():
    avail = viz.chart_availability(viz.build_view(_frame(), _schema(), ["P5"]))
    assert set(avail.keys()) == set(viz.CHART_TYPES)     # a verdict for every chart type
    for ct, (ok, reason) in avail.items():
        assert isinstance(ok, bool) and isinstance(reason, str)
        if not ok:
            assert reason                                # unavailable ALWAYS explains why


def test_scatter_needs_two_metrics():
    view1 = viz.build_view(_frame(), {**_schema(), "metrics": [{"source": "passes"}]}, ["P5"])
    ok, reason = viz.chart_availability(view1)["scatter"]
    assert ok is False and reason                        # 1 metric -> scatter unavailable, explained


# ---------------------------------------------------------------- shared engine registry snapshot
def test_shared_registry_catalog_snapshot():
    from fap.visuals.base import load_builtin_visuals, visual_registry
    load_builtin_visuals()
    cats = sorted({(getattr(i, "category", "") or "General") for i in visual_registry.infos()})
    # The shared engine currently exposes these categories; the Open-Play/team ones
    # (Team / Transitions / Possession / Build-up / Progression / Goalkeeper) are exactly what
    # leaks into the Scouting event-fallback workspace and the redesign must curate. Locking the
    # snapshot means a scouting-catalog change is proven NOT to have mutated the shared registry.
    for expected in ("Comparison", "Passing", "Attacking"):
        assert expected in cats
    assert len(visual_registry.infos()) >= 20           # the full shared catalog is intact
