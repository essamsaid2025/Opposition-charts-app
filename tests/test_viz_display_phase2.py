"""Phase 2 — strict capability-gated display controls in fap.visuals + Set Pieces.

Verifies the whole chain the upgrade promises, at the layer-composition level (fast
and precise): builders DECLARE capabilities that match their real rendering; the UI
would gate strictly on them; and the renderer HONOURS each toggle (values/xG/xG
values/outcome/density/percentages) WITHOUT ever changing the underlying data.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
from matplotlib.figure import Figure

from fap.visuals.base import load_builtin_visuals
from fap.visuals.context import LayerContext
from fap.visuals.display import display_controls_for
from fap.visuals.legend import LegendEngine
from fap.visuals.maps import _builders as B
from fap.visuals.pitch import get_spec
from fap.visuals.tokens import StyleTokens

load_builtin_visuals()
from fap.themes.theme import ThemeManager

_THEME = ThemeManager("assets/themes").get("opta_dark")


def _lctx(df: pd.DataFrame, controls: dict) -> LayerContext:
    fig = Figure()
    ax = fig.add_subplot(111)
    return LayerContext(fig=fig, ax=ax, df=df, theme=_THEME,
                        tokens=StyleTokens.from_theme(_THEME), controls=controls,
                        pitch_spec=get_spec("uefa"), legend=LegendEngine())


def _shot_df() -> pd.DataFrame:
    return pd.DataFrame({
        "event_type": ["shot"] * 4, "x": [80, 85, 90, 88], "y": [40, 45, 50, 30],
        "xg": [0.12, 0.34, 0.55, 0.08], "outcome": ["goal", "off_t", "saved", "blocked"],
        "player": ["A", "B", "C", "D"]})


def _pass_df() -> pd.DataFrame:
    return pd.DataFrame({
        "event_type": ["pass"] * 3, "x": [20, 40, 60], "y": [10, 30, 50],
        "end_x": [40, 60, 80], "end_y": [20, 40, 60],
        "outcome": ["successful", "unsuccessful", "successful"], "player": ["A", "B", "C"]})


def _layer_ids(layers) -> list[str]:
    return [l.info.id for l in layers]


# ================================================================ capability declarations
def test_shot_map_declares_xg_capabilities():
    cls = B.scatter_map("t2_shot", "Shot Map", lambda df, c: df, category="Shooting",
                        sized_by="xg")
    caps = cls.capabilities
    assert caps.xg and caps.xg_values and caps.player_names and caps.legend
    keys = {c.key for c in display_controls_for(caps)}
    assert {"show_xg", "show_xg_values", "show_player_names", "legend"} <= keys


def test_pass_map_has_no_xg_capabilities():
    cls = B.arrow_map("t2_pass", "Pass Map", lambda df, c: df, category="Passing")
    caps = cls.capabilities
    assert caps.outcome and caps.player_names and caps.legend
    keys = {c.key for c in display_controls_for(caps)}
    assert "show_xg" not in keys and "show_xg_values" not in keys      # strict gate
    assert "show_outcome" in keys


def test_density_and_chart_and_zone_capabilities():
    dens = B.density_map("t2_dens", "Heatmap", lambda df, c: df, category="Defensive")
    assert dens.capabilities.density and not dens.capabilities.legend
    ch = B.chart("t2_chart", "Bar", lambda ctx, ax: None, category="Team")
    assert ch.capabilities.grid and ch.capabilities.axes and ch.capabilities.legend
    assert ch.display_defaults == {"show_grid": True, "show_axes": True}
    zone = B.zone_map("t2_zone", "Zones", ((66.6, 0, 100, 100),), category="Zones")
    assert zone.capabilities.zones and zone.capabilities.percentages


# ================================================================ renderer honours toggles
def test_show_xg_gates_size_encoding_only():
    cls = B.scatter_map("t2_shot2", "Shot Map", lambda df, c: df, category="Shooting",
                        sized_by="xg")
    df = _shot_df()
    on = cls().layers(_lctx(df, {"show_xg": True}))
    off = cls().layers(_lctx(df, {"show_xg": False}))
    scat_on = next(l for l in on if l.info.id == "scatter")
    scat_off = next(l for l in off if l.info.id == "scatter")
    assert scat_on.params.get("sizes") is not None          # xG encoded as size
    assert scat_off.params.get("sizes") is None             # encoding removed
    # data integrity: the xG column is untouched by either toggle
    assert list(df["xg"]) == [0.12, 0.34, 0.55, 0.08]


def test_show_xg_values_toggles_numeric_labels_independently():
    cls = B.scatter_map("t2_shot3", "Shot Map", lambda df, c: df, category="Shooting",
                        sized_by="xg")
    df = _shot_df()
    with_vals = cls().layers(_lctx(df, {"show_xg": False, "show_xg_values": True}))
    without = cls().layers(_lctx(df, {"show_xg": True, "show_xg_values": False}))
    vl = [l for l in with_vals if l.info.id == "value_labels"]
    assert vl and vl[0].params.get("column") == "xg"        # xG numbers shown, xG encoding off
    assert not any(l.info.id == "value_labels" for l in without)


def test_show_outcome_gates_split_and_legend():
    cls = B.arrow_map("t2_pass2", "Pass Map", lambda df, c: df, category="Passing")
    df = _pass_df()
    split = cls().layers(_lctx(df, {"show_outcome": True}))
    single = cls().layers(_lctx(df, {"show_outcome": False}))
    labels_split = {l.params.get("label") for l in split if l.info.id == "arrows"}
    labels_single = {l.params.get("label") for l in single if l.info.id == "arrows"}
    assert "Successful" in labels_split and "Unsuccessful" in labels_split
    # outcome off -> single series, no misleading Successful/Unsuccessful legend entries
    assert labels_single == {"Pass Map"}


def test_show_player_names_gates_labels():
    cls = B.scatter_map("t2_shot4", "Shot Map", lambda df, c: df, category="Shooting",
                        sized_by="xg")
    df = _shot_df()
    on = cls().layers(_lctx(df, {"show_player_names": True}))
    off = cls().layers(_lctx(df, {}))
    assert any(l.info.id == "labels" for l in on)
    assert not any(l.info.id == "labels" for l in off)      # default: no player names


def test_show_density_removes_encoding():
    cls = B.density_map("t2_dens2", "Heatmap", lambda df, c: df, category="Defensive")
    df = _shot_df()
    assert cls().layers(_lctx(df, {"show_density": True})) != []
    assert cls().layers(_lctx(df, {"show_density": False})) == []


def test_show_percentages_gates_zone_labels():
    cls = B.zone_map("t2_zone2", "Final Third", ((66.6, 0, 100, 100),),
                     category="Zones", selector=lambda df, c: df)
    df = _shot_df()
    with_pct = cls().layers(_lctx(df, {"show_percentages": True, "show_zone_overlay": True}))
    no_pct = cls().layers(_lctx(df, {"show_percentages": False, "show_zone_overlay": True}))
    zones_with = next(l for l in with_pct if l.info.id == "zones").params["zones"]
    zones_without = next(l for l in no_pct if l.info.id == "zones").params["zones"]
    assert any(z[5] is not None for z in zones_with)        # % values present
    assert all(z[5] is None for z in zones_without)         # % values hidden


def test_frame_axes_honours_show_axes():
    df = _shot_df()
    ctx = _lctx(df, {"show_axes": False, "show_grid": False})
    B._frame_axes(ctx)
    assert list(ctx.ax.get_xticks()) == [] and list(ctx.ax.get_yticks()) == []


# ================================================================ note fields
def test_note_fields_are_declared_not_every_column():
    from fap.ui.components.viz_workspace import note_fields_for
    cls = B.scatter_map("t2_shot5", "Shot Map", lambda df, c: df, category="Shooting",
                        sized_by="xg")
    fields = note_fields_for(cls(), _shot_df())
    assert "x" in fields and "y" in fields and "xg" in fields   # requires + xG capability
    assert "player" not in fields                               # not consumed as a field


# ================================================================ default preservation
def test_defaults_reproduce_current_output_for_builders():
    # with no controls set, a pass map still splits by outcome (current behaviour) and a
    # shot map still encodes xG by size — i.e. the new system changes nothing by default.
    pass_cls = B.arrow_map("t2_pass3", "Pass Map", lambda df, c: df, category="Passing")
    dflt = pass_cls().layers(_lctx(_pass_df(), {}))
    assert "Successful" in {l.params.get("label") for l in dflt if l.info.id == "arrows"}
    shot_cls = B.scatter_map("t2_shot6", "Shot Map", lambda df, c: df, category="Shooting",
                             sized_by="xg")
    scat = next(l for l in shot_cls().layers(_lctx(_shot_df(), {})) if l.info.id == "scatter")
    assert scat.params.get("sizes") is not None
