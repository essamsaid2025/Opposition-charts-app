"""Phase S1 stabilization regression guards for the Open Play app (app.py).

These lock in the fixes made during the S1 release so they can't silently
regress: import validation before default-fill, transparent export, and a
representative 'plugins actually draw data' check. Heavy full-matrix output
validation lives in tests/deep_validate.py (run as a script).
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import pytest
import app


@pytest.fixture(autouse=True)
def _close_figs():
    yield
    plt.close("all")


def _df(n=200):
    rng = np.random.default_rng(7)
    x = rng.uniform(0, 100, n); y = rng.uniform(0, 100, n)
    return pd.DataFrame({
        "event_type": rng.choice(["pass", "shot", "carry", "tackle"], n),
        "x": x, "y": y, "x2": np.clip(x + rng.normal(10, 8, n), 0, 100),
        "y2": np.clip(y + rng.normal(0, 8, n), 0, 100),
        "outcome": rng.choice(["successful", "unsuccessful"], n),
        "team": "A", "player": rng.choice(["P1", "P2", "P3"], n),
    })


def _prep(raw, spec=None):
    spec = spec or app.PitchSpec()
    d = app.add_derived_columns(app.normalize_coordinates(app.ensure_columns(raw), "0-100"))
    return app.apply_pitch_transforms(d, spec)


# ---- §14: validation runs on real columns, before defaults are filled ----
def test_missing_event_type_is_flagged():
    problems = app.validate_data(app.clean_columns(pd.DataFrame({"x": [1], "y": [2]})))
    assert any("event_type" in p for p in problems)


def test_missing_xy_is_flagged():
    problems = app.validate_data(app.clean_columns(pd.DataFrame({"event_type": ["pass"]})))
    assert any("x" in p and "y" in p for p in problems)


def test_complete_file_passes_validation():
    problems = app.validate_data(app.clean_columns(
        pd.DataFrame({"event_type": ["pass"], "x": [1], "y": [2]})))
    assert problems == []


# ---- §2/§3: import pipeline survives messy input without crashing ----
@pytest.mark.parametrize("raw,mode", [
    (pd.DataFrame({"event_type": ["pass"], "x": ["bad"], "y": ["worse"]}), "0-100"),
    (pd.DataFrame({" Event Type ": ["PASS"], "X": [10], "Y ": [50]}), "0-100"),
    (pd.DataFrame({"event_type": ["pass"], "x": [120], "y": [80]}), "120 x 80"),
    (pd.DataFrame({"event_type": ["pass", "carry"], "x": [np.nan, 30], "y": [np.nan, 60]}), "0-100"),
])
def test_import_pipeline_robust(raw, mode):
    d = app.add_derived_columns(app.normalize_coordinates(app.ensure_columns(raw), mode))
    d = app.apply_pitch_transforms(d, app.PitchSpec())
    assert len(d) == len(raw)
    # coordinates never exceed the pitch frame
    assert d["x"].dropna().between(0, 100).all()
    assert d["y"].dropna().between(0, 100).all()


# ---- §12: transparent export works and differs from opaque ----
@pytest.mark.parametrize("fmt", ["png", "svg", "pdf"])
def test_transparent_export_differs(fmt):
    df = _prep(_df())
    fig, ax = app.new_pitch_fig(dict(app.VIZ_THEMES["Opta Analyst"]), app.PitchSpec(), {"label_size": 11})
    opaque = app.fig_to_bytes(fig, fmt=fmt, dpi=110, transparent=False)
    trans = app.fig_to_bytes(fig, fmt=fmt, dpi=110, transparent=True)
    assert len(opaque) > 500 and len(trans) > 500
    assert opaque != trans


def test_transparent_png_has_alpha():
    from io import BytesIO
    from PIL import Image
    fig, ax = app.new_pitch_fig(dict(app.VIZ_THEMES["Opta Analyst"]), app.PitchSpec(), {"label_size": 11})
    data = app.fig_to_bytes(fig, fmt="png", dpi=110, transparent=True)
    alpha = np.array(Image.open(BytesIO(data)).convert("RGBA"))[:, :, 3]
    assert alpha.min() == 0  # genuinely transparent pixels exist


# ---- §4: a representative plugin renders non-empty output ----
def _render_arr(name, df, ctx):
    fig = app.VIZ_REGISTRY[name]["render"](df, ctx)
    fig.canvas.draw()
    w, h = fig.canvas.get_width_height()
    arr = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8).reshape(h, w, 4)[:, :, :3].astype(np.int16).copy()
    plt.close(fig)
    return arr


def _ctx(spec, df):
    vt = dict(app.VIZ_THEMES["Opta Analyst"])
    return {"vt": vt, "spec": spec, "title": "T", "show_title": True, "title_size": 20,
            "label_size": 11, "legend_size": 10, "respect_filter": False,
            "marker": {"shape": "Circle", "size": 80, "edge_width": 1.1, "edge_color": vt["line"],
                       "alpha": 0.85, "rotation": 45, "jitter": 0.3, "zorder": 6, "shadow": True,
                       "glow": True, "glow_color": vt["accent"]},
            "arrow": {"kind": "Straight", "width": 1.6, "head": 10, "curvature": 0.18, "alpha": 0.72,
                      "linecap": "round", "shadow": False, "glow": False, "cmap": "viridis"},
            "labels": {"show": True, "show_players": True, "smart": True, "hide_overlapping": True,
                       "halo": True, "halo_color": vt["pitch"], "box": False, "leader_lines": True,
                       "size": 9, "offset": 1.6, "rotation": 0, "max_labels": 25},
            "legend": {"show": True, "position": "Bottom", "orientation": "Horizontal", "frame": True,
                       "title": "", "renames": "", "hide": "", "order": ""},
            "heat": {"type": "Gaussian KDE", "preset": "All selected events", "cmap": "Greens",
                     "alpha": 0.65, "bandwidth": 3.0, "levels": 10, "bins": 13, "gridsize": 22,
                     "cell_size": 10, "interpolation": "bilinear", "normalization": "Count",
                     "threshold": 0, "percentile_scale": False, "log_scale": False, "cell_labels": True},
            "colors": {k: vt["accent"] for k in ["arrow", "unsuccess", "start", "end", "shot", "goal",
                                                 "zone", "bar", "line", "trend", "carry", "cross"]},
            "aux": {"df_all": df, "top_n": 8, "zone_mode": "Pitch Thirds", "start_end_event": "pass",
                    "timeline_focus": "All", "trend_metric": "Shots", "sequence_mode": "Longest sequence",
                    "sequence_id": "S1", "show_sequence_numbers": True, "line_width": 2.4,
                    "dashboard_layout": None}}


@pytest.mark.parametrize("name", ["Pass Map", "Shot Map", "Heatmap Studio", "Defensive Actions Map"])
def test_plugin_draws_data_not_blank(name):
    spec = app.PitchSpec()
    df = _prep(_df())
    empty = df.iloc[0:0]
    cfull = _ctx(spec, df)
    cempty = _ctx(spec, empty); cempty["aux"]["df_all"] = empty
    a = _render_arr(name, df, cfull)
    b = _render_arr(name, empty, cempty)
    h = min(a.shape[0], b.shape[0]); w = min(a.shape[1], b.shape[1])
    diff = float(np.mean(np.any(np.abs(a[:h, :w] - b[:h, :w]) > 10, axis=2)))
    assert diff > 0.004, f"{name} render looks identical with and without data (diff={diff:.4f})"
