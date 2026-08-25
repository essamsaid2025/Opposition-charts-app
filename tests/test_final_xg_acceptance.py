"""FINAL ACCEPTANCE — end-to-end xG consistency across every user-facing surface.

Verification only: the reference xG/NPxG are computed DIRECTLY from the canonical
shot-level ``internal_xg`` column, then every surface (Match Stats, compute_metrics
/ KPI, Shot Map subtitle, team-level aggregation) must equal them within
floating-point tolerance. Data carries NO provider xG. Includes a penalty.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")

import re
import sys
import pathlib

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import app  # noqa: E402  registers Open Play engine (FAP_TEST-guarded)
from fap.openplay import add_derived_columns  # noqa: E402
from fap.openplay.engine import get_engine  # noqa: E402
from fap.pipeline.schema import coerce_schema  # noqa: E402
from fap.visuals.charts.match_flow import _team_metrics  # noqa: E402
from fap.xg.enrichment import sum_xg, sum_npxg  # noqa: E402
from fap.xg.services import xg_service  # noqa: E402

TOL = 1e-9
ROUND_TOL = 0.005  # surfaces that display round(x, 2)


def _match():
    """One representative match, two teams, NO provider xG column, one penalty."""
    raw = pd.DataFrame({
        "event_type": ["shot", "shot", "shot", "shot", "pass",
                       "shot", "shot"],
        "team":       ["A", "A", "A", "A", "A",  "B", "B"],
        "opponent":   ["B", "B", "B", "B", "B",  "A", "A"],
        "player":     ["A1", "A2", "A3", "A4", "A5", "B1", "B2"],
        "x": [95.0, 88.0, 89.0, 78.0, 40.0,  92.0, 84.0],
        "y": [50.0, 62.0, 50.0, 45.0, 50.0,  40.0, 58.0],
        "x2": [100.0, 100.0, 100.0, 100.0, 60.0, 100.0, 100.0],
        "y2": [50.0, 50.0, 50.0, 50.0, 55.0,  50.0, 50.0],
        "minute": [10, 25, 40, 55, 5, 30, 70],
        "second": [0, 0, 0, 0, 0, 0, 0],
        "period": [1, 1, 2, 2, 1, 1, 2],           # A: 2 first-half shots, 2 second-half
        "shot_result": ["Goal", "Saved", "Goal", "Off Target", "", "Saved", "Goal"],
        "set_piece": ["", "", "penalty", "", "", "", ""],   # A3 is a penalty
        "body_part": ["foot", "head", "foot", "foot", "", "foot", "head"],
    })
    assert "shot_xg" not in raw.columns and "xg" not in raw.columns   # no provider xG
    # mirror the production path: canonical coercion (adds outcome/etc.) then the
    # centralized derived-column enrichment (which attaches internal_xg).
    return add_derived_columns(coerce_schema(raw))


def _team_A(df):
    return df[df["team"] == "A"].copy()


def _reference(df_team):
    """Reference values from the canonical column ONLY (not from any UI)."""
    shots = df_team[df_team["event_type"].str.lower() == "shot"]
    xg = float(pd.to_numeric(shots["internal_xg"], errors="coerce").sum())
    non_pen = shots[shots["set_piece"].str.lower() != "penalty"]
    npxg = float(pd.to_numeric(non_pen["internal_xg"], errors="coerce").sum())
    return xg, npxg, shots


def _shot_map_subtitle_xg(df_team):
    """Render the real Shot Map panel and parse its subtitle total xG."""
    import matplotlib.pyplot as plt
    eng = get_engine()
    spec = eng.pitch_spec_cls()
    vt = eng.metadata["themes"]["Opta Analyst"]
    f = eng.apply_pitch_transforms(df_team, spec)
    ctx = eng.default_ctx(vt, spec, title="Shot Map", aux={"df_all": f})
    fig, ax = plt.subplots()
    sub = app.panel_shots(ax, f, ctx)
    plt.close(fig)
    m = re.search(r"xG:\s*([0-9.]+)", sub)
    return (float(m.group(1)) if m else None), sub, f


# --------------------------------------------------------------------------- #
def test_no_provider_xg_present_but_internal_xg_computed():
    df = _match()
    # The canonical schema reserves a 'shot_xg' slot, but with no provider data it
    # is entirely empty and is never used; internal_xg is computed regardless.
    if "shot_xg" in df.columns:
        assert pd.to_numeric(df["shot_xg"], errors="coerce").notna().sum() == 0
    assert "internal_xg" in df.columns
    assert df.loc[df["event_type"] == "shot", "internal_xg"].notna().any()


def test_every_surface_matches_reference():
    df = _match()
    a = _team_A(df)
    ref_xg, ref_npxg, _ = _reference(a)

    # A) Match Stats
    ms = _team_metrics(a)
    assert ms["xG"] == pytest.approx(round(ref_xg, 2), abs=ROUND_TOL)
    assert ms["NPxG"] == pytest.approx(round(ref_npxg, 2), abs=ROUND_TOL)

    # B) compute_metrics (drives KPI / summary tables)
    cm = app.compute_metrics(a)
    assert cm["xG"] == pytest.approx(round(ref_xg, 2), abs=ROUND_TOL)
    assert cm["NPxG"] == pytest.approx(round(ref_npxg, 2), abs=ROUND_TOL)

    # B') the exact helper the KPI tile uses
    assert sum_xg(a[a["event_type"] == "shot"]) == pytest.approx(ref_xg, abs=TOL)

    # C) Shot Map subtitle total
    sub_xg, _, _ = _shot_map_subtitle_xg(a)
    assert sub_xg == pytest.approx(round(ref_xg, 2), abs=ROUND_TOL)


def test_shot_to_team_level_aggregation():
    df = _match(); a = _team_A(df)
    ref_xg, ref_npxg, shots = _reference(a)
    assert sum_xg(shots) == pytest.approx(ref_xg, abs=TOL)          # team xG == Σ shot xG
    assert sum_npxg(shots) == pytest.approx(ref_npxg, abs=TOL)      # team NPxG == Σ non-pen xG


def test_penalty_contribution_equals_frozen_metadata():
    df = _match(); a = _team_A(df)
    ref_xg, ref_npxg, shots = _reference(a)
    frozen_pen = xg_service.penalty_xg()                            # read from metadata
    n_pen = int((shots["set_piece"].str.lower() == "penalty").sum())
    assert n_pen == 1
    assert (ref_xg - ref_npxg) == pytest.approx(frozen_pen, abs=1e-9)
    pen_row = shots[shots["set_piece"].str.lower() == "penalty"]
    assert pen_row["internal_xg"].iloc[0] == pytest.approx(frozen_pen, abs=1e-9)


def test_shot_map_uses_same_dataframe_and_xg():
    df = _match(); a = _team_A(df)
    ref_xg, _, shots = _reference(a)
    sub_xg, sub, f = _shot_map_subtitle_xg(a)
    assert "Marker size = xG" in sub                               # xG-encoded map
    assert sub_xg == pytest.approx(round(ref_xg, 2), abs=ROUND_TOL)
    # marker sizes derive from internal_xg (variation, sensible minimum)
    import matplotlib.pyplot as plt
    eng = get_engine(); spec = eng.pitch_spec_cls()
    vt = eng.metadata["themes"]["Opta Analyst"]
    ctx = eng.default_ctx(vt, spec, title="Shot Map", aux={"df_all": f})
    fig = eng.render("Shot Map", f, ctx)
    sizes = np.concatenate([c.get_sizes() for c in fig.axes[0].collections if len(c.get_sizes())])
    assert sizes.min() > 0 and sizes.max() > sizes.min()
    plt.close(fig)


def test_filter_consistency_first_half():
    df = _match(); a = _team_A(df)
    first_half = a[a["period"] == 1]
    ref_xg_h, ref_npxg_h, shots_h = _reference(first_half)
    # the filtered reference equals the explicit sum of the filtered shots
    assert ref_xg_h == pytest.approx(
        float(pd.to_numeric(shots_h["internal_xg"]).sum()), abs=TOL)
    # every surface agrees on the filtered scope
    assert _team_metrics(first_half)["xG"] == pytest.approx(round(ref_xg_h, 2), abs=ROUND_TOL)
    assert app.compute_metrics(first_half)["xG"] == pytest.approx(round(ref_xg_h, 2), abs=ROUND_TOL)
    sub_xg_h, _, _ = _shot_map_subtitle_xg(first_half)
    assert sub_xg_h == pytest.approx(round(ref_xg_h, 2), abs=ROUND_TOL)
    # filtering actually changed the scope
    ref_xg_full, _, _ = _reference(a)
    assert ref_xg_h < ref_xg_full


def test_rendering_does_not_mutate_dataframe():
    df = _match(); a = _team_A(df)
    before = a.copy(deep=True)
    _team_metrics(a)
    app.compute_metrics(a)
    _shot_map_subtitle_xg(a)
    for col in ["internal_xg", "x", "y", "team", "shot_result", "set_piece"]:
        pd.testing.assert_series_equal(a[col], before[col])


def test_determinism_repeated():
    df1 = _match(); df2 = _match()
    a1, a2 = _team_A(df1), _team_A(df2)
    assert sum_xg(a1[a1["event_type"] == "shot"]) == pytest.approx(
        sum_xg(a2[a2["event_type"] == "shot"]), abs=TOL)
    assert _team_metrics(a1)["xG"] == _team_metrics(a2)["xG"]
    assert _shot_map_subtitle_xg(a1)[0] == _shot_map_subtitle_xg(a2)[0]
