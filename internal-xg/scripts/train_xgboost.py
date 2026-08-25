"""Checkpoint 4 — XGBoost advanced model experiment.

Reuses the EXACT Checkpoint-3 match-level split (seed=42), the same FEATURES_A,
and the same preprocessing. Trains XGBoost with early stopping, investigates
calibration on validation only, runs reduced-feature experiments, diagnoses
overfitting, computes feature importance, football sanity + provider benchmark,
and compares head-to-head with the Logistic Regression baseline.

Usage (from internal-xg/):
    python scripts/train_xgboost.py

Writes models/xgboost_candidate.joblib (+ _meta.json), reports/checkpoint4_report.txt,
reports/calibration_xgboost.png.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.inspection import permutation_importance
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import config, data_loader, evaluate, features as F, splits, train  # noqa: E402
from xg.preprocessing import build_preprocessor_for  # noqa: E402
from xg.predict import predict_xg  # noqa: E402

SEED = config.RANDOM_SEED
EARLY = 50
MAX_TREES = 3000

BASE_PARAMS = dict(
    objective="binary:logistic", eval_metric="logloss", tree_method="hist",
    subsample=0.8, colsample_bytree=0.8, reg_alpha=0.0, n_jobs=-1,
    random_state=SEED, importance_type="gain",
)


def make_xgb(params, n_estimators, early=False):
    kw = dict(BASE_PARAMS)
    kw.update(params)
    kw["n_estimators"] = n_estimators
    if early:
        kw["early_stopping_rounds"] = EARLY
    return XGBClassifier(**kw)


def fit_with_earlystop(cols, params, train_df, val_df):
    """Fit pre+XGB on train with early stopping on val. Returns (pipeline, best_iter, val_metrics)."""
    pre = build_preprocessor_for(cols)
    Xtr = pre.fit_transform(train_df[cols], train_df["goal"].to_numpy())
    Xv = pre.transform(val_df[cols])
    clf = make_xgb(params, MAX_TREES, early=True)
    clf.fit(Xtr, train_df["goal"].to_numpy(), eval_set=[(Xv, val_df["goal"].to_numpy())], verbose=False)
    best_iter = int(clf.best_iteration) + 1
    pipe = Pipeline([("pre", pre), ("clf", clf)])
    pv = pipe.predict_proba(val_df[cols])[:, 1]
    return pipe, best_iter, evaluate.core_metrics(val_df["goal"].to_numpy(), pv)


def main() -> None:
    config.ensure_dirs()
    lines: list[str] = []
    w = lambda *a: lines.append(" ".join(str(x) for x in a))

    # ---- data + identical split ----
    df = data_loader.load_processed()
    non_pen, _ = F.split_penalties(df)
    feat, cols = F.build_features(non_pen, "A")
    primary = splits.match_level_split(feat, seed=SEED)  # identical to Checkpoint 3
    splits.assert_no_match_overlap(primary)
    tr, va, te = primary["train"], primary["val"], primary["test"]
    ytr, yva, yte = (p["goal"].to_numpy() for p in (tr, va, te))
    pen_xg = F.estimate_penalty_xg(df)["penalty_xg"]

    w("=" * 70); w("CHECKPOINT 4 — XGBOOST ADVANCED MODEL"); w("=" * 70)
    w("\n[SPLIT] identical to Checkpoint 3 (match-level, seed=42):")
    w(splits.describe_split(primary).to_string(index=False))
    w("[FEATURES] FEATURES_A: " + ", ".join(cols))

    # ---- 1) grid search on FULL FEATURES_A (select by val log loss) ----
    depths, lrs, mcws, lambdas = [3, 4, 5], [0.03, 0.05], [5, 20], [1.0, 5.0]
    grid = [dict(max_depth=d, learning_rate=lr, min_child_weight=m, reg_lambda=lam)
            for d, lr, m, lam in itertools.product(depths, lrs, mcws, lambdas)]
    results = []
    for g in grid:
        _, bi, mv = fit_with_earlystop(cols, g, tr, va)
        results.append({**g, "best_iter": bi, "val_logloss": mv["log_loss"],
                        "val_brier": mv["brier"], "val_auc": mv["roc_auc"]})
    rdf = pd.DataFrame(results).sort_values("val_logloss").reset_index(drop=True)
    best = rdf.iloc[0]
    best_params = dict(max_depth=int(best.max_depth), learning_rate=float(best.learning_rate),
                       min_child_weight=int(best.min_child_weight), reg_lambda=float(best.reg_lambda))
    N = int(best.best_iter)
    w(f"\n[4] XGB GRID SEARCH ({len(grid)} configs, early stopping). Top 5 by val log loss:")
    w(rdf.head(5).round(5).to_string(index=False))
    w(f"    -> selected: {best_params}, n_estimators={N}")

    # ---- raw model fit on TRAIN only (for overfitting diagnostics) ----
    raw_train_pipe, _, _ = fit_with_earlystop(cols, best_params, tr, va)

    def M(pipe, X, y):
        return evaluate.core_metrics(y, pipe.predict_proba(X[cols])[:, 1])

    m_tr, m_va = M(raw_train_pipe, tr, ytr), M(raw_train_pipe, va, yva)

    # ---- 7) calibration investigation on VALIDATION only ----
    trainval = pd.concat([tr, va], ignore_index=True)
    cal_val = {"raw": {**m_va, "ece": evaluate.expected_calibration_error(yva, raw_train_pipe.predict_proba(va[cols])[:, 1])}}
    for method in ("sigmoid", "isotonic"):
        base = Pipeline([("pre", build_preprocessor_for(cols)), ("clf", make_xgb(best_params, N))])
        cal = CalibratedClassifierCV(base, method=method, cv=5)
        cal.fit(tr[cols], ytr)
        pv = cal.predict_proba(va[cols])[:, 1]
        cal_val[method] = {**evaluate.core_metrics(yva, pv), "ece": evaluate.expected_calibration_error(yva, pv)}
    choice = train.choose_calibration(cal_val)
    w("\n[7] CALIBRATION INVESTIGATION (decided on VALIDATION only)")
    for k, v in cal_val.items():
        w(f"    {k:9s} log_loss={v['log_loss']:.5f} brier={v['brier']:.5f} auc={v['roc_auc']:.4f} ece={v['ece']:.4f}")
    w(f"    -> chosen: {choice.upper()}")

    # ---- final models fit on TRAIN+VAL ----
    raw_final = Pipeline([("pre", build_preprocessor_for(cols)), ("clf", make_xgb(best_params, N))])
    raw_final.fit(trainval[cols], trainval["goal"].to_numpy())
    best_cal_method = min(("sigmoid", "isotonic"), key=lambda mm: cal_val[mm]["log_loss"])
    cal_final = CalibratedClassifierCV(
        Pipeline([("pre", build_preprocessor_for(cols)), ("clf", make_xgb(best_params, N))]),
        method=best_cal_method, cv=5).fit(trainval[cols], trainval["goal"].to_numpy())
    final = raw_final if choice == "raw" else cal_final

    # ---- 6/8) TEST metrics (touched only now) + overfitting ----
    p_raw_te = raw_final.predict_proba(te[cols])[:, 1]
    m_raw_te = {**evaluate.core_metrics(yte, p_raw_te), "ece": evaluate.expected_calibration_error(yte, p_raw_te)}
    p_cal_te = cal_final.predict_proba(te[cols])[:, 1]
    m_cal_te = {**evaluate.core_metrics(yte, p_cal_te), "ece": evaluate.expected_calibration_error(yte, p_cal_te)}
    p_saved_te = final.predict_proba(te[cols])[:, 1]

    w("\n[8] OVERFITTING DIAGNOSTICS (raw model fit on TRAIN only)")
    w(f"    train: log_loss={m_tr['log_loss']:.5f} brier={m_tr['brier']:.5f} auc={m_tr['roc_auc']:.4f}")
    w(f"    val:   log_loss={m_va['log_loss']:.5f} brier={m_va['brier']:.5f} auc={m_va['roc_auc']:.4f}")
    w(f"    test:  log_loss={m_raw_te['log_loss']:.5f} brier={m_raw_te['brier']:.5f} auc={m_raw_te['roc_auc']:.4f}")
    w(f"    train->test gaps: dLogLoss={m_raw_te['log_loss']-m_tr['log_loss']:+.5f} "
      f"dBrier={m_raw_te['brier']-m_tr['brier']:+.5f} dAUC={m_raw_te['roc_auc']-m_tr['roc_auc']:+.4f}")

    w("\n[6] FINAL TEST METRICS")
    w(f"    RAW XGB:        log_loss={m_raw_te['log_loss']:.5f} brier={m_raw_te['brier']:.5f} auc={m_raw_te['roc_auc']:.4f} ece={m_raw_te['ece']:.4f}")
    w(f"    {best_cal_method} XGB: log_loss={m_cal_te['log_loss']:.5f} brier={m_cal_te['brier']:.5f} auc={m_cal_te['roc_auc']:.4f} ece={m_cal_te['ece']:.4f}")

    rel = evaluate.reliability_table(yte, p_saved_te)
    w(f"\n    RELIABILITY TABLE (saved XGB [{choice}], TEST):")
    w(rel.to_string(index=False))
    xs, ys, ns = evaluate.calibration_points(yte, p_saved_te, n_bins=10)
    plt.figure(figsize=(5, 5)); plt.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    plt.plot(xs, ys, "o-", label=f"XGB ({choice})")
    plt.xlabel("Mean predicted xG"); plt.ylabel("Observed goal rate")
    plt.title("Calibration — XGBoost (test)"); plt.legend(); plt.tight_layout()
    plt.savefig(ROOT / "reports" / "calibration_xgboost.png", dpi=120); plt.close()

    # ---- 2) reduced-feature experiments (fit train, select on val) ----
    w("\n[2] REDUCED-FEATURE EXPERIMENTS (val log loss; best_params reused)")
    experiments = {
        "full FEATURES_A": cols,
        "drop free_kick (redundant w/ shot_type)": [c for c in cols if c != "free_kick"],
        "location: keep distance+angle only": [c for c in cols if c not in ("distance_x", "abs_y_offset")],
        "location: keep distance_x+abs_y_offset+angle (drop distance)": [c for c in cols if c != "distance"],
        "location: keep distance+angle, drop distance_x/abs_y_offset/free_kick": [
            c for c in cols if c not in ("distance_x", "abs_y_offset", "free_kick")],
    }
    exp_rows = []
    for name, ecols in experiments.items():
        _, bi, mv = fit_with_earlystop(ecols, best_params, tr, va)
        exp_rows.append({"experiment": name, "n_feat": len(ecols), "n_est": bi,
                         "val_logloss": round(mv["log_loss"], 5), "val_brier": round(mv["brier"], 5),
                         "val_auc": round(mv["roc_auc"], 4)})
    edf = pd.DataFrame(exp_rows)
    w(edf.to_string(index=False))

    # ---- 11) feature importance ----
    w("\n[11] FEATURE IMPORTANCE")
    pre = raw_final.named_steps["pre"]; clf = raw_final.named_steps["clf"]
    enc_names = list(pre.get_feature_names_out())
    gains = clf.feature_importances_
    imp = pd.DataFrame({"encoded_feature": enc_names, "gain": gains})
    # aggregate one-hot back to original feature
    def orig(n):
        for c in cols:
            if n.endswith(f"__{c}") or f"__{c}_" in n or n == f"num__{c}" or n == f"bin__{c}":
                return c
        return n
    imp["orig"] = imp["encoded_feature"].map(orig)
    agg = imp.groupby("orig")["gain"].sum().sort_values(ascending=False)
    w("    Gain importance aggregated by original feature:")
    for k, v in agg.items():
        w(f"      {k:14s} {v:.4f}")
    # permutation importance on VALIDATION (neg log loss)
    perm = permutation_importance(raw_train_pipe, va[cols], yva, scoring="neg_log_loss",
                                  n_repeats=8, random_state=SEED, n_jobs=1)
    pimp = pd.DataFrame({"feature": cols, "perm_importance": perm.importances_mean,
                         "std": perm.importances_std}).sort_values("perm_importance", ascending=False)
    w("    Permutation importance (val, drop in neg-log-loss; higher = more important):")
    w("    " + pimp.round(5).to_string(index=False).replace("\n", "\n    "))

    # ---- 9) football sanity + symmetry ----
    w("\n[9] FOOTBALL SANITY CHECKS (LR vs XGB)")
    lr_bundle = joblib.load(config.MODELS_DIR / "logistic_baseline.joblib")
    xgb_bundle = {"pipeline": final, "feature_set": "A", "feature_columns": cols, "penalty_xg": pen_xg}
    sanity = train.sanity_shots()
    lr_s = predict_xg(sanity, bundle=lr_bundle)["xg"].to_numpy()
    xgb_s = predict_xg(sanity, bundle=xgb_bundle)["xg"].to_numpy()
    sfeat, _ = F.build_features(sanity, "A")
    for i, r in sanity.iterrows():
        w(f"    {r['label']:26s} dist={sfeat.loc[i,'distance']:5.1f}m angle={sfeat.loc[i,'angle_deg']:5.1f}  "
          f"LR={lr_s[i]:.4f}  XGB={xgb_s[i]:.4f}")
    sym = train.symmetry_shots()
    xs2 = predict_xg(sym, bundle=xgb_bundle)["xg"].to_numpy()
    w(f"    SYMMETRY (XGB): left={xs2[0]:.6f} right={xs2[1]:.6f} |diff|={abs(xs2[0]-xs2[1]):.2e} "
      f"({'PASS' if abs(xs2[0]-xs2[1])<1e-9 else 'FAIL'})")
    # penalty exclusion
    pen_shot = pd.DataFrame([{"shot_x": 108, "shot_y": 40, "body_part": "Right Foot",
                              "shot_type": "Penalty", "assist_type": "none", "assisted": False,
                              "set_piece": True, "free_kick": False, "penalty": True}])
    w(f"    PENALTY routed to constant: xG={predict_xg(pen_shot, bundle=xgb_bundle)['xg'].iloc[0]:.4f} (=pen_xg {pen_xg:.4f})")

    # ---- 10) provider benchmark ----
    w("\n[10] PROVIDER BENCHMARK (StatsBomb xG — reference only)")
    sb = te["statsbomb_xg"].to_numpy()
    for label, preds in [("LR", predict_xg(te, bundle=lr_bundle)["xg"].to_numpy()),
                         ("XGB", p_saved_te)]:
        b = evaluate.provider_benchmark(preds, sb, yte)
        w(f"    {label}: mean_xg={b['mean_internal_xg']:.4f} corr={b['correlation']:.4f} "
          f"MAD={b['mean_abs_diff']:.4f} brier={b['internal_brier']:.4f}")
    w(f"    provider mean_xg={np.nanmean(sb):.4f} provider_brier={evaluate.provider_benchmark(sb, sb, yte)['internal_brier']:.4f}")

    # ---- 12) comparison table ----
    lr_meta = lr_bundle["metadata"]["test_metrics_saved_model"]
    lr_ece = evaluate.expected_calibration_error(yte, predict_xg(te, bundle=lr_bundle)["xg"].to_numpy())
    w("\n[12] MODEL COMPARISON (test set)")
    comp = pd.DataFrame([
        {"model": "LogReg (baseline)", "features": "A (10)", "log_loss": round(lr_meta["log_loss"], 5),
         "brier": round(lr_meta["brier"], 5), "roc_auc": round(lr_meta["roc_auc"], 4), "ece": round(lr_ece, 4),
         "calib": "raw", "train_test_gap": "n/a"},
        {"model": "XGB raw", "features": "A (10)", "log_loss": round(m_raw_te["log_loss"], 5),
         "brier": round(m_raw_te["brier"], 5), "roc_auc": round(m_raw_te["roc_auc"], 4), "ece": round(m_raw_te["ece"], 4),
         "calib": "raw", "train_test_gap": f"dLL={m_raw_te['log_loss']-m_tr['log_loss']:+.4f}"},
        {"model": f"XGB {best_cal_method}", "features": "A (10)", "log_loss": round(m_cal_te["log_loss"], 5),
         "brier": round(m_cal_te["brier"], 5), "roc_auc": round(m_cal_te["roc_auc"], 4), "ece": round(m_cal_te["ece"], 4),
         "calib": best_cal_method, "train_test_gap": "-"},
    ])
    w(comp.to_string(index=False))

    # ---- 14) save candidate ----
    metadata = {
        "model_type": f"XGBClassifier {best_params} n_estimators={N}"
                      + ("" if choice == "raw" else f" + {choice} calibration"),
        "model_version": "xgb-candidate-0.1.0", "checkpoint": 4,
        "training_data_source": "StatsBomb Open Data", "feature_set": "A", "features": cols,
        "target": "goal (non-penalty shots only)", "split": "identical to Checkpoint 3 (match-level, seed=42)",
        "hyperparameters": {**best_params, "n_estimators": N, "subsample": 0.8, "colsample_bytree": 0.8,
                            "reg_alpha": 0.0, "early_stopping_rounds": EARLY},
        "calibration_status": choice, "penalty_xg": float(pen_xg),
        "test_metrics_saved_model": {k: float(v) for k, v in evaluate.core_metrics(yte, p_saved_te).items()},
        "test_metrics_raw": {k: float(v) for k, v in m_raw_te.items()},
        f"test_metrics_{best_cal_method}": {k: float(v) for k, v in m_cal_te.items()},
        "overfitting": {"train": {k: float(v) for k, v in m_tr.items()},
                        "val": {k: float(v) for k, v in m_va.items()},
                        "test": {k: float(v) for k, v in m_raw_te.items()}},
        "vs_logreg_baseline": lr_meta,
    }
    bundle = {"pipeline": final, "feature_set": "A", "feature_columns": cols,
              "penalty_xg": float(pen_xg), "metadata": metadata}
    cand_path = config.MODELS_DIR / "xgboost_candidate.joblib"
    joblib.dump(bundle, cand_path)
    (config.MODELS_DIR / "xgboost_candidate_meta.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    w(f"\n[14] SAVED CANDIDATE: {cand_path}")

    (ROOT / "reports" / "checkpoint4_report.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
