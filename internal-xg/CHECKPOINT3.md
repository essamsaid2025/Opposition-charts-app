# Checkpoint 3 — Logistic Regression Baseline

Full machine-generated log: [`reports/checkpoint3_report.txt`](reports/checkpoint3_report.txt).
Calibration curve: [`reports/calibration_baseline.png`](reports/calibration_baseline.png).
Model: [`models/logistic_baseline.joblib`](models/logistic_baseline.joblib) (+ `_meta.json`).

## Split (match-level, no shot leakage)

| split | matches | shots | goals | goal_rate |
|---|---|---|---|---|
| train | 1223 | 30139 | 2858 | 0.0948 |
| val | 262 | 6649 | 608 | 0.0914 |
| test | 262 | 6306 | 610 | 0.0967 |

Penalties (623) excluded from the model → separate empirical xG **0.7255**.
A chronological (time-ordered) split is also reported as a robustness reference.

## Model

- **LogisticRegression, L2, C = 10** (selected by validation log loss; curve is
  very flat, C∈[1,10] near-identical).
- **Calibration: RAW** — raw LR beat Platt/isotonic on validation
  (val log loss raw 0.24745 vs sigmoid 0.24754; isotonic worse). Already
  well-calibrated (val ECE 0.0089).
- Features: `FEATURES_A` only. No Group B, no `statsbomb_xg`, no penalties.

## Test-set metrics (untouched until final)

| model | log loss | Brier | ROC-AUC |
|---|---|---|---|
| **Raw LR (saved)** | **0.2650** | **0.0751** | **0.7878** |
| sigmoid-calibrated | 0.2649 | 0.0751 | 0.7878 |

Mean predicted xG 0.0964 ≈ base rate 0.0967; test ECE 0.0081. Reliability table
is monotonic with observed≈predicted in every bin.

## Interpretability (all football-sensible)

- `distance` OR 0.248 per +1 SD → farther = less likely ✓
- `angle` OR 1.52 per +1 SD → wider goal opening = more likely ✓
- body_part (ref Right Foot): **Head OR 0.34**, Left Foot 0.96 ✓
- assist_type (ref pass): **through_ball OR 3.41**, cross 0.84, none 0.74 ✓
- shot_type (ref Open Play): Free Kick/Corner positive *at matched geometry*
  (dead-ball strikes are unopposed; distance already handled separately).

### Caveats reported honestly
- **Numeric multicollinearity:** `distance` VIF 72.8, `distance_x` VIF 55 (they
  are algebraically related). Individual numeric coefficients are therefore not
  stable to interpret in isolation, but predictions/calibration are unaffected
  (kept per the brief — not auto-removed).
- **Categorical redundancy:** `free_kick` ≡ `shot_type==Free Kick`, and
  `set_piece` partially overlaps both; the fitted effect is split across them.
  Net predictions remain sensible (validated by sanity check F).
- Absolute per-level one-hot coefficients are non-identifiable vs the intercept
  (encoder keeps all levels for unseen-category safety) → reference-relative
  coefficients reported instead.

## Football sanity checks (saved model)

| scenario | dist | angle | xG |
|---|---|---|---|
| A close central foot | 5.5 m | 67° | 0.565 |
| D medium central header | 9.1 m | 44° | 0.128 |
| F free kick 25 m central | 22.9 m | 18° | 0.093 |
| C close tight-angle | 21.7 m | 5° | 0.018 |
| B long central foot | 32 m | 13° | 0.012 |
| E long-distance | 45.7 m | 9° | 0.002 |

Ordering A > D > F > C > B > E is correct. **Left/right symmetry: exact
(|diff| = 0).**

## Provider benchmark (reference only)

Mean internal xG 0.0964 vs StatsBomb 0.0939; correlation **0.812**; mean abs
diff 0.0375. On test, provider Brier 0.0701 vs ours 0.0751 — StatsBomb is
slightly better, expected since they use freeze-frame (defender/GK) features we
deliberately excluded for internal reproducibility. Not a training target.

## Reproduce

```bash
cd internal-xg
python scripts/train_baseline.py
```
