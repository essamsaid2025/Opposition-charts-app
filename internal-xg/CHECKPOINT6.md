# Checkpoint 6 — Final Football Sanity & Production Safety Suite

Full evidence: [`reports/checkpoint6_report.txt`](reports/checkpoint6_report.txt).

**The frozen Internal xG Model v1.0 was NOT retrained or modified.** The only
code added is an **inference-layer input-validation guard** (`src/xg/validation.py`
+ a `on_invalid` option in `predict.py`). The model artifact, features,
preprocessing, hyperparameters, calibration, and penalty handling are unchanged
— verified: v1 predictions equal the reviewed baseline to **max abs diff 0.0e+00**.

## 1. Frozen model integrity ✓
- Loads; `model_version = v1.0`, `frozen = True`.
- Feature list matches metadata and `FEATURES_A`.
- Predictions **deterministic** (identical across runs) and in **[0, 1]**.
- **v1 == reviewed Checkpoint-5 baseline** on the whole test holdout (diff 0.0e+00).

## 2. Coordinate sanity ✓
- `(x, y)` and `(x, 80−y)` give **identical** xG across a full position grid.
- Invalid coordinates are **explicitly handled, never silently scored**:
  | input | flagged | behavior |
  |---|---|---|
  | x<0, x>120, y<0, y>80, x=NaN, y=±inf | yes | `on_invalid="nan"` → xg=NaN; `on_invalid="error"` → raises |
- Near-boundary rounding (e.g. `x=120.2` in real data) is within a 1.0-unit
  tolerance → **passed through raw** (consistent with training), scored normally.
- Documented policy in `validation.py`.

## 3 & 7. Geometry + extreme-shot safety ✓
Distance/angle finite everywhere; angle ∈ [0, π]. Central sweep is **monotonic
non-increasing**. Representative extremes:

| shot | dist | angle° | xG |
|---|---|---|---|
| point-blank central | 0.9 m | 152 | 0.957 |
| ~6 m central | 5.5 m | 67 | 0.565 |
| ~10 m central | 9.1 m | 44 | 0.306 |
| ~20 m central | 20.1 m | 21 | 0.060 |
| ~45 m central | 45.7 m | 9 | 0.0022 |
| ~55 m central | 54.9 m | 8 | 0.0007 |
| byline (angle 0°) | 16.5 m | 0 | 0.027 |

No NaN/inf/negative/`>1` anywhere.

## 4 & 5. Shot types + missing data ✓
Open play, header, free kick, corner, assisted/unassisted all score without
crashing. Missing `assist_type` (→ `"none"`), missing `body_part` (→ imputed),
and even a coordinates-only row are handled by the frozen pipeline's own
imputers — **no invented values**.

## 6. Penalty safety ✓
Penalty shots bypass the open-play model and return the frozen constant
**0.7255**. For a mixed set: **team xG (incl. pen) = 0.4149 + 0.7255 = 1.1404**;
**npxG (excl. pen) = 0.4149**. `team_xG = Σ(xg)` and `npxG = Σ(non-penalty xg)`
verified.

## 8. Realistic sample (test holdout, frozen model)
n=6306 shots, 610 goals. xG min 0.0002 / max 0.948 / mean 0.0964 / median 0.0588;
percentiles [1,5,25,50,75,95,99] = [0.006, 0.013, 0.031, 0.059, 0.111, 0.325, 0.573].
**Σ xG = 608.0 vs 610 actual goals (goals/ΣxG = 1.003)** — reproduces Checkpoint 5
exactly.

## 9. Failure modes ✓
- Empty dataframe → 0 rows with `xg` column; `team_xg = 0.0`.
- Single shot, 20 000 shots, duplicated shots → all valid, in [0,1].
- Unseen categorical values (`body_part="Elbow"`, etc.) → scored via unknown-safe
  encoder, no crash.
- Valid + malformed mix → valid row scored, malformed row = NaN (fails safe).

## 10. Full test suite
**96 passed** (18 features + 10 model + 8 xgboost + 3 frozen + geometry + **the
new safety suite**). No failures.

## Remaining limitations (unchanged from v1.0)
Internal model, not provider xG; no freeze-frame/defender context (by design);
men's-football training sample; penalties a separate constant; per-match xG is
high-variance (reliable in aggregate); tiny categories (direct corners, cutbacks)
have too little data to trust individually.

---

**Internal xG Model v1.0 passed the final football sanity and production safety
suite.**
