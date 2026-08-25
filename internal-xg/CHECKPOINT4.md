# Checkpoint 4 — XGBoost Advanced Model (experiment)

Full log: [`reports/checkpoint4_report.txt`](reports/checkpoint4_report.txt).
Candidate: [`models/xgboost_candidate.joblib`](models/xgboost_candidate.joblib) (+ `_meta.json`).
Calibration curve: [`reports/calibration_xgboost.png`](reports/calibration_xgboost.png).

**This is an experiment. XGBoost is NOT declared the production model.**

## Setup (fair comparison)
Identical Checkpoint-3 match-level split (seed=42), identical `FEATURES_A` (10),
identical one-hot preprocessing. No Group B, no `statsbomb_xg`, no freeze-frame,
no post-shot info.

## Configuration
Grid search over 24 conservative configs (early stopping on val). Selected:
`max_depth=5, learning_rate=0.05, min_child_weight=5, reg_lambda=5.0,
subsample=0.8, colsample_bytree=0.8, reg_alpha=0`, **n_estimators=141**.
Calibration: raw beat sigmoid/isotonic on validation → **RAW chosen**.

## Head-to-head on the untouched test set

| model | features | Log Loss | Brier | ROC-AUC | ECE | calib |
|---|---|---|---|---|---|---|
| **LogReg (baseline)** | A (10) | 0.26495 | 0.07512 | 0.7878 | **0.0081** | raw |
| XGB raw | A (10) | **0.26370** | **0.07500** | **0.7899** | 0.0095 | raw |
| XGB isotonic | A (10) | 0.26365 | 0.07500 | 0.7898 | 0.0091 | isotonic |

Differences are within noise: ΔLogLoss −0.0013, ΔBrier −0.0001, ΔAUC +0.002.
**LR is better calibrated** (ECE 0.008 vs 0.0095).

## Overfitting
Train 0.2517 / val 0.2454 / test 0.2637 log loss; train→test ΔLogLoss +0.012,
ΔBrier +0.003, ΔAUC −0.024. Small, healthy gaps — the conservative config is
**not overfitting**.

## Reduced-feature experiments (val log loss)
| experiment | n_feat | val log loss |
|---|---|---|
| full FEATURES_A | 10 | 0.24541 |
| drop free_kick | 9 | 0.24560 |
| keep distance+angle only | 8 | 0.24597 |
| drop distance (keep distance_x+abs_y_offset+angle) | 9 | 0.24562 |
| keep distance+angle, drop distance_x/abs_y_offset/free_kick | 7 | 0.24592 |

Redundant features neither help nor hurt (all within 0.0006). `free_kick` has
~zero permutation importance — safe to drop but no benefit; kept for consistency.

## Feature importance
- **Permutation (val, most reliable):** angle 0.032 > distance 0.021 >
  body_part 0.013 > assist_type 0.007 > set_piece 0.004 > distance_x 0.003 >
  abs_y_offset 0.001 > shot_type 0.001 > assisted ≈ 0 ≈ free_kick.
- **Gain:** body_part 0.32, assist_type 0.23, angle 0.14, distance 0.135, …
  (gain over-weights higher-cardinality categoricals — permutation is the more
  trustworthy view.)

The model relies primarily on **geometry (angle, distance)** — football-sensible.

## Football sanity (LR vs XGB)
| scenario | LR | XGB |
|---|---|---|
| A close central foot (5.5 m) | 0.565 | 0.403 |
| D central header (9 m) | 0.128 | 0.112 |
| F free kick (23 m) | 0.093 | 0.063 |
| C tight-angle | 0.018 | 0.028 |
| B long central (32 m) | 0.012 | 0.0085 |
| E very long (46 m) | 0.0022 | 0.0081 |

- Symmetry: **exact (|diff|=0)**. Penalty correctly routed to constant 0.7255.
- **XGB extrapolates worse at the extremes** (trees plateau): it is more
  conservative on the very close central shot and shows near-flat, slightly
  non-monotonic values for 32 m vs 46 m. LR's linear-in-distance form stays
  monotonic out of range — a point in LR's favour for football robustness.

## Provider benchmark (reference only)
LR corr 0.812, Brier 0.0751; XGB corr 0.810, Brier 0.0750; provider Brier 0.0701.
Essentially tied; both trail StatsBomb, expected (they use freeze-frame features
we deliberately exclude).

## Verdict
**XGBoost does NOT meaningfully outperform Logistic Regression.** Accuracy gains
are within noise, and LR is better calibrated, simpler, and extrapolates more
sensibly at long range. Under the selection criteria (calibration → Brier →
log loss → generalization → sanity → simplicity → reproducibility), **LR remains
the preferred production model**. XGBoost is retained as a valid candidate
(`xgboost_candidate.joblib`) for the formal selection in a later checkpoint, not
declared final here.

## Tests
`36 passed` — added XGB prediction range, missing values, unseen categories,
save/load consistency, symmetry, penalty exclusion, team-xG aggregation.
