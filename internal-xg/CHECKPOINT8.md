# Checkpoint 8 — Production Inference API & Reproducibility

Full evidence: [`reports/checkpoint8_report.txt`](reports/checkpoint8_report.txt).
The frozen **Internal xG Model v1.0 was NOT retrained or modified** (artifact is
now read-only). No Streamlit code was touched.

## 1. Final API (`xg.api`)
The single public surface a consuming app imports:

| function | returns |
|---|---|
| `predict_xg(shots, on_invalid="nan")` | copy of `shots` + `xg` column (input not mutated) |
| `calculate_team_xg(shots, by=None)` | Σ xG (incl. penalties); per-group Series with `by` |
| `calculate_npxg(shots, by=None)` | Σ non-penalty xG |
| `model_info()` / `input_schema()` | metadata / input contract |
| `penalty_xg()` | frozen penalty value from metadata |
| `load(model_path=…)` | cached bundle (target a specific version) |

## 2. One source of truth
`api` → `predict` → `features.build_features` / `preprocessing`. Training and
inference call the **same** feature functions — no duplicated distance/angle/
categorical/missing-value logic. Verified by
`test_feature_consistency_training_vs_inference` (inference scores exactly what
`features.build_features` produces, to 1e-12).

## 3. Input contract
Required: `shot_x`, `shot_y`. Recommended: `penalty` (absent → non-penalty).
`goal`/`outcome` only for historical evaluation, never inference. Optional:
`body_part`, `shot_type`, `assist_type`, `assisted`, `set_piece`, `free_kick`.
Accepted values and missing-value policy documented in README §12 and
`api.input_schema()`.

## 4. Coordinate contract
StatsBomb **120×80 attacking-direction** (goal centre 120,40). The API **never
silently flips/rescales**; a different upstream system must be converted by an
explicit adapter first. (README §13.)

## 5. Validation (kept from Checkpoint 6)
Invalid coords (NaN/inf/off-pitch beyond 1.0 tol) never silently scored:
`on_invalid="nan"` → `xg=NaN` for those rows (valid rows in the same batch still
scored); `on_invalid="error"` → raises.

## 6. Penalty handling
Read from metadata (`api.penalty_xg()` = **0.7255**), not hard-coded. Penalties
bypass the model; non-penalty shots use v1.0.

## 7. Team xG & 8. npxG
`team_xg = Σ shot xg` (verified equal to the summed column, not derived from
counts/averages/goals); supports `by="team"`. `npxg = Σ non-penalty xg` — penalty
xG never contributes. Example: team xG 1.4359 = npxG 0.7104 + penalty 0.7255.

## 9. Metadata exposed
`model_info()` returns model_version, model_type, training_data_source,
training_matches (1747), training_shots (43,717), features, hyperparameters,
calibration_method, penalty_xg, training_date, **package_versions**, frozen
status, final metrics, limitations.

## 10. Determinism ✓
Same input → same xG across repeated calls, save/load, **and a separate Python
process** (identical SHA-256 hash `0112f50a…`).

## 11. Performance (vectorized)
| shots | total | per shot |
|---|---|---|
| 1 | 7.5 ms | — (fixed overhead) |
| 20 | 7.6 ms | 381 µs |
| 100 | 8.7 ms | 86 µs |
| 1,000 | 8.0 ms | 8.0 µs |
| 10,000 | 19.6 ms | **1.96 µs** |
Per-shot cost falls sharply with batch size — the model is called **once per
batch**, not once per shot.

## 12. Tests — **107 passed**
Added `test_api.py` (import, predict, no-mutation, empty/one/many, missing
optional, unseen categories, invalid + mixed rows, penalty from metadata, team
xG, grouped team xG, npxG, determinism + cache, metadata, schema, train↔inference
feature consistency) on top of geometry / model / xgboost / safety / frozen tests.

## 13. Reproducibility
`README.md` finalized (project purpose, xG meaning, data source, 1747 matches /
43,717 shots, features, freeze-frame exclusion rationale, LR selection rationale,
metrics, calibration, penalty handling, retrain commands, load & predict
examples, input schema, coordinate system, limitations).

## 14. Training vs production inference
Cleanly separated: training scripts build/evaluate/freeze a version; `xg.api`
does validation → exact feature pipeline → frozen model → xG, importing no
training code. Production never retrains.

## 15. Immutability & versioning policy
`models/internal_xg_v1.joblib` (+ meta) set **read-only**. A future model becomes
`internal_xg_v2.joblib` — never overwriting v1; `api.load(model_path=…)` selects
a version.

## Final files (this checkpoint)
- `src/xg/api.py` — public inference API
- `tests/test_api.py` — API test suite
- `scripts/checkpoint8_report.py` — benchmarks/metadata/examples/determinism
- `README.md` (finalized), `CHECKPOINT8.md`
- `models/internal_xg_v1.joblib` locked read-only

The standalone, production-ready Internal xG inference package is complete. No
integration with the Streamlit application was performed.
