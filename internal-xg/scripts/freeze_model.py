"""Freeze the Logistic Regression baseline as Internal xG Model v1.0 (Checkpoint 5).

Creates an immutable artifact + metadata. The pipeline object is the exact
baseline pipeline (byte-identical predictions); only metadata is enriched with
version, dataset stats, final metrics, and software versions.

Usage (from internal-xg/):
    python scripts/freeze_model.py
"""
from __future__ import annotations

import datetime as dt
import json
import platform
import sys
from pathlib import Path

import joblib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scipy  # noqa: E402
import sklearn  # noqa: E402
import xgboost  # noqa: E402

from xg import config, data_loader, evaluate, features as F, splits  # noqa: E402


def main() -> None:
    baseline = joblib.load(config.MODELS_DIR / "logistic_baseline.joblib")
    df = data_loader.load_processed()
    non_pen, pen = F.split_penalties(df)
    feat, cols = F.build_features(non_pen, "A")
    primary = splits.match_level_split(feat, seed=config.RANDOM_SEED)
    te = primary["test"]
    yte = te["goal"].to_numpy()
    p = baseline["pipeline"].predict_proba(te[cols])[:, 1]
    m = evaluate.core_metrics(yte, p)
    si = evaluate.calibration_slope_intercept(yte, p)

    pen_est = F.estimate_penalty_xg(df)

    metadata = {
        "model_name": "Internal xG Model",
        "model_version": "v1.0",
        "model_type": "LogisticRegression (L2, C=10) — raw (no post-hoc calibration)",
        "description": "Independent internal Expected Goals model trained on actual "
                       "shot outcomes (goal/no-goal) from public historical event data. "
                       "NOT Opta / StatsBomb / Wyscout xG.",
        "frozen": True,
        "frozen_at": dt.datetime.now().isoformat(timespec="seconds"),
        "training_data_source": "StatsBomb Open Data",
        "competition_selection": [lbl for _, _, lbl in config.COMPETITION_SELECTION],
        "n_matches_total": int(df["match_id"].nunique()),
        "n_shots_total": int(len(df)),
        "n_shots_nonpenalty": int(len(non_pen)),
        "n_penalties": int(len(pen)),
        "goal_base_rate_nonpenalty": float(non_pen["goal"].mean()),
        "feature_set": "A",
        "features": cols,
        "target": "goal (non-penalty shots only)",
        "excluded_from_features": ["statsbomb_xg", "outcome", "penalties",
                                   "Group B features (technique, play_pattern, one_on_one, "
                                   "first_time, open_goal, aerial_won, follows_dribble)",
                                   "freeze_frame / any post-shot information"],
        "preprocessing": "ColumnTransformer: numeric(median impute+standardise), "
                         "categorical(constant 'missing' impute + one-hot, unknown-safe), "
                         "binary(to-float + constant-0 impute). Saved inside the pipeline.",
        "hyperparameters": {"C": 10.0, "penalty": "l2", "solver": "lbfgs", "max_iter": 5000},
        "calibration_method": "none (raw LR chosen; beat Platt/isotonic on validation)",
        "penalty_handling": {
            "policy": "separate process; main model trained on non-penalty shots only",
            "penalty_xg": float(pen_est["penalty_xg"]),
            "penalty_xg_wilson95": [float(pen_est["wilson95_lo"]), float(pen_est["wilson95_hi"])],
            "n_penalties": int(pen_est["n_penalties"]),
        },
        "split_methodology": {
            "primary": "match-level, seeded (42), 70/15/15, no shot leakage",
            "robustness": "2x5-fold match-level grouped CV on train+val only",
            "temporal": "chronological match-level split (same config refit, no tuning)",
        },
        "final_metrics_primary_test": {
            "log_loss": float(m["log_loss"]), "brier": float(m["brier"]),
            "roc_auc": float(m["roc_auc"]),
            "ece": float(evaluate.expected_calibration_error(yte, p)),
            "mce": float(evaluate.max_calibration_error(yte, p)),
            "calibration_slope": float(si["slope"]),
            "calibration_in_the_large": float(si["citl"]),
            "n_test_shots": int(len(te)),
        },
        "software_versions": {
            "python": platform.python_version(),
            "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__, "xgboost": xgboost.__version__,
            "joblib": joblib.__version__,
        },
        "limitations": [
            "Internal model; not equivalent to commercial provider xG.",
            "No defender/goalkeeper context (freeze-frame deliberately excluded for "
            "reproducibility on future internal data).",
            "Trained on men's football (4 leagues 2015/16 + World Cup 2018/2022 + Euro 2020/2024).",
            "Penalties handled as a separate constant, not modelled.",
            "Per-match xG has high variance (corr with goals ~0.41 at match level); "
            "reliable in aggregate.",
        ],
    }

    bundle = {
        "pipeline": baseline["pipeline"],
        "feature_set": "A",
        "feature_columns": cols,
        "penalty_xg": float(pen_est["penalty_xg"]),
        "metadata": metadata,
    }
    out = config.MODELS_DIR / "internal_xg_v1.joblib"
    joblib.dump(bundle, out)
    (config.MODELS_DIR / "internal_xg_v1_meta.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"FROZEN: {out}")


if __name__ == "__main__":
    main()
