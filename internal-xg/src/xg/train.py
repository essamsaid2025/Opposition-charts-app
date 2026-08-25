"""Training logic for the Logistic Regression baseline (Checkpoint 3).

Kept separate from inference (``predict.py``). Provides reusable helpers plus a
``run_baseline`` entry point that: splits data (match-level), tunes C on the
validation set, investigates calibration on validation, fits the final model on
train+val, and returns everything needed for reporting/saving.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.pipeline import Pipeline

from . import config, data_loader, evaluate, features as F, splits
from .preprocessing import build_preprocessor

C_GRID = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]


def build_estimator(C: float, feature_set: str = "A") -> Pipeline:
    return Pipeline(
        steps=[
            ("pre", build_preprocessor(feature_set)),
            (
                "clf",
                # L2 is the default penalty; passing it explicitly is
                # deprecated in sklearn 1.8+, so we rely on the default.
                LogisticRegression(
                    C=C, solver="lbfgs", max_iter=5000,
                    random_state=config.RANDOM_SEED,
                ),
            ),
        ]
    )


def _Xy(part: pd.DataFrame, cols):
    return part[cols], part["goal"].to_numpy()


@dataclass
class BaselineResult:
    best_C: float
    tuning: list = field(default_factory=list)
    calibration_choice: str = "raw"
    calibration_val: dict = field(default_factory=dict)
    final_pipeline: object = None
    feature_columns: list = field(default_factory=list)
    penalty_xg: float = 0.0
    splits_desc: pd.DataFrame = None
    chrono_desc: pd.DataFrame = None


def tune_C(train, val, cols, feature_set="A"):
    results = []
    for C in C_GRID:
        est = build_estimator(C, feature_set)
        Xtr, ytr = _Xy(train, cols)
        est.fit(Xtr, ytr)
        Xv, yv = _Xy(val, cols)
        p = est.predict_proba(Xv)[:, 1]
        m = evaluate.core_metrics(yv, p)
        results.append({"C": C, **m})
    best = min(results, key=lambda r: r["log_loss"])
    return best["C"], results


def investigate_calibration(train, val, cols, best_C, feature_set="A"):
    """Compare raw LR vs Platt (sigmoid) and isotonic on validation.

    Calibrators are fit on TRAIN only (internal CV). Validation is used to
    DECIDE; the test set stays untouched.
    """
    Xtr, ytr = _Xy(train, cols)
    Xv, yv = _Xy(val, cols)

    raw = build_estimator(best_C, feature_set).fit(Xtr, ytr)
    p_raw = raw.predict_proba(Xv)[:, 1]
    out = {"raw": {**evaluate.core_metrics(yv, p_raw),
                   "ece": evaluate.expected_calibration_error(yv, p_raw)}}

    for method in ("sigmoid", "isotonic"):
        cal = CalibratedClassifierCV(build_estimator(best_C, feature_set), method=method, cv=5)
        cal.fit(Xtr, ytr)
        p = cal.predict_proba(Xv)[:, 1]
        out[method] = {**evaluate.core_metrics(yv, p),
                       "ece": evaluate.expected_calibration_error(yv, p)}
    return out


def choose_calibration(cal_val: dict, min_gain: float = 1e-3) -> str:
    """Pick raw unless a calibrator beats it on val log_loss by >= min_gain."""
    raw_ll = cal_val["raw"]["log_loss"]
    best_method, best_ll = "raw", raw_ll
    for m in ("sigmoid", "isotonic"):
        if cal_val[m]["log_loss"] < best_ll - min_gain:
            best_method, best_ll = m, cal_val[m]["log_loss"]
    return best_method


def fit_final(trainval, cols, best_C, calibration="raw", feature_set="A"):
    X, y = _Xy(trainval, cols)
    base = build_estimator(best_C, feature_set)
    if calibration == "raw":
        base.fit(X, y)
        return base
    cal = CalibratedClassifierCV(base, method=calibration, cv=5)
    cal.fit(X, y)
    return cal


# --------------------------------------------------------------------------- #
# Interpretability
# --------------------------------------------------------------------------- #
def coefficient_table(raw_pipeline: Pipeline) -> pd.DataFrame:
    """Coefficients + odds ratios from a *raw* (uncalibrated) LR pipeline."""
    pre = raw_pipeline.named_steps["pre"]
    clf = raw_pipeline.named_steps["clf"]
    names = pre.get_feature_names_out()
    coefs = clf.coef_.ravel()
    df = pd.DataFrame({"feature": names, "coef": coefs, "odds_ratio": np.exp(coefs)})
    df["abs_coef"] = df["coef"].abs()
    return df.sort_values("abs_coef", ascending=False).reset_index(drop=True)


def reference_relative_coefs(raw_pipeline: Pipeline, categorical_cols, train_df: pd.DataFrame) -> dict:
    """Categorical coefficients expressed *relative to a reference level*.

    Because the one-hot encoder keeps every level (so unknown categories are
    handled at inference), individual level coefficients are not identifiable
    against the intercept — but their *differences* are. For each categorical we
    take the most frequent training level as the reference (coef 0) and report
    the other levels' log-odds and odds ratios relative to it.
    """
    pre = raw_pipeline.named_steps["pre"]
    clf = raw_pipeline.named_steps["clf"]
    cmap = dict(zip(pre.get_feature_names_out(), clf.coef_.ravel()))
    out = {}
    for col in categorical_cols:
        ref = train_df[col].mode().iloc[0]
        ref_coef = cmap.get(f"cat__{col}_{ref}", 0.0)
        rows = []
        for lev in sorted(train_df[col].dropna().unique().tolist()):
            key = f"cat__{col}_{lev}"
            if key not in cmap:
                continue
            d = cmap[key] - ref_coef
            rows.append({"level": lev, "coef_vs_ref": round(float(d), 4),
                         "odds_ratio": round(float(np.exp(d)), 4),
                         "is_reference": lev == ref})
        out[col] = {"reference": ref, "rows": rows}
    return out


def vif_table(train: pd.DataFrame, numeric_cols) -> pd.DataFrame:
    """Variance Inflation Factor for the numeric features (>~5 = concerning)."""
    X = train[numeric_cols].to_numpy(dtype=float)
    X = (X - X.mean(0)) / X.std(0)  # standardise for a scale-free VIF
    rows = []
    for i, col in enumerate(numeric_cols):
        others = np.delete(X, i, axis=1)
        r2 = LinearRegression().fit(others, X[:, i]).score(others, X[:, i])
        vif = np.inf if r2 >= 1 - 1e-12 else 1.0 / (1.0 - r2)
        rows.append({"feature": col, "R2_on_others": round(r2, 4), "VIF": round(vif, 2)})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Football sanity check inputs
# --------------------------------------------------------------------------- #
def sanity_shots() -> pd.DataFrame:
    """Controlled synthetic shots (raw StatsBomb coords) for sanity checks."""
    base = dict(
        body_part="Right Foot", shot_type="Open Play", assist_type="none",
        assisted=False, set_piece=False, free_kick=False, penalty=False,
    )
    rows = [
        {"label": "A close central foot", "shot_x": 114, "shot_y": 40, **base},
        {"label": "B long central foot", "shot_x": 85, "shot_y": 40, **base},
        {"label": "C close tight-angle", "shot_x": 114, "shot_y": 63, **base},
        {"label": "D medium central header", "shot_x": 110, "shot_y": 40,
         **{**base, "body_part": "Head"}},
        {"label": "E long-distance", "shot_x": 70, "shot_y": 40, **base},
        {"label": "F free kick (25m central)", "shot_x": 95, "shot_y": 40,
         **{**base, "shot_type": "Free Kick", "free_kick": True, "set_piece": True}},
    ]
    return pd.DataFrame(rows)


def symmetry_shots() -> pd.DataFrame:
    base = dict(
        body_part="Right Foot", shot_type="Open Play", assist_type="none",
        assisted=False, set_piece=False, free_kick=False, penalty=False,
    )
    return pd.DataFrame(
        [
            {"label": "left (x=105,y=25)", "shot_x": 105, "shot_y": 25, **base},
            {"label": "right (x=105,y=55)", "shot_x": 105, "shot_y": 55, **base},
        ]
    )


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_baseline(feature_set: str = "A", seed: int = 42) -> tuple[BaselineResult, dict]:
    df = data_loader.load_processed()
    non_pen, _pen = F.split_penalties(df)
    feat_np, cols = F.build_features(non_pen, feature_set)

    primary = splits.match_level_split(feat_np, seed=seed)
    splits.assert_no_match_overlap(primary)
    chrono = splits.chronological_split(feat_np)
    splits.assert_no_match_overlap(chrono)

    train, val, test = primary["train"], primary["val"], primary["test"]

    best_C, tuning = tune_C(train, val, cols, feature_set)
    cal_val = investigate_calibration(train, val, cols, best_C, feature_set)
    choice = choose_calibration(cal_val)

    trainval = pd.concat([train, val], ignore_index=True)
    final = fit_final(trainval, cols, best_C, calibration=choice, feature_set=feature_set)
    # A raw pipeline (fit on train+val) is always kept for interpretability.
    raw_final = fit_final(trainval, cols, best_C, calibration="raw", feature_set=feature_set)

    pen_est = F.estimate_penalty_xg(df)

    res = BaselineResult(
        best_C=best_C, tuning=tuning, calibration_choice=choice, calibration_val=cal_val,
        final_pipeline=final, feature_columns=cols, penalty_xg=pen_est["penalty_xg"],
        splits_desc=splits.describe_split(primary), chrono_desc=splits.describe_split(chrono),
    )
    context = {
        "df": df, "non_pen": non_pen, "feat_np": feat_np, "cols": cols,
        "primary": primary, "chrono": chrono, "raw_final": raw_final,
        "penalty_estimate": pen_est, "trainval": trainval, "feature_set": feature_set,
        "trained_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    return res, context
