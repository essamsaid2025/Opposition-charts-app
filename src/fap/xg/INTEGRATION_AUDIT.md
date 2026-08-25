# Phase 2 · Checkpoint 1 — Application Data Audit (xG integration)

Read-only audit of the existing FAP app to plan integration of the frozen
**Internal xG Model v1.0**. No existing app logic modified; the only code added
is the isolated, tested coordinate adapter.

## 1. Existing shot data flow
```
upload/import  →  ImportService/pipeline  →  coordinate normalization (once)
              →  canonical event frame  →  WorkspaceManager.active_frame(user)
              →  legacy_active_frame(ctx)  →  Open Play engine / charts
```
- Import maps any vendor into ONE canonical schema + coordinate space; nothing
  downstream sees vendor coordinates (`fap/pipeline/coordinates.py`,
  `schema.py`, `pipeline.py`).
- Attacking direction is normalized **at import** via the `flip_direction`
  option (`transforms.flip_left_to_right`); canonical is always attack L→R.
- The single source of truth at runtime is
  `WorkspaceManager.active_frame(user)`, reached via
  `fap.ui.dataset_bridge.legacy_active_frame(ctx)`.
- Shots are identified everywhere as `event_type.str.lower() == "shot"`
  (helper: `fap.visuals.analysis.shots(df)`).

## 2. Existing shot dataframe schema (canonical)
Defined in `fap/pipeline/schema.py`. Relevant columns for a shot row:

| canonical column | meaning | example values |
|---|---|---|
| `event_type` | event kind | `"shot"` |
| `x`, `y` | location (canonical 0–100) | x≈83–100, y 0–100 |
| `end_x`,`end_y`/`x2`,`y2` | shot end | 100,50 |
| `shot_result` | shot outcome | `Goal`, `Saved`, `Off Target`, `off_target` |
| `outcome` | generic outcome | `successful`, … |
| `body_part` | coarse | `foot`, `head`, `weak_foot` |
| `set_piece` | dead-ball origin (text) | `""`, `corner`, `free kick`, `penalty` |
| `sub_event`, `play_pattern`, `phase` | context | often empty |
| `key_pass`, `assist` | assist flags (bool) | True/False |
| `team`, `opponent` | both present per row | `Team A` / `Team B` |
| `player`, `minute`, `second`, `period`, `match_id` | context | |
| `shot_xg` | **provider xG** (when present) | 0.2 |

## 3. Coordinate system analysis
| | App canonical | xG model (StatsBomb) |
|---|---|---|
| x range | 0–100 | 0–120 |
| y range | 0–100 | 0–80 |
| attacked goal | x = 100 | x = 120 |
| goal centre | (100, 50) | (120, 40) |
| y origin | 0 = right touchline | 0 = a touchline (top-down) |
| direction | attack L→R (normalized at import) | attack toward x=120 (source-normalized) |

The app's StatsBomb→canonical rule is `x/120*100, (80−y)/80*100`. **The adapter is
its exact inverse** → `shot_x = x*1.2`, `shot_y = 80 − y*0.8`. Goal centre
(100,50)→(120,40). (Model geometry is y-symmetric, so the y-flip cannot change
xG, but the adapter does it correctly anyway.)

## 4. Team / opposition handling
Every event row carries both `team` and `opponent`. Open Play filters
(`OPEN_PLAY_FILTERS`) select by `team`/`opponent`/`match_id`. Team xG will group
by the existing `team` column — no new opposition concept needed.

## 5. Complete mapping — canonical → xG API input
| app column | xG field | transformation | req/opt | notes |
|---|---|---|---|---|
| `x` | `shot_x` | `x*1.2` (coord adapter) | **required** | implemented |
| `y` | `shot_y` | `80 − y*0.8` (coord adapter) | **required** | implemented |
| `shot_result` | `goal` | `== "goal"` | eval/display only | **never** an inference input |
| `body_part` | `body_part` | `head→Head`; `foot`/`weak_foot`→`Right Foot`; `left/right foot`→exact; `""`→missing | optional | app is coarse; feet ≈ equivalent in model |
| `set_piece` | `shot_type` + flags | `penalty→penalty=True`; `free kick→shot_type="Free Kick",free_kick=True,set_piece=True`; `corner→set_piece=True, shot_type="Open Play"`; else `Open Play` | optional | matches training semantics (corner shots were Open Play + From Corner) |
| `key_pass`/`assist` | `assisted`,`assist_type` | assisted = flag; `assist_type` = `"pass"` if assisted else `"none"` | optional | see missing fields |
| `team` | (grouping) | passthrough | — | for team xG |
| `opponent`,`match_id`,`player`,`minute` | (context) | passthrough | — | not features |
| `shot_xg` | (benchmark) | passthrough, **not used** | — | provider xG, reference only |

## 6. Missing fields (app does NOT have — do NOT invent)
- **`assist_type` categories** (cross / through_ball / cutback): unavailable →
  assisted shots use generic `"pass"`; unassisted `"none"`. Loses the through-ball
  premium; safe (API missing-value policy). Documented gap.
- **Right vs Left foot**: app has generic `foot`/`weak_foot` → single foot
  category. Model treats feet near-identically (OR≈0.96) → negligible.
- **Penalty flag**: only present if `set_piece == "penalty"`. Penalties largely
  live in the separate set-pieces subsystem, so most open-play frames have none;
  unlabeled → scored as open play. Flagged as a review item.
- Group-B qualifiers (one-on-one, first_time, …) are not used by the model.

## 7. Required transformations
1. filter `event_type == "shot"` (reuse `visuals.analysis.shots`).
2. coordinate adapter (implemented + tested).
3. `body_part` value map.
4. `set_piece` → `shot_type`/`set_piece`/`free_kick`/`penalty` derivation.
5. `assisted`/`assist_type` derivation from `key_pass`/`assist`.

## Confirmed design decisions (locked for Checkpoint 2)
1. **Package wiring:** `sys.path` insertion of `internal-xg/src`, **isolated
   inside a service module** (`services/xg_service.py`). The frozen package is
   NOT modified, the model is NOT vendored/copied, and `xg.*` internals are NOT
   exposed to the Streamlit app — the service re-exposes only app-native
   functions (score shots / team xG / npxG / model info).
2. **Penalty policy:** treat as penalty ONLY when `set_piece == "penalty"`;
   unlabeled shots are scored as open play (no location heuristic, no fabrication).
3. **Assist mapping:** assisted shots with unknown type → `assist_type = "pass"`
   (generic assisted category); unassisted → `"none"`.

## 8. Proposed integration point
A new, additive `fap.xg` subpackage — nothing existing is modified:
- `coord_adapter.py` — **created + tested** (this checkpoint).
- `shot_adapter.py` *(next)* — canonical shots → xG API input df (steps 3–5).
- `service.py` *(next)* — imports the standalone `xg` package and calls
  `xg.api.predict_xg / calculate_team_xg / calculate_npxg / model_info`, returning
  a scored frame. **Output column named `internal_xg`** (not `xg`) to avoid
  colliding with the provider `shot_xg`/`xg` columns.
Reads shots from `legacy_active_frame(ctx)`; delegates ALL scoring to the frozen
API (single source of truth). UI comes later.

**Wiring the frozen package (for review):** the standalone `xg` package lives in
`internal-xg/src`. Recommended: `service.py` inserts `internal-xg/src` on
`sys.path` once (least invasive; the frozen model path resolves relative to the
package). Alternative: `pip install -e internal-xg` (needs a small `pyproject`).

## 9. Files to create
- `src/fap/xg/__init__.py` ✓
- `src/fap/xg/coord_adapter.py` ✓
- `src/fap/xg/test_coord_adapter.py` ✓ (10 tests pass)
- *(next)* `shot_adapter.py`, `service.py`, and their tests.

## 10. Files that must NOT be modified
`app.py`; anything under `fap/ui`, `fap/visuals`, `fap/pipeline`, `fap/openplay`,
`fap/state`; the canonical schema/column names; and the entire frozen
`internal-xg/` package + `internal_xg_v1.joblib`.

## 11. Coordinate adapter (implemented)
`fap/xg/coord_adapter.py` — pure (no fap imports). `to_xg_coordinates(df)` adds
`shot_x`/`shot_y`, leaves source `x`/`y` untouched, non-numeric → NaN (no
invention/clipping). Tests cover: goal centre, pitch centre, both goal lines,
both touchlines, attacking direction, left/right symmetry, boundary coords,
round-trip vs the app's StatsBomb rule, and no-mutation.

## 12. Risks / edge cases
- **Attacking-direction assumption:** xG requires canonical attack→x=100 (same
  assumption every existing shot map already makes). Data imported without the
  correct `flip_direction` would score toward the wrong goal → document/guard.
- **Unlabeled penalties** scored as open play (0.09 vs 0.73). Review item.
- **Column collision:** output as `internal_xg` to avoid clobbering provider
  `shot_xg`/`xg`.
- **Coarse `body_part` / missing `assist_type`:** modest, documented under-use of
  signal; never fabricated.
- **Missing/off-pitch coords** → NaN → handled by the API's `on_invalid` layer.
