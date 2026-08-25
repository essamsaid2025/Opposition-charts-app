"""Public API tests for the Internal xG Model (Checkpoint 8).

Exercises the production surface in xg.api against the frozen v1 model.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import api, config, features as F  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (config.MODELS_DIR / "internal_xg_v1.joblib").exists(), reason="frozen v1 not present"
)


def _shot(**kw):
    base = dict(shot_x=110.0, shot_y=40.0, body_part="Right Foot", shot_type="Open Play",
                assist_type="none", assisted=False, set_piece=False, free_kick=False, penalty=False)
    base.update(kw)
    return pd.DataFrame([base])


def _team_df():
    return pd.DataFrame([
        {"team": "A", "shot_x": 112, "shot_y": 40, "penalty": False},
        {"team": "A", "shot_x": 100, "shot_y": 30, "penalty": False},
        {"team": "A", "shot_x": 108, "shot_y": 40, "shot_type": "Penalty", "penalty": True},
        {"team": "B", "shot_x": 95, "shot_y": 55, "penalty": False},
    ])


def test_api_import_and_predict():
    out = api.predict_xg(_shot())
    assert "xg" in out.columns and 0 <= out["xg"].iloc[0] <= 1


def test_does_not_mutate_caller():
    d = _shot()
    before = d.copy()
    api.predict_xg(d)
    pd.testing.assert_frame_equal(d, before)


def test_empty_and_single_and_many():
    assert len(api.predict_xg(pd.DataFrame(columns=["shot_x", "shot_y", "penalty"]))) == 0
    assert len(api.predict_xg(_shot())) == 1
    big = pd.concat([_shot(shot_x=110, shot_y=40)] * 3000, ignore_index=True)
    assert api.predict_xg(big)["xg"].between(0, 1).all()


def test_missing_optional_and_unseen():
    assert 0 <= api.predict_xg(pd.DataFrame([{"shot_x": 110, "shot_y": 40, "penalty": False}]))["xg"].iloc[0] <= 1
    out = api.predict_xg(_shot(body_part="Elbow", shot_type="Bicycle", assist_type="lob"))
    assert 0 <= out["xg"].iloc[0] <= 1


def test_invalid_and_mixed():
    d = pd.concat([_shot(shot_x=112, shot_y=40), _shot(shot_x=999, shot_y=40)], ignore_index=True)
    out = api.predict_xg(d, on_invalid="nan")
    assert 0 <= out["xg"].iloc[0] <= 1 and np.isnan(out["xg"].iloc[1])
    with pytest.raises(ValueError):
        api.predict_xg(_shot(shot_x=np.nan), on_invalid="error")


def test_penalty_uses_metadata_value():
    out = api.predict_xg(_shot(shot_x=108, shot_y=40, shot_type="Penalty", penalty=True))
    assert out["xg"].iloc[0] == pytest.approx(api.penalty_xg())


def test_team_xg_and_npxg():
    d = _team_df()
    scored = api.predict_xg(d)
    assert api.calculate_team_xg(d) == pytest.approx(scored["xg"].sum())
    # npxg excludes the single penalty
    manual_np = scored.loc[~d["penalty"].astype(bool), "xg"].sum()
    assert api.calculate_npxg(d) == pytest.approx(manual_np)
    assert api.calculate_team_xg(d) > api.calculate_npxg(d)


def test_team_xg_grouped():
    d = _team_df()
    by_team = api.calculate_team_xg(d, by="team")
    scored = api.predict_xg(d)
    assert by_team["A"] == pytest.approx(scored[scored["team"] == "A"]["xg"].sum())
    assert set(by_team.index) == {"A", "B"}


def test_deterministic_and_cached():
    d = pd.concat([_shot(shot_x=112, shot_y=44)] * 25, ignore_index=True)
    a = api.predict_xg(d)["xg"].to_numpy()
    b = api.predict_xg(d)["xg"].to_numpy()
    np.testing.assert_array_equal(a, b)
    # cache returns the same object
    assert api.load() is api.load()


def test_model_info_and_schema():
    info = api.model_info()
    for k in ["model_version", "model_type", "features", "hyperparameters",
              "penalty_xg", "software_versions", "frozen", "training_matches", "training_shots"]:
        assert k in info
    assert info["model_version"] == "v1.0" and info["frozen"] is True
    schema = api.input_schema()
    assert schema["required"] == ["shot_x", "shot_y"]
    assert schema["features_used_by_model"] == list(F.FEATURES_A)


def test_feature_consistency_training_vs_inference():
    """Inference must score EXACTLY the features that features.build_features
    produces (one source of truth) — no duplicated formulas."""
    d = _shot(shot_x=103.7, shot_y=51.3, body_part="Head", assist_type="cross", assisted=True)
    feat, cols = F.build_features(d, "A")
    bundle = api.load()
    direct = bundle["pipeline"].predict_proba(feat[cols])[:, 1][0]
    via_api = api.predict_xg(d)["xg"].iloc[0]
    assert via_api == pytest.approx(direct, abs=1e-12)
