"""Checkpoint 5 — deep evaluation, calibration, robustness (LR vs XGB).

Discipline:
  * The primary match-level TEST set is a final holdout: used only to REPORT
    (never to tune or modify the model).
  * Robustness cross-validation uses ONLY train+val matches.
  * Temporal robustness refits the SAME frozen config (no tuning) on the
    chronological train+val and evaluates on the later chronological test
    (avoids the leakage that would come from scoring the primary-trained model,
    which already saw chrono-test matches).

Usage (from internal-xg/):
    python scripts/evaluate_checkpoint5.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import config, data_loader, evaluate, features as F, splits, train  # noqa: E402
from xg.preprocessing import build_preprocessor_for  # noqa: E402

SEED = config.RANDOM_SEED
XGB_BASE = dict(objective="binary:logistic", eval_metric="logloss", tree_method="hist",
                subsample=0.8, colsample_bytree=0.8, reg_alpha=0.0, n_jobs=-1,
                random_state=SEED, importance_type="gain")
XGB_BEST = dict(max_depth=5, learning_rate=0.05, min_child_weight=5, reg_lambda=5.0, n_estimators=141)

lines: list[str] = []
def w(*a): lines.append(" ".join(str(x) for x in a))


def make_xgb():
    return XGBClassifier(**XGB_BASE, **XGB_BEST)


def lr_pipe():
    return train.build_estimator(C=10.0, feature_set="A")


def xgb_pipe(cols):
    return Pipeline([("pre", build_preprocessor_for(cols)), ("clf", make_xgb())])


def metrics_row(y, p):
    m = evaluate.core_metrics(y, p)
    m["ece"] = evaluate.expected_calibration_error(y, p)
    return m


def main() -> None:
    config.ensure_dirs()
    df = data_loader.load_processed()
    non_pen, _ = F.split_penalties(df)
    feat, cols = F.build_features(non_pen, "A")
    primary = splits.match_level_split(feat, seed=SEED)
    tr, va, te = primary["train"], primary["val"], primary["test"]
    yte = te["goal"].to_numpy()

    lr_bundle = joblib.load(config.MODELS_DIR / "logistic_baseline.joblib")
    xgb_bundle = joblib.load(config.MODELS_DIR / "xgboost_candidate.joblib")
    p_lr = lr_bundle["pipeline"].predict_proba(te[cols])[:, 1]
    p_xgb = xgb_bundle["pipeline"].predict_proba(te[cols])[:, 1]
    te = te.copy(); te["p_lr"] = p_lr; te["p_xgb"] = p_xgb

    w("=" * 72); w("CHECKPOINT 5 — DEEP EVALUATION / CALIBRATION / ROBUSTNESS"); w("=" * 72)
    w(f"Primary test: {len(te)} shots, {int(yte.sum())} goals, base rate {yte.mean():.4f}")

    # ================= 1. CALIBRATION DEEP DIVE (LR, test) =================
    w("\n" + "#" * 60); w("[1] CALIBRATION DEEP DIVE — Logistic Regression (test holdout)")
    m = metrics_row(yte, p_lr)
    si = evaluate.calibration_slope_intercept(yte, p_lr)
    w(f"  Log Loss={m['log_loss']:.5f}  Brier={m['brier']:.5f}  ROC-AUC={m['roc_auc']:.4f}")
    w(f"  ECE={m['ece']:.4f}  MCE={evaluate.max_calibration_error(yte, p_lr):.4f}")
    w(f"  Calibration slope={si['slope']:.3f} (ideal 1.0)  intercept={si['intercept_full']:.3f}  "
      f"calibration-in-the-large={si['citl']:.3f} (ideal 0.0)")
    rel = evaluate.reliability_table(yte, p_lr)
    rel["expected_goals"] = [round(te.loc[
        (te["p_lr"] >= float(b.split("-")[0])) & (te["p_lr"] < float(b.split("-")[1]) + (1e-9 if b.endswith("1.00") else 0)),
        "p_lr"].sum(), 1) for b in rel["bin"]]
    w("  Reliability table (predicted bin | n | mean pred | actual rate | obs goals | exp goals):")
    w(rel.rename(columns={"mean_pred": "pred_prob", "observed_rate": "actual_rate",
                          "actual_goals": "obs_goals"}).to_string(index=False))

    # reliability diagram
    xs, ys, ns = evaluate.calibration_points(yte, p_lr, n_bins=10)
    plt.figure(figsize=(5, 5)); plt.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    plt.plot(xs, ys, "o-", label="LR"); plt.xlabel("Mean predicted xG"); plt.ylabel("Observed rate")
    plt.title("Reliability — LR (test)"); plt.legend(); plt.tight_layout()
    plt.savefig(ROOT / "reports" / "reliability_lr_deep.png", dpi=120); plt.close()

    # ================= 2/5. SEGMENTS: shot type & body part =================
    w("\n" + "#" * 60); w("[2] CALIBRATION BY SHOT TYPE (LR, test)")
    w(evaluate.segment_report(te, "p_lr", "goal", "shot_type").to_string(index=False))
    te["is_header"] = (te["body_part"] == "Head")
    te["foot_head"] = np.where(te["body_part"].isin(["Right Foot", "Left Foot"]), "foot",
                               np.where(te["body_part"] == "Head", "head", "other"))
    w("\n[5] BODY PART ANALYSIS (LR, test)")
    w(evaluate.segment_report(te, "p_lr", "goal", "foot_head").to_string(index=False))
    w("    (full body_part breakdown)")
    w(evaluate.segment_report(te, "p_lr", "goal", "body_part").to_string(index=False))

    # ================= 3. CALIBRATION BY DISTANCE =================
    w("\n" + "#" * 60); w("[3] CALIBRATION BY DISTANCE (LR, test) — bands in metres")
    dbins = [0, 6, 10, 15, 20, 25, 30, 300]
    dlbl = ["0-6", "6-10", "10-15", "15-20", "20-25", "25-30", "30+"]
    te["dist_band"] = pd.cut(te["distance"], bins=dbins, labels=dlbl, right=False)
    w(evaluate.segment_report(te, "p_lr", "goal", "dist_band").to_string(index=False))

    # ================= 4. CALIBRATION BY ANGLE =================
    w("\n" + "#" * 60); w("[4] CALIBRATION BY ANGLE (LR, test) — bands in degrees")
    abins = [0, 10, 20, 30, 45, 200]
    albl = ["0-10", "10-20", "20-30", "30-45", "45+"]
    te["angle_band"] = pd.cut(te["angle_deg"], bins=abins, labels=albl, right=False)
    w(evaluate.segment_report(te, "p_lr", "goal", "angle_band").to_string(index=False))

    # ================= 6. ASSIST TYPE =================
    w("\n" + "#" * 60); w("[6] ASSIST TYPE ANALYSIS (LR, test)")
    w(evaluate.segment_report(te, "p_lr", "goal", "assist_type").to_string(index=False))
    w("    NOTE: small assist categories (cutback / through_ball) — interpret with caution.")

    # ================= 7. ROBUSTNESS CV (train+val ONLY) =================
    w("\n" + "#" * 60); w("[7] ROBUSTNESS — repeated match-level CV (train+val ONLY; test untouched)")
    trainval = pd.concat([tr, va], ignore_index=True)
    match_ids = trainval["match_id"].drop_duplicates().to_numpy()
    K, R = 5, 2
    lr_scores, xgb_scores = [], []
    for r in range(R):
        rng = np.random.default_rng(SEED + r); ids = match_ids.copy(); rng.shuffle(ids)
        for chunk in np.array_split(ids, K):
            test_ids = set(chunk.tolist())
            fold_te = trainval[trainval["match_id"].isin(test_ids)]
            fold_tr = trainval[~trainval["match_id"].isin(test_ids)]
            ytr, yfte = fold_tr["goal"].to_numpy(), fold_te["goal"].to_numpy()
            lrp = lr_pipe().fit(fold_tr[cols], ytr).predict_proba(fold_te[cols])[:, 1]
            xgp = xgb_pipe(cols).fit(fold_tr[cols], ytr).predict_proba(fold_te[cols])[:, 1]
            lr_scores.append(metrics_row(yfte, lrp)); xgb_scores.append(metrics_row(yfte, xgp))
    def summ(scores, key):
        v = np.array([s[key] for s in scores]); return v.mean(), v.std()
    w(f"  {R}x{K}-fold grouped CV ({len(lr_scores)} folds):")
    for key in ["log_loss", "brier", "roc_auc", "ece"]:
        lm, ls = summ(lr_scores, key); xm, xs_ = summ(xgb_scores, key)
        w(f"    {key:9s}  LR = {lm:.5f} ± {ls:.5f}    XGB = {xm:.5f} ± {xs_:.5f}    "
          f"Δ(XGB-LR) = {xm-lm:+.5f}")
    # paired difference on log_loss
    d = np.array([x["log_loss"] for x in xgb_scores]) - np.array([l["log_loss"] for l in lr_scores])
    w(f"  Paired log_loss diff (XGB-LR): mean={d.mean():+.5f}  std={d.std():.5f}  "
      f"folds where XGB better: {int((d<0).sum())}/{len(d)}")

    # ================= 8. TEMPORAL ROBUSTNESS =================
    w("\n" + "#" * 60); w("[8] TEMPORAL ROBUSTNESS (chronological split; same config, refit — no tuning)")
    chrono = splits.chronological_split(feat)
    c_tr = pd.concat([chrono["train"], chrono["val"]], ignore_index=True)
    c_te = chrono["test"]
    ycte = c_te["goal"].to_numpy()
    w(f"  chrono train+val: {c_tr['match_id'].nunique()} matches / {len(c_tr)} shots; "
      f"chrono test: {c_te['match_id'].nunique()} matches / {len(c_te)} shots (later in time)")
    lr_c = lr_pipe().fit(c_tr[cols], c_tr["goal"].to_numpy())
    xgb_c = xgb_pipe(cols).fit(c_tr[cols], c_tr["goal"].to_numpy())
    mlrc = metrics_row(ycte, lr_c.predict_proba(c_te[cols])[:, 1])
    mxgc = metrics_row(ycte, xgb_c.predict_proba(c_te[cols])[:, 1])
    w(f"    LR  chrono-test: log_loss={mlrc['log_loss']:.5f} brier={mlrc['brier']:.5f} auc={mlrc['roc_auc']:.4f} ece={mlrc['ece']:.4f}")
    w(f"    XGB chrono-test: log_loss={mxgc['log_loss']:.5f} brier={mxgc['brier']:.5f} auc={mxgc['roc_auc']:.4f} ece={mxgc['ece']:.4f}")
    w(f"    (compare vs primary match-level test: LR log_loss={m['log_loss']:.5f} brier={m['brier']:.5f})")

    # ================= 9. EXTREME-SHOT BEHAVIOR =================
    w("\n" + "#" * 60); w("[9] EXTREME-SHOT BEHAVIOR — LR vs XGB (central sweep)")
    def sweep(y_val):
        xs_ = np.linspace(119.5, 60, 60)
        d = pd.DataFrame({"shot_x": xs_, "shot_y": y_val, "body_part": "Right Foot",
                          "shot_type": "Open Play", "assist_type": "none", "assisted": False,
                          "set_piece": False, "free_kick": False, "penalty": False})
        f2, _ = F.build_features(d, "A")
        return f2["distance"].to_numpy(), lr_bundle["pipeline"].predict_proba(f2[cols])[:, 1], \
            xgb_bundle["pipeline"].predict_proba(f2[cols])[:, 1]
    dcen, lrc, xgc = sweep(40)
    # monotonicity check (should be non-increasing with distance, central)
    lr_mono = bool(np.all(np.diff(lrc) <= 1e-9))
    xg_mono = bool(np.all(np.diff(xgc) <= 1e-9))
    w(f"  Central shot, xG vs distance (selected):")
    for dd in [2, 6, 10, 16, 24, 32, 45, 55]:
        i = int(np.argmin(np.abs(dcen - dd)))
        w(f"    dist={dcen[i]:4.1f}m   LR={lrc[i]:.4f}   XGB={xgc[i]:.4f}")
    w(f"  Monotonic non-increasing with distance?  LR={lr_mono}   XGB={xg_mono}")
    plt.figure(figsize=(6, 4)); plt.plot(dcen, lrc, label="LR"); plt.plot(dcen, xgc, label="XGB")
    plt.xlabel("Distance (m), central"); plt.ylabel("xG"); plt.title("Extreme-distance behavior (central)")
    plt.legend(); plt.tight_layout(); plt.savefig(ROOT / "reports" / "extreme_sweep.png", dpi=120); plt.close()

    # ================= 10. AGGREGATE xG VALIDATION =================
    w("\n" + "#" * 60); w("[10] AGGREGATE xG VALIDATION (LR, test)")
    w(f"  ALL test shots: sum xG={te['p_lr'].sum():.1f}  actual goals={int(yte.sum())}  "
      f"ratio={te['p_lr'].sum()/max(yte.sum(),1):.3f}")
    for level in ["match_id", "team", "competition"]:
        agg = te.groupby(level).agg(shots=("goal", "size"), goals=("goal", "sum"),
                                    xg=("p_lr", "sum")).reset_index()
        big = agg[agg["shots"] >= (5 if level == "match_id" else 30)]
        if len(big) >= 3:
            corr = np.corrcoef(big["xg"], big["goals"])[0, 1]
            mae = np.mean(np.abs(big["xg"] - big["goals"]))
            w(f"  by {level}: groups(n>= thr)={len(big)}  corr(xG,goals)={corr:.3f}  "
              f"MAE={mae:.2f}  total_xG={big['xg'].sum():.1f} vs goals={int(big['goals'].sum())}")

    # ================= 11. PROVIDER COMPARISON =================
    w("\n" + "#" * 60); w("[11] PROVIDER COMPARISON (StatsBomb — reference only)")
    sb = te["statsbomb_xg"].to_numpy()
    bl = evaluate.provider_benchmark(p_lr, sb, yte)
    w(f"  overall: internal_mean={bl['mean_internal_xg']:.4f} provider_mean={bl['mean_provider_xg']:.4f} "
      f"actual={bl['actual_goal_rate']:.4f}")
    w(f"           corr={bl['correlation']:.4f} MAD={bl['mean_abs_diff']:.4f} "
      f"internal_brier={bl['internal_brier']:.4f} provider_brier={bl['provider_brier']:.4f}")
    w("  By distance band (mean internal LR / mean provider / actual rate / n):")
    for band, g in te.groupby("dist_band", observed=True):
        if len(g) < 30:
            continue
        w(f"    {str(band):6s}  LR={g['p_lr'].mean():.4f}  SB={g['statsbomb_xg'].mean():.4f}  "
          f"actual={g['goal'].mean():.4f}  n={len(g)}")

    # ================= 12. COMPLEXITY DECISION =================
    w("\n" + "#" * 60); w("[12] MODEL COMPLEXITY DECISION")
    w(f"  Primary test:   LR  log_loss={m['log_loss']:.5f} brier={m['brier']:.5f} auc={m['roc_auc']:.4f} ece={m['ece']:.4f}")
    mx = metrics_row(yte, p_xgb)
    w(f"                  XGB log_loss={mx['log_loss']:.5f} brier={mx['brier']:.5f} auc={mx['roc_auc']:.4f} ece={mx['ece']:.4f}")
    lm_ll, ls_ll = summ(lr_scores, "log_loss"); xm_ll, xs_ll = summ(xgb_scores, "log_loss")
    w(f"  CV log_loss:    LR {lm_ll:.5f}±{ls_ll:.5f}   XGB {xm_ll:.5f}±{xs_ll:.5f}   "
      f"(Δ {xm_ll-lm_ll:+.5f}, within ±1σ={abs(xm_ll-lm_ll)<ls_ll})")
    w(f"  Extreme monotonicity: LR={lr_mono}  XGB={xg_mono}")

    # persist a machine-readable summary for the report
    summary = {
        "test_LR": m, "test_XGB": mx,
        "calibration_slope_intercept_LR": si,
        "cv_LR": {k: summ(lr_scores, k) for k in ["log_loss", "brier", "roc_auc", "ece"]},
        "cv_XGB": {k: summ(xgb_scores, k) for k in ["log_loss", "brier", "roc_auc", "ece"]},
        "temporal_LR": mlrc, "temporal_XGB": mxgc,
        "extreme_monotonic": {"LR": lr_mono, "XGB": xg_mono},
        "provider": bl,
    }
    (ROOT / "reports" / "checkpoint5_summary.json").write_text(
        json.dumps(summary, indent=2, default=lambda o: float(o) if isinstance(o, np.floating) else list(o)),
        encoding="utf-8")
    (ROOT / "reports" / "checkpoint5_report.txt").write_text("\n".join(lines), encoding="utf-8")
    w("\nDONE.")


if __name__ == "__main__":
    main()
