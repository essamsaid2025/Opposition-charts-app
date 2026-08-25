# Training Dataset & Schema (Checkpoint 1)

## 1. Source

**StatsBomb Open Data** — free, reputable, publicly available football event
data, served as raw JSON from
`https://github.com/statsbomb/open-data`.

We access three endpoints (all cached locally, see below):

| File | Purpose |
|------|---------|
| `competitions.json` | catalogue of available competition/season pairs |
| `matches/{competition_id}/{season_id}.json` | match list + metadata for a season |
| `events/{match_id}.json` | full event stream for one match (we keep only `Shot` events) |

### Competition selection (default)

Chosen for a large, modern, mostly homogeneous **men's** football sample with
good league + tournament + set-piece variety. Edit
`src/xg/config.COMPETITION_SELECTION` to change scope, then re-run the build.

| Competition | Season | ~Matches |
|-------------|--------|----------|
| La Liga | 2015/2016 | 380 |
| Premier League | 2015/2016 | 380 |
| Serie A | 2015/2016 | 380 |
| Ligue 1 | 2015/2016 | 377 |
| FIFA World Cup | 2018 | 64 |
| FIFA World Cup | 2022 | 64 |
| UEFA Euro | 2020 | 51 |
| UEFA Euro | 2024 | 51 |
| **Total** | | **~1,747 matches** (~40k shots) |

### Caching / git policy

- Raw event JSON (several GB) is cached under `~/.cache/statsbomb_open_data`
  (override with `XG_CACHE_DIR`). It is **outside git and outside the
  OneDrive-synced project folder** to avoid multi-GB sync churn.
- Only the small processed table (`data/processed/shots.csv[.parquet]`,
  a few MB) is written into the project and may be committed.

## 2. Coordinate system

StatsBomb pitch = **120 × 80** units. The data is stored so that the shooting
team **always attacks toward `x = 120`**; the attacked goal is therefore fixed:

- Goal centre: **(120, 40)**
- Left post: (120, 36); Right post: (120, 44) → goal width 8 units
- Verified empirically: shot `end_location` x-values cluster at 120.

Because attacking direction is already consistent in the raw data, no
left/right flipping is required. Distance/angle geometry is derived in
`features.py` relative to the fixed goal. StatsBomb units are treated as yards
for human-readable distances (× 0.9144 → metres); angles are unit-less.

## 3. Target variable

**`goal` ∈ {0, 1}** = `1` iff `shot.outcome.name == "Goal"`, else `0`.

The model learns `P(goal | shot features)` **only** from these actual outcomes.

> `statsbomb_xg` is carried through as a column but is used **exclusively** as
> an external benchmark in evaluation. It is never a feature and never a target.

## 4. Column dictionary

One row per shot. Columns fall into four groups.

### Identifiers / context (not model features)

| Column | Definition | Source |
|--------|-----------|--------|
| `match_id` | StatsBomb match id | match file |
| `competition` | competition name | match file |
| `season` | season name | match file |
| `match_date` | date of match | match file |
| `team` | shooting team | event `team.name` |
| `player` | shooter | event `player.name` |
| `minute`, `second`, `period` | shot time | event |

### Geometry (raw coords; normalised in `features.py`)

| Column | Definition | Source | Future-internal? |
|--------|-----------|--------|------------------|
| `shot_x` | StatsBomb x of shot (0–120, toward goal) | event `location[0]` | **Yes** (we tag shot location) |
| `shot_y` | StatsBomb y of shot (0–80) | event `location[1]` | **Yes** |

### Target

| Column | Definition | Source |
|--------|-----------|--------|
| `goal` | 1 if goal else 0 | `shot.outcome.name` |
| `outcome` | raw outcome (Goal/Saved/Off T/…) — kept for audit, not a feature | `shot.outcome.name` |

### Qualitative descriptors (candidate features)

| Column | Definition | Source | Future-internal? |
|--------|-----------|--------|------------------|
| `body_part` | Right/Left Foot, Head, Other | `shot.body_part.name` | **Yes** (tagged) |
| `shot_type` | Open Play / Penalty / Free Kick / Corner / Kick Off | `shot.type.name` | **Yes** |
| `technique` | Normal/Volley/Half Volley/Lob/Overhead/Backheel/Diving Header | `shot.technique.name` | Partial (subjective; optional tag) |
| `play_pattern` | possession origin (Regular Play, From Corner, From Free Kick, From Throw In, From Counter, …) | event `play_pattern.name` | **Yes** (derivable from sequence) |

### Context flags (candidate features)

| Column | Definition | Source | Future-internal? |
|--------|-----------|--------|------------------|
| `set_piece` | dead-ball origin: penalty OR free-kick shot OR play_pattern∈{From Corner, From Free Kick} | derived | **Yes** |
| `open_play` | `not set_piece` | derived | **Yes** |
| `penalty` | shot_type == Penalty | derived | **Yes** |
| `free_kick` | shot_type == Free Kick | derived | **Yes** |
| `one_on_one` | keeper 1v1 | `shot.one_on_one` | Optional (SB derives from freeze-frame; we could tag manually) |
| `first_time` | struck first-time | `shot.first_time` | Partial (optional tag) |
| `open_goal` | empty net | `shot.open_goal` | Optional (tag) |
| `aerial_won` | won aerial duel before shot | `shot.aerial_won` | Optional |
| `follows_dribble` | shot after a dribble | `shot.follows_dribble` | Partial |

### Assist context (candidate features)

| Column | Definition | Source | Future-internal? |
|--------|-----------|--------|------------------|
| `assisted` | a key pass immediately created the shot | `shot.key_pass_id` present | **Yes** (we know the prior pass) |
| `assist_type` | cross / through_ball / cutback / pass / None | derived from key-pass event | **Yes** |
| `assist_cross` | key pass was a cross | key-pass `pass.cross` | **Yes** |
| `assist_through_ball` | key pass was a through ball | key-pass `pass.technique` | **Yes** |
| `assist_cutback` | key pass was a cut-back | key-pass `pass.cut_back` | **Yes** |

### Benchmark only

| Column | Definition | Source |
|--------|-----------|--------|
| `statsbomb_xg` | provider xG — **benchmark comparison only** | `shot.statsbomb_xg` |

## 5. Deliberately excluded

- **`freeze_frame`** (positions of all defenders + GK at shot). Rich, but we
  **cannot reproduce it** from our future internal tagging data, so features
  like "defenders in shot cone" / "distance to GK" are **not** used — per the
  project rule to only use features obtainable at internal inference time.

## 6. Cleaning applied at extraction

- Shots with no `location` are dropped (cannot compute geometry).
- `goal` cast to clean integer 0/1.
- Missing qualitative values are left as-is; imputation is handled inside the
  saved preprocessing pipeline so it travels with the model.
- Rows sorted by `(match_id, minute, second)` for reproducibility.

## 7. Reproduce

```bash
cd internal-xg
python scripts/build_dataset.py          # full selection
python scripts/build_dataset.py --smoke  # 3 matches per comp (quick check)
```
