# Phase 2 · Checkpoint 2 — shot_adapter + xg_service wiring

Backend-only. **No UI. Frozen Internal xG Model v1.0 untouched.** The only app
change is the new, isolated `src/fap/xg/` subpackage (zero existing files
modified — verified via `git status`).

## Architecture
```
app canonical shots df
      │  fap.xg.shot_adapter.to_xg_input   (semantic mapping + coord_adapter)
      ▼
xG API input df
      │  fap.xg.services.xg_service        (isolated sys.path insert -> xg.api)
      ▼
frozen Internal xG Model v1.0  →  internal_xg
```
`shot_adapter` is the ONLY place app column names/semantics map to xG fields.
`xg_service` is the ONLY place that imports the standalone `xg` package.

## 1. Input mapping (shot_adapter)
| app column | xG field | rule |
|---|---|---|
| `x`,`y` | `shot_x`,`shot_y` | via `coord_adapter` (no math duplicated) |
| `set_piece` | `penalty`/`free_kick`/`set_piece`/`shot_type` | see below |
| `body_part` | `body_part` | value map (below) |
| `assisted`/`assist`/`key_pass` + `assist_type` | `assisted`,`assist_type` | see below |
| `team`,`opponent`,`match_id`,`player`,`minute`,… | carried context | not features |
| `shot_result` | `goal` (0/1) | eval/display only, never a feature |

## 2. No duplicated model logic
`shot_adapter` computes **no** distance/angle/distance_x/abs_y_offset/encoding/
probability. It prepares raw semantic inputs only; the frozen `xg` package owns
all model math and aggregation.

## 3. Penalty behavior (exact)
`set_piece == "penalty"` → `penalty=True`, `shot_type="Penalty"` → frozen
penalty xG. Everything else → `penalty=False` → normal model. Never inferred
from location/distance/outcome/scoreline. Unknown/unlabeled ⇒ non-penalty.
- `free kick`/`free_kick`/… → `Free Kick`, `free_kick=True`, `set_piece=True`.
- `corner` → `Open Play` + `set_piece=True` (matches training: corner shots are
  Open Play with a From-Corner phase).
- else → `Open Play`, all flags False.

## 4. Assist fallback (exact)
`assisted` = OR of `assisted`/`assist`/`key_pass`. Then:
- known `assist_type` (normalized: `through ball`→`through_ball`, `cut back`→
  `cutback`, etc.) → preserved.
- assisted & unknown/missing type → `"pass"`.
- not assisted & unknown/missing → `"none"`.
Specific types (cross/through_ball/cutback) are **never** inferred.

## 5. Coordinate adapter usage
Delegates entirely to the Checkpoint-1 `coord_adapter` (`x*1.2`, `80−y*0.8`).
Source `x`/`y` untouched; non-numeric → NaN (no fabrication/clipping).

## 6. Categorical mapping (body_part)
`head`→Head; `foot`/`weak_foot`/`strong_foot`→Right Foot (model reference foot;
feet are near-identical in the model); `left foot`→Left Foot; `right foot`→Right
Foot; `""`/missing→NaN (frozen pipeline imputes); any other non-empty token→
`Other` (the model's genuine catch-all — not a random assignment). Unknown
`shot_type`/`assist_type` tokens fall back safely as documented above.

## 7. Required data & missing-value behavior
`x`/`y` are required — `to_xg_input` raises `ValueError` if absent (no fabricated
coordinates). Invalid coordinates (off-pitch/NaN after conversion) flow to the
frozen API's `on_invalid="nan"` path → `internal_xg = NaN`, valid rows still
scored. All optional descriptors use the frozen model's documented missing-value
behavior.

## 8. Service API (`services/xg_service.py`) — app-native only
- `score_shots(df)` → copy of `df` + `internal_xg` column (never mutates caller;
  no existing columns removed/renamed). Output column is **`internal_xg`** to
  avoid colliding with provider `shot_xg`/`xg`.
- `calculate_team_xg(df, by=None)` → Σ shot xG (incl. penalties); per-group with `by`.
- `calculate_npxg(df, by=None)` → Σ non-penalty xG.
- `get_xg_model_info()` → plain dict of frozen metadata.
- `penalty_xg()` → frozen empirical penalty value.

Isolation: the single `sys.path` insertion of `internal-xg/src` lives only here;
`xg.api`/`xg.predict`/`xg.features` are never imported elsewhere in the app, and
no `xg.*` object crosses the boundary (only dataframes / floats / dicts).

## 9. Dataframe immutability
`score_shots` returns a `.copy()` + new column; the caller's frame is unchanged
(tested). `shot_adapter.to_xg_input` also never mutates its input (tested).

## 10. Team xG / npxG
Both delegate to the frozen API's aggregation (`calculate_team_xg` /
`calculate_npxg`) — never recomputed. Verified `team_xG = Σ shot xG` and
`npxG = Σ non-penalty xG`, and `team − npxG = penalty_xg` for one penalty.

## 11. Tests — **47 xG-integration tests pass**
- `test_coord_adapter.py` (10, Checkpoint 1).
- `test_shot_adapter.py` (19): open play, penalty (label-only), unlabeled set
  piece, free kick, assist known/unknown/none, through-ball normalization,
  body-part map, coordinates/symmetry/boundary/center, missing-coord raise,
  immutability, context carry, shot filter.
- `test_xg_service.py` (18): scoring range, no-mutation, no columns
  removed/renamed, penalty = frozen value, **service == direct frozen API**,
  team xG = sum, npxG excludes penalty, grouped multi-team, invalid → NaN,
  mixed valid/invalid, left/right symmetry, determinism, metadata dict.

## 12. No UI
No cards, charts, columns in visible UI, filters, buttons, or Streamlit widgets
were added. Backend only.

## 13. Backward compatibility
Existing app suite: **1495 passed, 15 failed**. `git status` confirms **no
existing tracked file was modified** (only the new untracked `src/fap/xg/`), so
all 15 failures are **pre-existing** and unrelated to xG (they live in
app_shell / identity / openplay_bridge / phase11 / report_editor / reports /
scouting_routing — none of which this isolated subpackage touches). No unrelated
code was refactored.

## Deliverables
- `src/fap/xg/shot_adapter.py`
- `src/fap/xg/services/__init__.py`, `src/fap/xg/services/xg_service.py`
- `src/fap/xg/test_shot_adapter.py`, `src/fap/xg/test_xg_service.py`
- `src/fap/xg/CHECKPOINT_INTEGRATION_2.md`
