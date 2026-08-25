"""Train + evaluate + save the Logistic Regression baseline (Checkpoint 3).

Usage (from internal-xg/):
    python scripts/train_baseline.py

Writes:
    models/logistic_baseline.joblib      (pipeline + metadata bundle)
    models/logistic_baseline_meta.json   (human-readable metadata)
    reports/checkpoint3_report.txt       (full text report)
    reports/calibration_baseline.png     (calibration curve)
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import config, evaluate, features as F, train  # noqa: E402
from xg.predict import predict_xg  # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)


def main() -> None:
    config.ensure_dirs()
    lines: list[str] = []
    w = lambda *a: lines.append(" ".join(str(x) for x in a))

    res, ctx = train.run_baseline(feature_set="A", seed=config.RANDOM_SEED)
    cols = res.feature_columns
    primary = ctx["primary"]
    train_part, val_part, test_part = primary["train"], primary["val"], primary["test"]
    raw_final = ctx["raw_final"]
    final = res.final_pipeline

    # ---- 1. splits ----
    w("=" * 70); w("CHECKPOINT 3 — LOGISTIC REGRESSION BASELINE"); w("=" * 70)
    w("\n[1] MATCH-LEVEL SPLIT (primary, seeded, representative)")
    w(res.splits_desc.to_string(index=False))
    w("\n    CHRONOLOGICAL SPLIT (robustness, time-ordered)")
    w(res.chrono_desc.to_string(index=False))
    w("\n[2] FEATURES (FEATURES_A, no Group B, no provider xG):")
    w("    " + ", ".join(cols))

    # ---- 3. hyperparameter tuning ----
    w("\n[3] HYPERPARAMETER TUNING (LogReg L2; selected by validation log loss)")
    tdf = pd.DataFrame(res.tuning)[["C", "log_loss", "brier", "roc_auc"]].round(5)
    w(tdf.to_string(index=False))
    w(f"    -> selected C = {res.best_C}")

    # ---- 7. calibration decision on validation ----
    w("\n[7] CALIBRATION INVESTIGATION (decided on VALIDATION only)")
    for k, v in res.calibration_val.items():
        w(f"    {k:9s}  log_loss={v['log_loss']:.5f}  brier={v['brier']:.5f}  "
          f"roc_auc={v['roc_auc']:.4f}  ece={v['ece']:.4f}")
    w(f"    -> chosen: {res.calibration_choice.upper()}")

    # ---- final TEST evaluation (raw vs calibrated) : test used only here ----
    Xte, yte = test_part[cols], test_part["goal"].to_numpy()
    p_raw = raw_final.predict_proba(Xte)[:, 1]
    m_raw = evaluate.core_metrics(yte, p_raw)

    # best calibrator (for a raw-vs-calibrated test comparison)
    best_cal_method = min(("sigmoid", "isotonic"),
                          key=lambda mth: res.calibration_val[mth]["log_loss"])
    cal_final = train.fit_final(ctx["trainval"], cols, res.best_C,
                                calibration=best_cal_method, feature_set="A")
    p_cal = cal_final.predict_proba(Xte)[:, 1]
    m_cal = evaluate.core_metrics(yte, p_cal)

    w("\n[4-6] FINAL TEST-SET METRICS (untouched until now)")
    w(f"    RAW  LR:        log_loss={m_raw['log_loss']:.5f}  brier={m_raw['brier']:.5f}  roc_auc={m_raw['roc_auc']:.4f}")
    w(f"    {best_cal_method:>3} calibrated: log_loss={m_cal['log_loss']:.5f}  brier={m_cal['brier']:.5f}  roc_auc={m_cal['roc_auc']:.4f}")
    w(f"    test mean pred (raw) = {m_raw['mean_pred']:.4f}   test base rate = {m_raw['base_rate']:.4f}")

    # which model is saved
    saved_p = final.predict_proba(Xte)[:, 1]
    m_saved = evaluate.core_metrics(yte, saved_p)
    w(f"    SAVED model ({res.calibration_choice}): log_loss={m_saved['log_loss']:.5f}  "
      f"brier={m_saved['brier']:.5f}  roc_auc={m_saved['roc_auc']:.4f}  ece={evaluate.expected_calibration_error(yte, saved_p):.4f}")

    # ---- reliability table (saved model, on test) ----
    w("\n[6] RELIABILITY TABLE (saved model, TEST set)")
    rel = evaluate.reliability_table(yte, saved_p)
    w(rel.to_string(index=False))

    # calibration curve plot
    xs, ys, ns = evaluate.calibration_points(yte, saved_p, n_bins=10)
    plt.figure(figsize=(5, 5))
    plt.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    plt.plot(xs, ys, "o-", label=f"baseline ({res.calibration_choice})")
    plt.xlabel("Mean predicted xG"); plt.ylabel("Observed goal rate")
    plt.title("Calibration — LR baseline (test)"); plt.legend(); plt.tight_layout()
    plt.savefig(ROOT / "reports" / "calibration_baseline.png", dpi=120)
    plt.close()

    # ---- 8. interpretability ----
    w("\n[8] COEFFICIENTS & ODDS RATIOS (raw LR, fit train+val)")
    coef = train.coefficient_table(raw_final)
    w("    Numeric coefs are per +1 SD (features standardised). Absolute per-level")
    w("    categorical coefs are non-identifiable vs the intercept; see the")
    w("    reference-relative table below for interpretable categorical effects.")
    w(coef.round(4).to_string(index=False))
    # Reference-relative categorical coefficients (identifiable differences).
    w("\n    Categorical effects vs reference level (log-odds & odds ratio):")
    ref_coefs = train.reference_relative_coefs(raw_final, F.CATEGORICAL_A, train_part)
    for col, info in ref_coefs.items():
        w(f"      {col}  (reference = '{info['reference']}')")
        for r in info["rows"]:
            tag = "  <- reference" if r["is_reference"] else ""
            w(f"        {r['level']:14s} coef_vs_ref={r['coef_vs_ref']:+.4f}  OR={r['odds_ratio']:.3f}{tag}")

    # ---- 9. multicollinearity ----
    w("\n[9] MULTICOLLINEARITY (numeric features)")
    corr = train_part[F.NUMERIC_A].corr().round(3)
    w("    Correlation matrix:")
    w(corr.to_string())
    w("    VIF:")
    w(train.vif_table(train_part, F.NUMERIC_A).to_string(index=False))

    # ---- 10. football sanity checks ----
    w("\n[10] FOOTBALL SANITY CHECKS (saved model)")
    sanity = train.sanity_shots()
    scored = predict_xg(sanity, bundle={"pipeline": final, "feature_set": "A",
                                        "feature_columns": cols, "penalty_xg": res.penalty_xg})
    sfeat, _ = F.build_features(sanity, "A")
    for i, r in scored.iterrows():
        w(f"    {r['label']:26s} dist={sfeat.loc[i,'distance']:5.1f}m "
          f"angle={sfeat.loc[i,'angle_deg']:5.1f}deg  xG={r['xg']:.4f}")

    sym = train.symmetry_shots()
    sym_scored = predict_xg(sym, bundle={"pipeline": final, "feature_set": "A",
                                         "feature_columns": cols, "penalty_xg": res.penalty_xg})
    diff = abs(sym_scored["xg"].iloc[0] - sym_scored["xg"].iloc[1])
    w(f"    SYMMETRY: left xG={sym_scored['xg'].iloc[0]:.6f}  "
      f"right xG={sym_scored['xg'].iloc[1]:.6f}  |diff|={diff:.2e}  "
      f"({'PASS' if diff < 1e-9 else 'FAIL'})")

    # ---- 11. provider benchmark (non-penalty test shots) ----
    w("\n[11] PROVIDER BENCHMARK (StatsBomb xG — REFERENCE ONLY, not a target)")
    bench = evaluate.provider_benchmark(saved_p, test_part["statsbomb_xg"].to_numpy(), yte)
    for k, v in bench.items():
        w(f"    {k}: {round(v,4) if isinstance(v,float) else v}")

    # ---- 12. save model + metadata ----
    metadata = {
        "model_type": f"LogisticRegression (L2, C={res.best_C})"
                      + ("" if res.calibration_choice == "raw" else f" + {res.calibration_choice} calibration"),
        "model_version": "baseline-0.1.0",
        "checkpoint": 3,
        "trained_at": ctx["trained_at"],
        "training_data_source": "StatsBomb Open Data",
        "competition_selection": [lbl for _, _, lbl in config.COMPETITION_SELECTION],
        "feature_set": "A",
        "features": cols,
        "target": "goal (non-penalty shots only)",
        "excluded_from_features": ["statsbomb_xg", "outcome", "penalties", "Group B features"],
        "split": {
            "type": "match-level (primary) + chronological (robustness)",
            "fracs": [0.70, 0.15, 0.15],
            "seed": config.RANDOM_SEED,
            "primary": res.splits_desc.to_dict(orient="records"),
            "chronological": res.chrono_desc.to_dict(orient="records"),
        },
        "hyperparameters": {"C": res.best_C, "penalty": "l2", "solver": "lbfgs", "max_iter": 5000},
        "calibration_status": res.calibration_choice,
        "penalty_xg": res.penalty_xg,
        "penalty_estimate": {k: (float(v) if isinstance(v, (int, float, np.floating)) else v)
                             for k, v in ctx["penalty_estimate"].items()},
        "test_metrics_saved_model": {k: float(v) for k, v in m_saved.items()},
        "test_metrics_raw": {k: float(v) for k, v in m_raw.items()},
        f"test_metrics_{best_cal_method}": {k: float(v) for k, v in m_cal.items()},
        "provider_benchmark": {k: (float(v) if isinstance(v, float) else v) for k, v in bench.items()},
    }
    bundle = {
        "pipeline": final,
        "feature_set": "A",
        "feature_columns": cols,
        "penalty_xg": float(res.penalty_xg),
        "metadata": metadata,
    }
    model_path = config.MODELS_DIR / "logistic_baseline.joblib"
    joblib.dump(bundle, model_path)
    (config.MODELS_DIR / "logistic_baseline_meta.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    w(f"\n[12] SAVED: {model_path}")
    w(f"     META:  {config.MODELS_DIR / 'logistic_baseline_meta.json'}")

    report_path = ROOT / "reports" / "checkpoint3_report.txt"
    report_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
