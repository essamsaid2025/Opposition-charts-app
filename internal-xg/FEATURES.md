# Feature Engineering (Checkpoint 2)

Implemented in [`src/xg/features.py`](src/xg/features.py); tested in
[`tests/test_features.py`](tests/test_features.py) (18 tests, all passing).

## Design rules honoured

- **Penalties are a separate process** — excluded from the main model.
- **Only Group A features** (reproducible from our future internal shot data)
  are eligible for the production model. Group B is offline-only.
- **Geometry is left/right symmetric** — mirror-image shots get identical
  features (lateral info enters only via `abs_y_offset` and the post `angle`).
- **No leakage** — `goal`, `outcome`, `statsbomb_xg` can never be features
  (`assert_no_leakage` guards every feature list).
- Raw StatsBomb 120×80 coordinates are kept in the dataset; modelling features
  are *derived* from them.

## Numerical features (all Group A)

Goal centre = (120, 40); posts = (120, 36) & (120, 44). StatsBomb units treated
as yards → metres via ×0.9144. Angles in radians.

| Feature | Formula | Meaning | A/B |
|---|---|---|---|
| `distance` | `sqrt((120−x)² + (40−y)²) · 0.9144` | straight-line distance to goal centre (m) | A |
| `angle` | `arccos( (v₁·v₂) / (‖v₁‖‖v₂‖) )`, with `v₁ = P_left − shot`, `v₂ = P_right − shot` | goal-mouth opening seen from the shot (rad) | A |
| `distance_x` | `(120 − x) · 0.9144` | longitudinal distance to goal line (m) | A |
| `abs_y_offset` | `|y − 40| · 0.9144` | lateral distance from centre line (m); absolute → symmetric | A |

`angle_deg` is derived for interpretability only and is **not** a model feature.

### Angle method & symmetry

The angle is the geometric opening subtended by the two posts, via the
normalized dot product of the vectors from the shot to each post (cos clipped to
[−1,1], denominator ε-guarded so on-line/at-post shots are finite). It is
provably symmetric: `angle(x, y) == angle(x, 80 − y)`, so a shot and its mirror
across the pitch centre produce equal angles. This is asserted in
`test_angle_symmetry_mirror_about_centre` over a grid of positions, and
cross-checked against an independent `atan2` computation.

## Categorical features

| Feature | Levels (observed) | A/B |
|---|---|---|
| `body_part` | Right Foot, Left Foot, Head, Other | A |
| `shot_type` | Open Play, Free Kick, Corner (Penalty routed out) | A |
| `assist_type` | none, pass, cross, through_ball, cutback | A |
| `technique` | Normal, Volley, Half Volley, Lob, Overhead Kick, Backheel, Diving Header | **B** |
| `play_pattern` | Regular Play, From Corner/Free Kick/Throw In/Counter/… | **B** |

## Binary flags

| Feature | Meaning | A/B |
|---|---|---|
| `assisted` | shot created by a key pass | A |
| `set_piece` | penalty OR free-kick shot OR play_pattern ∈ {From Corner, From Free Kick} | A |
| `free_kick` | direct free-kick shot | A |
| `one_on_one` | keeper 1v1 (SB freeze-frame derived) | **B** |
| `first_time` | struck first time | **B** |
| `open_goal` | empty net | **B** |
| `aerial_won` | won aerial duel before shot | **B** |
| `follows_dribble` | shot after a dribble | **B** |

## Feature sets

- **`FEATURES_A` (production, 10 features):** `distance, angle, distance_x,
  abs_y_offset, body_part, shot_type, assist_type, assisted, set_piece,
  free_kick`.
- **`FEATURES_ALL` (A + B, experimentation only):** adds `technique,
  play_pattern, one_on_one, first_time, open_goal, aerial_won, follows_dribble`.

The final production model will use **only `FEATURES_A`**. `FEATURES_ALL` is
kept so later checkpoints can quantify how much B features would add (and
confirm we are not leaving large, *reproducible* signal on the table).

## Missing-value handling

- `assist_type` missing = *unassisted* → mapped to the explicit `"none"`
  category (semantic, not imputed).
- Boolean flags coerced to real bools; absent B columns on internal data are
  created as neutral defaults (`False` / `"missing"`) so the same code path runs.
- Numeric geometry is always computable (shots without location were dropped in
  Checkpoint 1). Any residual gaps are handled by **statistical imputation
  inside the saved preprocessing pipeline** (Checkpoint 3), so imputation
  travels with the model rather than living in ad-hoc feature code.

## Penalty handling design

- `split_penalties(df)` → `(non_penalty, penalty)`. The main model trains and
  predicts on `non_penalty` only.
- `estimate_penalty_xg(df)` returns an **empirical** penalty xG (not
  hard-coded). On the training data: **0.7255** (452/623), Wilson 95% CI
  **[0.689, 0.759]**. This value will be stored in model metadata; `predict`
  will assign it to penalty shots.
- This enables the architecture to expose both:
  - **xG** = model(non-penalty) summed + penalty_xg per penalty
  - **npxG** = model(non-penalty) summed only

## Leakage audit

Feature lists are validated by `assert_no_leakage`, which rejects any list
containing `goal`, `outcome`, or `statsbomb_xg`. Context columns (`player`,
`team`, `minute`, `match_id`, …) are never added to feature lists. No feature
encodes the shot result directly or indirectly. (`open_goal` — the only flag
that correlates strongly with scoring — describes a *pre-shot* condition, is
Group B, and is excluded from the production set regardless.)
