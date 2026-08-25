# Internal xG Model

An **independent Expected Goals (xG) model** that predicts `P(goal | shot
characteristics)` for football shots, trained on **actual historical shot
outcomes** from public event data.

> This is **our own internal model**. It is **NOT** Opta xG, StatsBomb xG, or
> Wyscout xG. Provider xG is used only as an external benchmark, never as a
> training label or feature.

- **Status:** Internal xG Model **v1.0 — FINAL & FROZEN**.
- **Model:** regularized Logistic Regression (L2, C=10), raw (well-calibrated,
  no post-hoc calibration needed).
- **Standalone:** no dependency on, and no changes to, the Streamlit application.

---

## 1. What this project does

Given a dataframe of shots (location + a few optional descriptors), it returns a
calibrated goal probability (`xg ∈ [0, 1]`) per shot, and aggregates to team xG
and non-penalty xG (npxG).

## 2. What xG means

Expected Goals is the modelled probability that a shot becomes a goal, given its
characteristics. Summed over shots it estimates how many goals a set of chances
"should" yield. A 0.10 xG shot scores ~10% of the time; team xG ≈ Σ shot xG.

## 3. Training data

- **Source:** [StatsBomb Open Data](https://github.com/statsbomb/open-data)
  (free, reputable; no paid provider).
- **Selection:** 4 leagues 2015/16 (La Liga, Premier League, Serie A, Ligue 1)
  + FIFA World Cup 2018 & 2022 + UEFA Euro 2020 & 2024.
- **Volume:** **1,747 matches, 43,717 shots** (43,094 non-penalty), non-penalty
  goal base rate **9.46%**.
- Raw JSON is cached **outside git and outside the OneDrive folder**
  (`~/.cache/statsbomb_open_data`, override with `XG_CACHE_DIR`). Only the small
  processed table is kept in `data/processed/`.

Full schema & coordinate documentation: [`DATASET.md`](DATASET.md).

## 4. Features (`FEATURES_A`, 10)

Only features **reproducible from our own future internal shot data** are used
(classified "A"; see [`FEATURES.md`](FEATURES.md)).

| feature | definition |
|---|---|
| `distance` | √((120−x)²+(40−y)²)·0.9144 (m) to goal centre |
| `angle` | goal-mouth opening subtended by the posts (rad) |
| `distance_x` | (120−x)·0.9144 (m) |
| `abs_y_offset` | \|y−40\|·0.9144 (m) — symmetric |
| `body_part` | Right Foot / Left Foot / Head / Other |
| `shot_type` | Open Play / Free Kick / Corner |
| `assist_type` | none / pass / cross / through_ball / cutback |
| `assisted`, `set_piece`, `free_kick` | boolean flags |

## 5. Why freeze-frame was excluded

StatsBomb ships a `freeze_frame` (positions of all defenders + the goalkeeper at
shot time). It is powerful but **cannot be reproduced from our future internal
tagging data**, so features like "defenders in the shot cone" or "distance to
GK" are deliberately **excluded** — the model only uses signals we can recreate
at inference. This is the main reason provider xG has slightly better
discrimination.

## 6. Why Logistic Regression was selected

XGBoost was trained and compared fairly (same split, same features). Its test
gains were **within cross-validation noise** (Δlog-loss ≈ 0.0008, within ±1σ),
while LR was **better calibrated** and **monotonic / smooth at extreme
distances** (XGBoost plateaus and can tick up at long range). Under the priority
order calibration → Brier → log loss → robustness → sanity → simplicity →
reproducibility, **LR wins**. Details: [`CHECKPOINT4.md`](CHECKPOINT4.md),
[`CHECKPOINT5.md`](CHECKPOINT5.md).

## 7. Evaluation (untouched test holdout)

| metric | value |
|---|---|
| Log Loss | 0.2650 |
| Brier | 0.0751 |
| ROC-AUC | 0.7878 |
| ECE / MCE | 0.0081 / 0.0245 |
| calibration slope / in-the-large | 0.988 / 0.004 |

Aggregate: Σ test xG **608.0 vs 610 actual goals** (ratio 0.997).

## 8. Calibration

Raw LR is already well-calibrated (slope ≈ 1, ECE ≈ 0.008; Platt/isotonic did
not improve validation performance), so **no post-hoc calibration is applied**.
Reliability tables and curves: `reports/`.

## 9. Penalty handling

Penalties are a **separate process**, never sent through the model. Each penalty
gets the frozen **empirical** value **0.7255** (452/623 converted; Wilson 95% CI
[0.689, 0.759]), read from the model metadata (not hard-coded in code).
- **xG** = model(non-penalty) + 0.7255 per penalty
- **npxG** = model(non-penalty) only

---

## 10. Installation

```bash
cd internal-xg
pip install -r requirements.txt
```
Verified on Python 3.14 (win_amd64) with scikit-learn 1.9, xgboost 3.4.1.

## 11. Load the frozen model & run predictions

```python
import pandas as pd
from xg import api   # add internal-xg/src to sys.path, or install the package

shots = pd.DataFrame([
    {"shot_x": 114, "shot_y": 40, "body_part": "Right Foot",
     "shot_type": "Open Play", "assist_type": "pass", "assisted": True,
     "set_piece": False, "free_kick": False, "penalty": False},
])

scored = api.predict_xg(shots)          # adds an 'xg' column (input not mutated)
total  = api.calculate_team_xg(shots)   # sum of xG (incl. penalties)
npxg   = api.calculate_npxg(shots)      # sum of non-penalty xG
info   = api.model_info()               # model metadata for display
api.calculate_team_xg(shots, by="team") # per-team Series if a 'team' column exists
```

## 12. Input schema (`api.input_schema()`)

**Required:** `shot_x`, `shot_y` (coordinates). **Recommended:** `penalty`
(bool; absent → all treated as non-penalty). `goal`/`outcome` are needed only
for historical evaluation, never for inference.

**Optional** (missing values handled inside the frozen pipeline — nothing is
invented): `body_part`, `shot_type`, `assist_type`, `assisted`, `set_piece`,
`free_kick`.

Accepted categorical values:
- `body_part`: Right Foot, Left Foot, Head, Other
- `shot_type`: Open Play, Free Kick, Corner, Penalty
- `assist_type`: none, pass, cross, through_ball, cutback

Unknown categorical values are accepted safely (one-hot `handle_unknown=ignore`).
Missing `assist_type` → `"none"`; missing `body_part`/`shot_type` → imputed;
missing flags → `False`.

## 13. Coordinate contract

The API expects **StatsBomb-compatible 120 × 80 attacking-direction
coordinates**: the shooting team attacks toward `x = 120`, goal centre `(120,
40)`, posts at `y = 36`/`44`. The API **does not silently flip or rescale**
coordinates. If a consuming application uses a different coordinate system, it
**must convert to this system with an explicit adapter before calling** the API.

## 14. Validation (`on_invalid`)

Coordinates missing, non-finite, or off-pitch beyond a 1.0-unit tolerance are
**invalid** and never silently scored:
- `on_invalid="nan"` (default) → those rows get `xg = NaN`; valid rows in the
  same batch are still scored.
- `on_invalid="error"` → raises `ValueError`.

## 15. Retrain (build a NEW model version)

Production inference **never retrains**. To rebuild from scratch:

```bash
cd internal-xg
python scripts/build_dataset.py       # download + extract shots -> data/processed/
python scripts/train_baseline.py      # LR baseline + metrics + reliability
python scripts/train_xgboost.py       # XGBoost comparison experiment
python scripts/evaluate_checkpoint5.py# deep calibration/robustness analysis
python scripts/freeze_model.py        # freeze the chosen model artifact
```

Full pipeline: download/load → extract shots → clean → feature engineering →
match-level split → train → evaluate → (calibrate if justified) → select →
freeze.

## 16. Training vs production inference

- **TRAINING** (scripts above): raw public data → dataset → features → train →
  evaluate → **freeze a new version**. Uses `train.py`, `data_loader.py`.
- **PRODUCTION INFERENCE** (`xg.api`): shot dataframe → validation → **exact
  same** feature pipeline (`features.py`) → frozen model → xG. No training code
  is imported or executed.

Both paths call the **same** `features.build_features` / `preprocessing` — one
source of truth for every formula.

## 17. Model versioning & immutability

- The frozen artifact `models/internal_xg_v1.joblib` is set **read-only** and
  must not be overwritten.
- A future model is saved as **`internal_xg_v2.joblib`** (new version, new
  metadata) — never overwriting v1. `api.load(model_path=...)` can target a
  specific version.

## 18. Known limitations

- Internal model; not equivalent to commercial provider xG.
- No defender/goalkeeper (freeze-frame) context — by design, for internal
  reproducibility.
- Trained on **men's** football (leagues 2015/16 + WC 2018/22 + Euro 2020/24).
- Penalties are a fixed constant, not modelled.
- Per-match xG is high-variance (corr with goals ~0.41 at match level); the model
  is reliable **in aggregate** (team/competition level).
- Tiny categories (direct-corner shots, cutback assists) have too little data to
  trust individually.

## 19. Project layout

```
internal-xg/
├── data/processed/         # small processed shot table (raw JSON cached elsewhere)
├── models/                 # internal_xg_v1.joblib (frozen) + candidates + metadata
├── reports/                # metrics, reliability tables, calibration plots
├── src/xg/                 # config, data_loader, features, preprocessing,
│                           # splits, train, evaluate, calibration-in-evaluate,
│                           # predict, validation, api
├── scripts/                # build_dataset, train_baseline, train_xgboost,
│                           # evaluate_checkpoint5, freeze_model, checkpoint8_report
├── tests/                  # 107 tests (geometry, model, xgboost, safety, api, frozen)
├── DATASET.md  FEATURES.md  CHECKPOINT3..8.md
└── requirements.txt  README.md
```

## 20. Tests

```bash
cd internal-xg
python -m pytest tests -q      # 107 passing
```
