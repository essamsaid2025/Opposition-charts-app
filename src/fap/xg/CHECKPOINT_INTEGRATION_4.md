# Phase 2 · Checkpoint 4 — Surface xG in the UI (canonical "xG")

`internal_xg` (backend column) is displayed to users as **"xG"**; non-penalty as
**"NPxG"**. All surfaces consume the canonical shot-level `internal_xg` column —
no chart recomputes xG, and none derives it from goals / shot counts / averages.
Provider `shot_xg`/`xg` is never required and never overwritten. Frozen model
untouched.

## Shot-based component audit
| Component | uses shot data? | expose xG? | representation | done |
|---|---|---|---|---|
| **Match Stats table** (`visuals/charts/match_flow._team_metrics`) | yes | **yes** | per-team **xG** + **NPxG** rows (was provider `shot_xg` → now canonical `internal_xg`) | ✅ |
| **Metrics dict / tables / summary cards** (`app.compute_metrics`) | yes | **yes** | **xG** + **NPxG** metrics (feed comparison tables, per-match frames) | ✅ |
| **Analysis KPI row** (`app.run_app`) | yes | **yes** | new **"xG"** KPI tile (sum of `internal_xg`) | ✅ |
| **Shot Map** (`app.panel_shots`) | yes | *deferred* | marker-size-by-xG is analytically ideal but mutating this figure breaks the pinned byte-identical baseline (`test_run_app_still_byte_identical_baseline`). Deferred pending reviewer approval to update that baseline. | ⏸ |
| Shot Result bar (`app.panel_shot_summary`) | yes | no | pure outcome breakdown; xG adds no analytical value here | — |
| Sequence / match-flow markers (`app` viz_*) | yes | no | goal/shot event markers; xG not meaningful per marker | — |
| Momentum / xT (`match_flow`) | no (xT) | no | different metric | — |
| Heat/pass/carry/defensive maps | no (non-shot) | no | not shot-level | — |

Guiding rule applied: add xG where it is a meaningful shot-derived metric
(team/match aggregates, KPI, stats table); do **not** force it into charts where
it makes no analytical sense.

## What was implemented
1. **Match Stats (comparison table)** — `_team_metrics` now sums the canonical
   `internal_xg` for **xG** (incl. penalties) and adds **NPxG** (non-penalty);
   the provider `shot_xg` dependency was removed. Per-team xG & NPxG as required.
2. **`compute_metrics`** — adds `"xG"` and `"NPxG"` (from `internal_xg`), so
   every metrics table / summary card / per-match comparison surfaces them.
   `HIGHER_BETTER` updated (both higher-is-better).
3. **Analysis KPI row** — a 7th KPI tile **"xG"** (`Σ internal_xg`).

All three use two pure aggregation helpers added to `fap.xg.enrichment`:
`sum_xg` (Σ internal_xg incl. penalties) and `sum_npxg` (Σ over non-penalty
shots, penalties identified by `set_piece == "penalty"`). These only sum the
existing column — no model call.

## Terminology
- Backend column: **`internal_xg`** (unchanged).
- User-facing: **"xG"** (canonical) and **"NPxG"**.
- "Internal xG" reserved for the model-info context (Checkpoint 2 `model_info`),
  not the analysis surfaces.

## No provider dependency
`internal_xg` is the sole source. If a provider `shot_xg`/`xg` exists it is left
untouched as an unrelated field and is never required (test:
`test_match_stats_uses_internal_xg_not_provider` proves provider values are
ignored).

## xG / NPxG definitions (as implemented)
- **xG** = `Σ internal_xg` over the team's shots, **including** penalties (each
  penalty contributes the frozen 0.7255).
- **NPxG** = `Σ internal_xg` over the team's **non-penalty** shots.
- Never from goals, shot counts, or averages.

## Existing files modified (this checkpoint)
- `app.py` — import of `sum_xg`/`sum_npxg`; `compute_metrics` +xG/+NPxG;
  `HIGHER_BETTER` +xG/+NPxG; one added KPI tile. (`panel_shots` was edited then
  fully reverted — no net change.)
- `src/fap/visuals/charts/match_flow.py` — `_team_metrics` xG source + NPxG,
  one import.

(`src/fap/openplay/transforms.py` was the Checkpoint-3 change, unchanged here.)

## Tests
- **65 fap.xg tests pass** — incl. new `test_ui_surfacing.py` (sum_xg includes
  penalties, sum_npxg excludes them, NaN-safe, missing-column → 0, Match Stats
  uses internal_xg not provider).
- Byte-identical guard `test_run_app_still_byte_identical_baseline` **still
  passes** (shot-map figure left unchanged).
- Targeted consumers (match report visuals, comparison charts, phase13 viz,
  data engine, openplay studio/migration) all pass.

## Baseline accounting
| | passed | failed |
|---|---|---|
| Baseline (before Phase 2) | 1495 | 15 |
| After Checkpoint 4 | 1494 | 16 |

The one extra "failure" is `test_platform_bootstrap.py::
test_stale_modules_are_dropped_so_a_redeploy_recovers_in_process` — it fails in
the loaded suite with `OSError [WinError 6] The handle is invalid` at
`subprocess.run(..., capture_output=True)`, a `pythonw` windowless-subprocess
flake. It **passes 3/3 in isolation** and touches neither xG code nor any file I
changed (bootstrap/subprocess). Not attributable to this checkpoint. The 15
genuine pre-existing failures are unchanged (identical set, none xG-related,
none "fixed").

## Remaining / follow-ups
- **Shot Map xG encoding** (marker size = xG, xG in subtitle) is prepared but
  deferred to avoid unilaterally rewriting the byte-identical baseline; ready to
  enable with reviewer sign-off to update that one baseline number.
- Attacking-direction still assumed normalized at import (same as all shot maps).
