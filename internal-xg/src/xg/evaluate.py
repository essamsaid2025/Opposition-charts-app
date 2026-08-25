"""Evaluation utilities: metrics, reliability tables, calibration curves,
and the provider (StatsBomb) benchmark comparison (Checkpoint 3).

Nothing here fits a model; it only scores predictions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

# Reliability bins requested in the brief.
DEFAULT_BINS = [0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 1.0]


def core_metrics(y_true, p_pred) -> dict:
    y_true = np.asarray(y_true)
    p_pred = np.clip(np.asarray(p_pred, dtype=float), 1e-15, 1 - 1e-15)
    return {
        "log_loss": float(log_loss(y_true, p_pred, labels=[0, 1])),
        "brier": float(brier_score_loss(y_true, p_pred)),
        "roc_auc": float(roc_auc_score(y_true, p_pred)),
        "n": int(len(y_true)),
        "mean_pred": float(np.mean(p_pred)),
        "base_rate": float(np.mean(y_true)),
    }


def reliability_table(y_true, p_pred, bins=DEFAULT_BINS) -> pd.DataFrame:
    """Observed goal rate vs predicted probability per bin."""
    y_true = np.asarray(y_true)
    p_pred = np.asarray(p_pred, dtype=float)
    edges = np.array(bins, dtype=float)
    idx = np.digitize(p_pred, edges[1:-1], right=False)
    rows = []
    for b in range(len(edges) - 1):
        m = idx == b
        n = int(m.sum())
        goals = int(y_true[m].sum()) if n else 0
        rows.append(
            {
                "bin": f"{edges[b]:.2f}-{edges[b+1]:.2f}",
                "n_shots": n,
                "actual_goals": goals,
                "observed_rate": round(goals / n, 4) if n else float("nan"),
                "mean_pred": round(float(p_pred[m].mean()), 4) if n else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def calibration_points(y_true, p_pred, n_bins: int = 10, strategy: str = "quantile"):
    """Return (mean_pred, observed_rate, counts) for a calibration curve."""
    y_true = np.asarray(y_true)
    p_pred = np.asarray(p_pred, dtype=float)
    if strategy == "quantile":
        edges = np.unique(np.quantile(p_pred, np.linspace(0, 1, n_bins + 1)))
    else:
        edges = np.linspace(p_pred.min(), p_pred.max(), n_bins + 1)
    idx = np.clip(np.digitize(p_pred, edges[1:-1], right=False), 0, len(edges) - 2)
    xs, ys, ns = [], [], []
    for b in range(len(edges) - 1):
        m = idx == b
        if m.sum() == 0:
            continue
        xs.append(float(p_pred[m].mean()))
        ys.append(float(y_true[m].mean()))
        ns.append(int(m.sum()))
    return np.array(xs), np.array(ys), np.array(ns)


def expected_calibration_error(y_true, p_pred, n_bins: int = 10) -> float:
    xs, ys, ns = calibration_points(y_true, p_pred, n_bins=n_bins, strategy="quantile")
    if len(ns) == 0:
        return float("nan")
    w = ns / ns.sum()
    return float(np.sum(w * np.abs(xs - ys)))


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def calibration_slope_intercept(y_true, p_pred) -> dict:
    """Cox calibration slope + calibration-in-the-large.

    slope: coef of logit(p) in logistic reg y ~ logit(p)   (ideal 1.0)
    intercept_full: intercept of that same fit
    citl: calibration-in-the-large — intercept when slope is fixed at 1
          (ideal 0.0). Positive => model under-predicts overall.
    """
    from scipy.optimize import minimize_scalar
    from sklearn.linear_model import LogisticRegression

    y = np.asarray(y_true)
    z = _logit(p_pred)
    lr = LogisticRegression(C=1e9, solver="lbfgs", max_iter=2000).fit(z.reshape(-1, 1), y)
    slope = float(lr.coef_[0, 0])
    intercept_full = float(lr.intercept_[0])

    def nll(c):
        lp = z + c
        pr = np.clip(1 / (1 + np.exp(-lp)), 1e-12, 1 - 1e-12)
        return -np.mean(y * np.log(pr) + (1 - y) * np.log(1 - pr))

    citl = float(minimize_scalar(nll, bounds=(-5, 5), method="bounded").x)
    return {"slope": slope, "intercept_full": intercept_full, "citl": citl}


def max_calibration_error(y_true, p_pred, n_bins: int = 10) -> float:
    xs, ys, ns = calibration_points(y_true, p_pred, n_bins=n_bins, strategy="quantile")
    if len(ns) == 0:
        return float("nan")
    return float(np.max(np.abs(xs - ys)))


def segment_report(df: pd.DataFrame, pred_col: str, y_col: str, group, min_n: int = 50) -> pd.DataFrame:
    """Per-group calibration: n, mean pred, actual rate, expected vs observed goals."""
    rows = []
    grouped = df.groupby(group) if isinstance(group, str) else df.groupby(group)
    for key, g in grouped:
        n = len(g)
        mp = float(g[pred_col].mean())
        ar = float(g[y_col].mean())
        rows.append(
            {
                "group": key,
                "n_shots": n,
                "mean_pred": round(mp, 4),
                "actual_rate": round(ar, 4),
                "expected_goals": round(float(g[pred_col].sum()), 1),
                "observed_goals": int(g[y_col].sum()),
                "diff(pred-obs)": round(mp - ar, 4),
                "brier": round(float(brier_score_loss(g[y_col], np.clip(g[pred_col], 0, 1))), 4) if n >= min_n else np.nan,
                "reliable": n >= min_n,
            }
        )
    return pd.DataFrame(rows)


def provider_benchmark(internal_xg, provider_xg, y_true=None) -> dict:
    """Compare our internal xG to StatsBomb xG — REFERENCE ONLY, not a target."""
    a = np.asarray(internal_xg, dtype=float)
    b = np.asarray(provider_xg, dtype=float)
    mask = ~(np.isnan(a) | np.isnan(b))
    a, b = a[mask], b[mask]
    out = {
        "n": int(mask.sum()),
        "mean_internal_xg": float(a.mean()),
        "mean_provider_xg": float(b.mean()),
        "correlation": float(np.corrcoef(a, b)[0, 1]),
        "mean_abs_diff": float(np.mean(np.abs(a - b))),
    }
    if y_true is not None:
        yt = np.asarray(y_true)[mask]
        out["actual_goal_rate"] = float(yt.mean())
        out["provider_brier"] = float(brier_score_loss(yt, np.clip(b, 0, 1)))
        out["internal_brier"] = float(brier_score_loss(yt, np.clip(a, 0, 1)))
    return out
