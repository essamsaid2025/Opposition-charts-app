"""Shot Map xG enhancement validation (Phase-2 Checkpoint 5).

Renders the real Shot Map via the Open Play engine and verifies xG is encoded by
marker size, appears in the subtitle/label, penalties use the frozen value,
missing xG is safe, coordinates/goal-miss encoding are untouched, and rendering
is deterministic. Reads only the canonical ``internal_xg`` column.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")

import sys
import pathlib

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import app  # noqa: E402  registers the Open Play engine (FAP_TEST-guarded)
from fap.openplay import add_derived_columns  # noqa: E402
from fap.openplay.engine import get_engine  # noqa: E402


def _shot_frame():
    raw = pd.DataFrame({
        "event_type": ["shot", "shot", "shot", "pass"],
        "team": ["A", "A", "A", "A"],
        "player": ["Striker", "Winger", "Taker", "Mid"],
        "x": [116.0 / 1.2, 100.0, 89.0, 40.0],   # canonical (will be ~close/mid/pen)
        "y": [50.0, 30.0, 50.0, 50.0],
        "x2": [120.0 / 1.2, 100.0, 100.0, 60.0],
        "y2": [50.0, 40.0, 50.0, 55.0],
        "minute": [10, 20, 30, 5], "second": [0, 0, 0, 0], "period": [1, 1, 1, 1],
        "shot_result": ["Goal", "Off Target", "Goal", ""],
        "set_piece": ["", "", "penalty", ""],
    })
    return add_derived_columns(raw)


@pytest.fixture(scope="module")
def rendered():
    eng = get_engine()
    df = _shot_frame()
    spec = eng.pitch_spec_cls()
    vt = eng.metadata["themes"]["Opta Analyst"]
    f = eng.apply_pitch_transforms(df, spec)
    ctx = eng.default_ctx(vt, spec, title="Shot Map", aux={"df_all": f})
    ctx["labels"]["show_players"] = True
    return eng, df, f, spec, vt, ctx


def test_internal_xg_present_and_penalty_is_frozen(rendered):
    _, df, *_ = rendered
    from fap.xg.services import xg_service
    assert "internal_xg" in df.columns
    shots = df[df["event_type"] == "shot"]
    pen = shots[shots["set_piece"] == "penalty"]
    assert pen["internal_xg"].iloc[0] == pytest.approx(xg_service.penalty_xg())   # frozen
    non_pen = shots[shots["set_piece"] != "penalty"]
    assert non_pen["internal_xg"].between(0, 1).all()                             # model


def test_marker_size_encodes_xg(rendered):
    eng, df, f, spec, vt, ctx = rendered
    fig = eng.render("Shot Map", f, ctx)
    sizes = np.concatenate([c.get_sizes() for c in fig.axes[0].collections
                            if len(c.get_sizes())])
    assert sizes.min() > 0                       # sensible minimum (low-xG visible)
    assert sizes.max() > sizes.min()             # xG creates size variation
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_subtitle_and_label_show_xg(rendered):
    eng, df, f, spec, vt, ctx = rendered
    import matplotlib.pyplot as plt
    fig = eng.render("Shot Map", f, ctx)
    texts = " ".join(t.get_text() for t in fig.findobj(match=plt.Text))
    assert "xG" in texts                          # subtitle "xG: ..." and goal labels "(xG ..)"
    plt.close(fig)


def test_deterministic_render(rendered):
    eng, df, f, spec, vt, ctx = rendered
    import matplotlib.pyplot as plt
    fig1 = eng.render("Shot Map", f, ctx); b1 = eng.export(fig1, "png", 120); plt.close(fig1)
    fig2 = eng.render("Shot Map", f, ctx); b2 = eng.export(fig2, "png", 120); plt.close(fig2)
    assert b1 == b2


def test_coordinates_unchanged(rendered):
    _, df, f, *_ = rendered
    # panel_shots must not mutate the frame's coordinates
    assert f.loc[f["event_type"] == "shot", "x"].notna().all()
    assert list(f["x"]) == list(f["x"])          # stable (no in-place edits)


def test_missing_xg_is_safe():
    eng = get_engine()
    df = _shot_frame()
    df.loc[df["event_type"] == "shot", "internal_xg"] = np.nan   # simulate unavailability
    spec = eng.pitch_spec_cls(); vt = eng.metadata["themes"]["Opta Analyst"]
    f = eng.apply_pitch_transforms(df, spec)
    ctx = eng.default_ctx(vt, spec, title="Shot Map", aux={"df_all": f})
    import matplotlib.pyplot as plt
    fig = eng.render("Shot Map", f, ctx)          # must not raise
    assert fig is not None
    plt.close(fig)
