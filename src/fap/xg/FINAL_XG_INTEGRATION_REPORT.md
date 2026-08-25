# Final xG Integration Report — End-to-End Acceptance

**Result: ✅ PASS.** The canonical shot-level `internal_xg` is the single source
of truth and produces consistent values across every user-facing xG surface. No
integration inconsistency was found; no code or model changes were made in this
checkpoint (verification only — one additive acceptance test).

## 1. Frozen model version
**Internal xG Model v1.0** (`models/internal_xg_v1.joblib`, read-only) —
LogisticRegression (L2, C=10), raw (no post-hoc calibration). Untouched.

## 2. Data source
StatsBomb Open Data — 1,747 matches / 43,717 shots (43,094 non-penalty). The
app's own event/shot data is the production source; provider xG is not required.

## 3. Shot-level xG source
Every surface reads the single canonical column **`internal_xg`**, attached once
centrally in `fap.openplay.transforms.add_derived_columns` via
`fap.xg.enrichment → fap.xg.services.xg_service → frozen model`. No surface
recomputes xG or calls the model directly.

## 4. Penalty handling
Penalties (`set_piece == "penalty"`) bypass the model and receive the frozen
empirical value **read from model metadata** (`xg_service.penalty_xg()` =
0.7255). Verified: `xG − NPxG == penalty_xg` for a one-penalty team, and the
penalty row's `internal_xg` equals the frozen value (not hard-coded in the test).

## 5. NPxG definition
`NPxG = Σ internal_xg over non-penalty shots`. `xG = Σ internal_xg incl.
penalties`. Never derived from goals, shot counts, or averages.

## 6. UI surfaces (all consume `internal_xg`)
- **Match Stats** (`match_flow._team_metrics`) → per-team **xG** + **NPxG**.
- **compute_metrics / KPI** (`app.compute_metrics`, KPI tile) → **xG** (+ NPxG in
  metrics tables).
- **Shot Map** (`app.panel_shots`) → subtitle total **xG** + marker size by xG.

## 7. End-to-end consistency results
For a fixed representative match/team, the reference computed **directly from the
`internal_xg` column** matched every surface within tolerance:

| Surface | matches reference? |
|---|---|
| Match Stats xG / NPxG | ✅ (round 2dp) |
| compute_metrics xG / NPxG | ✅ (round 2dp) |
| KPI helper `sum_xg` | ✅ (exact) |
| Shot Map subtitle total | ✅ (round 2dp) |
| Team-level = Σ shot-level (xG & NPxG) | ✅ (exact) |

## 8. Filter consistency
First-half filter (`period == 1`) verified: the filtered reference equals the
explicit sum of the filtered shots' `internal_xg`, and Match Stats,
compute_metrics, and the Shot Map subtitle all agree on the reduced scope
(`first-half xG < full-match xG`). Changing the filter changes shot set → xG →
NPxG → every surface, consistently.

## 9. Provider independence
Verified with data carrying **no provider xG values** (the canonical schema's
`shot_xg` slot is entirely empty). All xG surfaces compute correctly from
`internal_xg` alone; provider xG is never required and never used.

## 10. Determinism & immutability
- Repeated calculation/rendering of the same match yields **identical** xG and
  aggregations.
- Rendering Match Stats, compute_metrics, and the Shot Map does **not** mutate
  `internal_xg`, coordinates, `team`, `shot_result`, or `set_piece`.

## 11. Regression results
| | passed | failed |
|---|---|---|
| Baseline (start of this checkpoint) | 1501 | 15 |
| After final acceptance | 1508 | 16* |

- **+7 vs baseline passed** = the 8 new acceptance tests minus the 1 flaky
  bootstrap test that intermittently fails in the loaded suite.
- The **15 genuine failures are identical to the pre-existing set** (app_shell /
  identity / openplay_bridge / phase11 / report_editor / reports /
  scouting_routing) — none xG-related, none introduced, none "fixed."
- *The 16th is `test_platform_bootstrap::test_stale_modules_...`, failing with
  `OSError [WinError 6] The handle is invalid` at `subprocess.run` under
  `pythonw` — an environmental windowless-subprocess flake. It **passes in
  isolation** (confirmed 5/5 across runs) and touches neither xG code nor any
  file changed in Phase 2. Left untouched as instructed.
- **65 fap.xg tests pass**; **8 acceptance tests pass**.

## 12. Known limitations
- Static Shot Map has no per-shot hover; xG detail is via marker size + goal
  labels + subtitle.
- No per-chart "Size by xG" toggle (Open Play controls are global).
- Attacking direction assumed normalized at import (same assumption as every
  existing shot map).
- Unlabeled penalties are scored as open play (confirmed policy — penalty only
  when `set_piece == "penalty"`).
- Shot Map excludes shots with missing plot coordinates; such shots also carry
  NaN `internal_xg` (→ 0 contribution), so totals stay consistent across surfaces.
- PNG byte-size baselines are environment-specific (matplotlib/font versions).

---

**Acceptance: the internal xG integration is end-to-end consistent. Success.**
