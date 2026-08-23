# FAP Visualization Audit — Golden Test Data

Deterministic datasets for verifying that every visualization plots **exactly** the
events its name claims. Every `event_id` is chosen so the correct result is obvious.
Import a file through **Data Hub → Import**, activate it, then open the named
visualization. Coordinates are canonical: `x` 0–100 (0 = own goal, 100 = opponent
goal), `y` 0–100, attacking left→right.

## Files
- `fap_visualization_audit_events.csv` — passes, carries, shots, crosses, defensive
  actions, zone entries and set pieces (open-play maps).
- `fap_visualization_audit_set_pieces.csv` — corners / free kicks / throw-ins /
  penalties / set-piece shot (Set Piece analysis).
- `fap_visualization_audit_goal_events.csv` — goal-mouth shots with `goal_x/goal_y`
  (Goal Mouth / Save maps).

---

## events file — expected results

| Visualization | SHOULD appear | MUST NOT appear |
|---|---|---|
| **Pass Map** | P001–P005, K040, FT060/061, PA070/071 | any shot/carry/defensive |
| **Progressive Pass Map** | P001, P004, K040, FT060, FT061, PA070 | **P002, P003, P005, PA071** |
| **Forward Passes** | P001, P004, K040, FT060, FT061, PA070 | P003 (backward) |
| **Backward Passes** | P003 | P001 |
| **Sideways Passes** | P002, P005, PA071 | P001 |
| **Key Passes** | **K040 only** | every other pass |
| **Crosses** | X030 | passes |
| **Carry Map** | C010, C011 | passes |
| **Progressive Carries** | C010 | **C011** |
| **Shot Map** | S020, S021, S022, SPS001 | passes, carries, defensive |
| **Goals** | S021 | S020 (saved), S022 (off target) |
| **Interceptions** | D050 | D051–D056 |
| **Recoveries** | D051 | D050, D052… |
| **Tackles** | D052 | other defensive |
| **Pressures** | D053 | other defensive |
| **Clearances** | D054 | other defensive |
| **Blocks** | D056 | other defensive |
| **Defensive Actions** | D050–D056 | passes/shots |
| **Final Third Entries** | P001, P004, C010, FT060 | **FT061** (already inside) |
| **Penalty Area Entries** | P004, K040, FT061, PA070, X030 | **PA071** (starts inside) |

Coordinates to verify visually: **P001** starts (20,50) → ends (70,50) — a straight
horizontal line in the defensive/middle third. **S021** (goal) sits at (90,45).

## set_pieces file — expected results

| Visualization | SHOULD appear | MUST NOT appear |
|---|---|---|
| **Corner Map** | CRN001, CRN002, SPSHOT001 | **FK001, FK002, TI001** |
| **Free Kick Map** | FK001, FK002 | **CRN001, CRN002** |
| **Throw-in Map** | TI001 | corners/free kicks |
| **Penalty** | PEN001 | — |
| **Set-piece Shot** | SPSHOT001 | NORMALSHOT001 (open-play shot) |

Import via **Data Hub** — Set Piece then reads it automatically (no second import).

## goal_events file — expected results

| Visualization | SHOULD appear | Notes |
|---|---|---|
| **Goal Mouth Map** | GM001–GM005 | GM001 is a Goal (red), others saved/missed (purple) |
| **Save Map / Save Zones** | GM002, GM003, GM005 | saved shots |

`goal_x/goal_y` (0–100 across the goal / ground→crossbar) locate each marker inside
the canonical goal renderer; `end_y` places it across the goal-mouth frame.

---

## Automated proof
`tests/test_visualization_audit.py` and `tests/test_setpiece_datahub.py` assert every
row above (positive **and** negative) through the real ingestion pipeline, so a
regression that widens or narrows any selector fails the build.
