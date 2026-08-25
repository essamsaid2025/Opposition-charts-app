"""Freeze / immutability tests for Internal xG Model v1.0 (Checkpoint 5)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import config, predict as P  # noqa: E402

V1 = config.MODELS_DIR / "internal_xg_v1.joblib"
BASELINE = config.MODELS_DIR / "logistic_baseline.joblib"


def _shots():
    return pd.DataFrame(
        [
            {"shot_x": 114, "shot_y": 40, "body_part": "Right Foot", "shot_type": "Open Play",
             "assist_type": "pass", "assisted": True, "set_piece": False, "free_kick": False, "penalty": False},
            {"shot_x": 95, "shot_y": 55, "body_part": "Head", "shot_type": "Open Play",
             "assist_type": "cross", "assisted": True, "set_piece": True, "free_kick": False, "penalty": False},
            {"shot_x": 108, "shot_y": 40, "body_part": "Right Foot", "shot_type": "Penalty",
             "assist_type": "none", "assisted": False, "set_piece": True, "free_kick": False, "penalty": True},
        ]
    )


@pytest.mark.skipif(not V1.exists(), reason="v1 not frozen yet")
def test_v1_loads_and_metadata_frozen():
    b = P.load_model(V1)
    md = b["metadata"]
    assert md["model_version"] == "v1.0" and md["frozen"] is True
    assert md["feature_set"] == "A"
    assert md["features"] == b["feature_columns"]
    assert "software_versions" in md and "penalty_handling" in md


@pytest.mark.skipif(not V1.exists(), reason="v1 not frozen yet")
def test_v1_predictions_in_range():
    b = P.load_model(V1)
    out = P.predict_xg(_shots(), bundle=b)
    assert out["xg"].between(0.0, 1.0).all()
    # penalty routed to the frozen constant
    assert out["xg"].iloc[2] == pytest.approx(b["penalty_xg"])


@pytest.mark.skipif(not (V1.exists() and BASELINE.exists()), reason="models missing")
def test_v1_matches_baseline_exactly():
    """The frozen v1 pipeline must be identical to the reviewed baseline."""
    v1 = P.load_model(V1)
    base = P.load_model(BASELINE)
    shots = _shots()
    a = P.predict_xg(shots, bundle=v1)["xg"].to_numpy()
    c = P.predict_xg(shots, bundle=base)["xg"].to_numpy()
    np.testing.assert_allclose(a, c, rtol=0, atol=1e-12)
