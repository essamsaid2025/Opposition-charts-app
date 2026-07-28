"""Phase 13 - Player Visualization Workspace (additive, reuse-only).

Proves the shared workspace drives the EXISTING engine end to end: the visual
registry -> Renderer -> ExportEngine -> FilterSet, over a player event frame - and
that its catalog/favorites/signature helpers behave. It creates no chart builder,
no theme, no filter, no exporter and no dataframe of its own.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd

from fap.core.types import RenderContext
from fap.exports.base import load_builtin_exporters
from fap.openplay.transforms import add_derived_columns
from fap.pipeline import schema
from fap.pipeline.filters import FilterSet
from fap.themes.theme import REQUIRED_COLORS, Theme
from fap.ui.components import viz_workspace as W
from fap.visuals.base import load_builtin_visuals, visual_registry
from fap.visuals.export import ExportEngine
from fap.visuals.renderer import Renderer

load_builtin_visuals()
load_builtin_exporters()


def _theme() -> Theme:
    colors = {c: "#888888" for c in REQUIRED_COLORS}
    colors.update(bg="#0b0e14", pitch="#1b7a3a", text="#ffffff", accent="#e07b2b")
    return Theme(id="test", name="Test", dark=True, colors=colors)


def _frame() -> pd.DataFrame:
    n, rng = 40, np.random.default_rng(0)
    df = pd.DataFrame({
        "event_type": (["pass"] * 18 + ["carry"] * 8 + ["shot"] * 6 + ["cross"] * 4 + ["dribble"] * 4),
        "x": rng.uniform(5, 95, n), "y": rng.uniform(5, 95, n),
        "end_x": rng.uniform(5, 99, n), "end_y": rng.uniform(5, 95, n),
        "team": ["Home"] * n, "opponent": ["Away"] * n, "player": ["Salah"] * n,
        "minute": rng.integers(1, 90, n), "second": [0] * n, "period": [1] * n, "match_id": ["M1"] * n,
        "outcome": (["successful"] * 30 + ["unsuccessful"] * 10)})
    return add_derived_columns(schema.coerce_schema(df))


def test_catalog_from_registry_grouped():
    cat = W._catalog(visual_registry)
    assert len(cat) >= 10
    assert all({"id", "name", "category"} <= set(v) for v in cat)
    assert len({v["category"] for v in cat}) >= 3


def test_signature_is_deterministic_and_sensitive():
    filt = FilterSet()
    fr = pd.DataFrame({"x": [1]})
    a = W._signature("viz", {"t": 1}, filt, "opta_light", fr)
    assert a == W._signature("viz", {"t": 1}, filt, "opta_light", fr)
    assert a != W._signature("other", {"t": 1}, filt, "opta_light", fr)


def test_render_and_export_through_existing_engine():
    theme, frame = _theme(), _frame()
    renderer, export = Renderer(None), ExportEngine()
    rendered, exported = 0, {"png": 0, "svg": 0, "pdf": 0}
    for info in W._catalog(visual_registry)[:14]:
        try:
            viz = visual_registry.create(info["id"])
            ctx = RenderContext(df=frame, theme=theme, controls={"title": "Salah"},
                                meta={"filters": FilterSet(event_types=("pass", "carry"))})
            fig = renderer.render(viz, ctx)
        except Exception:
            continue
        rendered += 1
        for fmt in ("png", "svg", "pdf"):
            try:
                if export.export(fig, "Salah", fmt=fmt).data:
                    exported[fmt] += 1
            except Exception:
                pass
        matplotlib.pyplot.close(fig)
    assert rendered >= 3
    assert exported["png"] >= 3 and exported["svg"] >= 3 and exported["pdf"] >= 3


def test_renderer_applies_filterset():
    frame = _frame()
    only_shots = Renderer(None)._apply_filters(frame, FilterSet(event_types=("shot",)))
    assert len(only_shots) == 6


def test_favorites_are_metadata_only(tmp_path):
    from dataclasses import replace
    from fap.config.settings import AppSettings, CacheSettings, DatabaseSettings, StorageSettings
    from fap.bootstrap import init_platform
    from fap.identity.models import User
    from fap.identity.roles import Role
    settings = replace(AppSettings(environment="development"), user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))
    platform = init_platform(settings=settings)
    wm = platform.workspace_manager
    user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
    try:
        wm.autosave(user, {"viz_ids": ["heatmap", "passmap"]}, scope="viz_favorites")
        got = (wm.load_autosave(user, scope="viz_favorites") or {}).get("viz_ids", [])
        assert got == ["heatmap", "passmap"]
    finally:
        platform.db.close()
