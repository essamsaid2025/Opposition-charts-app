# Phase 2 · Checkpoint 5 — Shot Map xG enhancement

Approved intentional visual change. Frozen Internal xG v1.0 untouched. Reads only
the canonical `internal_xg` column; the chart never calls the model or
recomputes xG.

## Shot Map changes (`app.panel_shots`)
The legacy Shot Map is a **static matplotlib** panel (no hover tooltip). xG is
surfaced three ways, all from `internal_xg`:

1. **Marker size = xG** (visual encoding).
2. **Goal detail labels** now include the xG value (the existing per-shot detail
   mechanism, shown when "show players" is on): `"Striker (xG 0.62)"`.
3. **Subtitle** shows the total: `"Shots: N | xG: X.XX | Marker size = xG"`.

Preserved exactly:
- shot **coordinates** (the frame is copied; `x`/`y`/`x_plot`/`y_plot` untouched),
- **goal vs miss** colour/zorder encoding,
- legend and all other markers.

If `internal_xg` is absent, the panel **falls back** to the previous
distance-proxy sizing and old subtitle — so xG-less data renders exactly as
before.

## Marker-size scaling (documented)
```
size_mult = clip(0.6 + 2.2 * xG, 0.6, 2.6)
```
- `size_mult` multiplies the base marker **area** (matplotlib `s`), so area
  scales ~linearly with xG.
- **Floor 0.6×** keeps low/zero-xG shots clearly visible.
- **Cap 2.6×** stops a very high-xG shot (e.g. a penalty at 0.73) from dominating.
- Goals use the same per-shot scaling (their own xG), keeping the goal colour +
  raised zorder for distinction.
- Coordinates are never derived from or altered by xG.

## Tooltip / detail behavior
No interactive tooltip exists on this static chart, so — per "use the existing
formatting conventions" — xG is added to the existing **goal player-labels** and
the **subtitle**. No model internals (distance/angle/coefficients/probability
components) are exposed. There is no duplicate xG field.

## Optional toggle
Skipped. The Open Play controls are global (not per-chart), so a clean
"Size by xG" toggle would require non-trivial control-plumbing refactoring. Per
the checkpoint guidance, the toggle was omitted; xG-by-size is the default when
`internal_xg` is present (and auto-falls back otherwise).

## Baseline update (verified isolated)
`tests/test_openplay_studio.py::test_run_app_still_byte_identical_baseline` pins
exact PNG byte-sizes. Updated **only** the Shot Map entry:

| map | before | after | changed? |
|---|---|---|---|
| Pass Map | 217328 | 217328 | no (byte-identical) |
| **Shot Map** | **60455** | **53460** | **yes (intended xG sizing)** |
| Carry Map | 193492 | 193492 | no (byte-identical) |

Verified by rendering all three exactly as the test does: **only the Shot Map
size changed**; Pass/Carry are byte-identical, so this baseline update masks no
unrelated regression. The test was **not** removed or weakened — only the one
expected number was updated, with a documented comment.

## Validation (`tests/test_shot_map_xg.py`, 6 tests)
- penalty shot → `internal_xg` == frozen `penalty_xg` (0.7255); normal shot →
  model value in [0,1];
- marker sizes vary with xG and have a sensible minimum;
- subtitle + goal label contain "xG";
- repeated render is deterministic (byte-identical);
- coordinates unchanged;
- missing/NaN `internal_xg` renders safely (no crash, floor size).

## Regression results
| | passed | failed |
|---|---|---|
| Before (pre-Phase-2) | 1495 | 15 |
| After Checkpoint 5 | **1501** | **15** |

- **Failure set identical** to the pre-Phase-2 baseline (`diff` = no change);
  **no new failures**.
- +6 passed = the new `test_shot_map_xg.py`.
- The known `test_platform_bootstrap::test_stale_modules_...` **WinError 6
  pythonw flake did NOT recur** this run; it remains an environmental subprocess
  flake (passes in isolation), unrelated to xG and left untouched.
- **65 fap.xg tests pass.**

## Existing files modified (this checkpoint)
- `app.py` — `panel_shots`: xG marker sizing + goal-label xG + subtitle (with
  fallback). No other UI changed (Match Stats / KPI / aggregation from CP4 are
  as-approved and untouched).
- `tests/test_openplay_studio.py` — Shot Map baseline number only, documented.

New: `tests/test_shot_map_xg.py`.

## Remaining limitations
- Static chart → no per-shot hover; xG detail is via size + goal labels +
  subtitle.
- No per-chart "Size by xG" toggle (global-controls limitation).
- Attacking-direction still assumed normalized at import (as every shot map does).
- PNG byte-size baselines are environment-specific (matplotlib/font versions);
  the updated number matches this project's environment.
