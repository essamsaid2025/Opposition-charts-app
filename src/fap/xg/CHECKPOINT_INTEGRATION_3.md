# Phase 2 · Checkpoint 3 — Data-flow integration (attach internal_xg)

Data-flow only. **No UI. Frozen Internal xG Model v1.0 untouched.** Exactly one
existing file modified.

## 1. Exact integration point
`fap.openplay.transforms.add_derived_columns(df)` — the single derived-frame
enrichment every analysis consumer already calls:
`app.py` (Open Play analysis ×2), `ui/builtin/openplay_studio.py`,
`ui/components/viz_workspace.py`, `scouting/map_filters.py`,
`analytics/tactical/context.py`.

Adding `internal_xg` here means **one shot-level calculation** that all
downstream components reuse — never scattered per chart/tab/team/metric.

## 2. Existing files modified
- **`src/fap/openplay/transforms.py`** — one guarded block appended at the end
  of `add_derived_columns` (see §12). Nothing else changed.

New additive files (no existing code touched):
`src/fap/xg/enrichment.py`, `src/fap/xg/test_integration_flow.py`.

## 3. Why this point
It already has the finalized shot dataframe (coords normalized, `team`,
`event_type`, `body_part`, `set_piece`…), it is reused by multiple analysis
components, and it is a **read-time** transform — so failures can never corrupt
the stored dataset, and enrichment stays a single, central operation.

## 4. Shot dataframe before / after
Unchanged except one appended column:
```
before: … event_type, x, y, team, shot_result, body_part, set_piece,
            distance, is_progressive, shot_distance, time_min, …
after:  … (all of the above, byte-identical) + internal_xg
```
Only `internal_xg` is added. No model internals (distance/angle/distance_x/
abs_y_offset) are exposed — the app already had its own `distance`/`shot_distance`
(unrelated to the model) and those are untouched.

## 5. internal_xg behavior
- Shot rows (`event_type=="shot"`) → frozen model score in [0,1]; penalties →
  frozen penalty xG.
- Non-shot rows → NaN.
- All scoring flows `add_derived_columns → fap.xg.enrichment →
  fap.xg.services.xg_service → frozen model`. No xG formula lives in the app.

## 6. Provider xG preservation
`internal_xg` is a distinct, namespaced column. Existing `shot_xg` / `xg` /
provider metrics are never read or overwritten (test: provider `shot_xg`
preserved and different from `internal_xg`).

## 7. Penalty handling
`set_piece=="penalty"` → frozen `penalty_xg` (0.7255); everything else → model.
Unchanged from Checkpoint 2; verified end-to-end through the derived frame.

## 8. Team / npxG behavior
Downstream aggregates from the shot-level column:
`team_xG = Σ internal_xg`, `npxG = Σ internal_xg over non-penalty shots`
(`team − npxG == penalty_xg` verified). Goals are never used to compute xG.

## 9. Idempotency
`add_derived_columns` recomputes `internal_xg` only if the column is absent, so
repeated processing keeps exactly one `internal_xg` (no `internal_xg_x/_y`,
identical values on the second pass — tested).

## 10. Failure handling
Fully failure-safe: the enrichment is wrapped so that if the frozen package/model
cannot load, coordinates are invalid, or any row is malformed, the affected
values become **NaN** (logged via `logging.warning`) — the app never crashes and
no fake xG is substituted. Invalid coordinate rows → NaN while valid rows in the
same frame are still scored (tested).

## 11. Performance
One vectorized scoring call per frame (shots sliced once, scored in a single
`predict` via `xg_service`). The frozen model bundle is loaded once per process
and cached (`xg.api` cache); frames with no shot rows skip scoring entirely
(model never loaded). Full app suite runtime unchanged (378s vs 388s baseline).

## 12. The change (verbatim)
```python
# appended at the end of add_derived_columns, before `return df`
if "internal_xg" not in df.columns:
    try:
        from fap.xg.enrichment import compute_internal_xg_series
        df["internal_xg"] = compute_internal_xg_series(df)
    except Exception:
        df["internal_xg"] = np.nan
```

## 13. Baseline vs after integration
| | passed | failed |
|---|---|---|
| Baseline (Checkpoint 2, additive only) | 1495 | 15 |
| After integration (Checkpoint 3) | 1495 | 15 |

**Failure set is byte-identical** (`diff` = no change). No new failures; the 15
are the same pre-existing ones (app_shell / identity / openplay_bridge / phase11
/ report_editor / reports / scouting_routing) — none related to xG, none "fixed"
here. Only `src/fap/openplay/transforms.py` was modified (git-verified).

## 14. Integration tests — **60 fap.xg tests pass**
`test_integration_flow.py` (13) covers: derived-frame → internal_xg, existing
columns preserved, provider xG preserved, added exactly once, idempotent
repeats, team & npxG, penalty, malformed coordinate row, missing optional
fields, deterministic, empty frame, multi-match, multi-team, and the key
**app internal_xg == direct `xg_service.score_shots` on the same shot rows**.
Plus the 47 adapter/service/coord tests from Checkpoints 1–2.

## Remaining risks
- Every consumer of `add_derived_columns` (including non-xG contexts like
  scouting/tactical) now carries an unused `internal_xg` column — harmless, but a
  broad reach; acceptable given the single-point mandate.
- Attacking-direction still assumed normalized at import (same assumption all
  existing shot maps make).
- Unlabeled penalties scored as open play (confirmed policy).
