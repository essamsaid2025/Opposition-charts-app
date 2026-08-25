# Bug Fix — Match Stats Comparison xG / NPxG showing zero

## Root cause
The Match Stats Comparison builds per-team metrics in
`fap.visuals.charts.match_flow._team_metrics`, which summed the canonical
`internal_xg` column via `sum_xg` / `sum_npxg`. Those helpers treat a **missing**
`internal_xg` column as empty and return **0.0**. So whenever the frame reaching
this chart had no `internal_xg` column (e.g. a match-statistics file with no
precomputed xG, rendered without the central `add_derived_columns` enrichment),
xG and NPxG displayed as **0** despite real shots.

Confirmed: `sum_xg(shots_without_internal_xg)` → `0.0`, while deriving the column
first → `0.6353` for the same two shots.

## Previous behavior
- No `internal_xg` column → `xG = 0`, `NPxG = 0` (incorrect).
- "Missing source data" was wrongly conflated with "zero xG".

## New fallback behavior
`_team_metrics` now ensures shot-level xG is available before aggregating, using
the existing idempotent helper `fap.xg.enrichment.attach_internal_xg`:

```python
shots = _xg_enrich.attach_internal_xg(shots)   # reuse if present, else derive
xg   = _xg_enrich.sum_xg(shots)                 # Σ internal_xg (incl. penalties)
npxg = _xg_enrich.sum_npxg(shots)               # Σ non-penalty internal_xg
```

- **`internal_xg` present** → reused as-is (idempotent; **not** recalculated).
- **`internal_xg` absent** → derived from the shot rows via the canonical
  `xg_service.score_shots()` (the same frozen model / same pipeline), then summed.
- **Genuinely empty shot set** → still `0` (only real zeros show as zero).

No second xG calculation, no duplicated model/aggregation logic, no hard-coded
values — the fix reuses `attach_internal_xg` / `sum_xg` / `sum_npxg` / the
canonical `internal_xg`.

## Exact data source
Shot-level canonical **`internal_xg`** only. Never goals, shot counts, averages,
Match Stats xG fields, or provider `shot_xg`/`xg`. Per team, aggregation runs on
that team's (already filtered) shot slice, so match/team/period filters are
respected and one team never sums the whole match.

## Penalty handling (unchanged)
A penalty is identified only by the canonical rule `set_piece == "penalty"`; its
xG is the frozen metadata value (`xg_service.penalty_xg()` = 0.7255). Therefore
`xG − NPxG == total penalty xG` when penalties exist. Penalties are never
detected from coordinates.

## Provider xG
Not required and never used. Verified the chart shows correct calculated xG/NPxG
when the file has no `xg`/`shot_xg`/provider column, and that a present provider
value is ignored in favour of `internal_xg`.

## Tests (`src/fap/xg/test_match_stats_fallback.py`, 9 tests)
Covers all required scenarios:
1/2/4 missing xG (and NPxG) with no provider → derived from shots (not 0);
3 present `internal_xg` reused (sentinels 0.40/0.10 → 0.50, not recomputed);
5 provider xG present → ignored; 6 penalty included in xG; 7 penalty excluded
from NPxG (`xG − NPxG == frozen penalty xG`); 8 two teams independent; 9 filter
scope respected (`0 < first-half < full`); 10 empty shot set → `0`; 11
deterministic; 12 existing Match Stats rows unchanged.

## Regression results
| suite | before | after |
|---|---|---|
| fap.xg | 65 passed | **74 passed** (+9 fallback tests) |
| full app suite (genuine) | 1508 passed / **15** genuine failed | 1508 passed / **15** genuine failed |

- The **15 genuine pre-existing failures are unchanged** (identical set; none
  xG-related, none introduced, none fixed).
- The intermittent 16th failure is the known
  `test_platform_bootstrap::test_stale_modules_...` `OSError [WinError 6]`
  `pythonw` subprocess flake (passes in isolation) — unrelated, left untouched.

## UI
No redesign. Only the **data source** for the existing `xG` / `NPxG` rows was
fixed. Rows, labels, and layout are unchanged (test 12 pins the row set).

## Files
- Modified: `src/fap/visuals/charts/match_flow.py` (`_team_metrics` — one
  `attach_internal_xg` call before summing).
- Added: `src/fap/xg/test_match_stats_fallback.py`.
- Frozen model, xG algorithm, `shot_adapter`, `xg_service`, `sum_xg`/`sum_npxg`,
  and all other charts: **untouched**.
