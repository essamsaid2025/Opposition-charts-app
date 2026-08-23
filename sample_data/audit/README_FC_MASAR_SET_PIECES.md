# FC Masar — Set Piece Template (one game)

`fap_visualization_audit` companion. A single match, **FC Masar vs Nile Stars**
(50 set pieces), designed to exercise the Set Piece module through the **Data Hub**.

## How to use
1. **Data Hub → Import** → upload `fc_masar_set_pieces.csv` → it is classified as an
   *event* dataset, persisted and activated.
2. **Analysis → Set Piece** — it reads the active dataset automatically (no second
   import). The Overview, **Offensive** (FC Masar attacking, 33 set pieces) and
   **Defensive** (vs Nile Stars, 17) dashboards all populate.

## What's in the game
| Type | Count | Notes |
|---|---|---|
| Corners | 23 | left & right; inswing / outswing / driven / short; 33% of them = FC Masar |
| Free kicks | 13 | direct (shots on goal) + indirect (deliveries into the box) |
| Throw-ins | 9 | long throws into the box |
| Penalties | 5 | takers M. Salah / O. Marmoush / Zizo; goal / saved / missed |
| Goals from set pieces | 9 | across corners, free kicks and penalties |

Each row carries: `event_type` (corner/free_kick/throw_in/penalty), `team`,
`opponent`, `player` (taker), `x,y` (delivery origin), `end_x,end_y` (landing),
`outcome`, `shot_result`, `delivery_type` (swing), `side`, `foot`, `players_in_box`,
`first_contact_team`, `second_ball_team`, `retained`, `xg`, `marking`, `minute`,
`period`. Coordinates are canonical (0–100, attacking toward x=100).

## Charts this file renders (delivery-level / CSV-reachable)
- **Delivery landing**, **Delivery outcome split**, **Delivery trajectory**
- **Set pieces over time** (timeline by 15-min band)
- **Penalty outcomes**, **Shooter conversion**
- Offensive / Defensive dashboards, side & swing breakdowns, first-contact split.

## Charts that need in-app tagging (NOT carried by ANY CSV — by design)
Box occupancy / player positions, attacking-run / movement maps, contact maps
(first contact, second ball, clearances, flick-ons, shot & goal *contact* locations),
the **penalty placement 3×3 grid**, and **GK dive / reach** need the manual tagging
layer (player positions, contacts, penalty placement, goalkeeper) added on a set
piece in the app — a plain event feed only carries delivery locations. Open a set
piece in **Browse** and tag positions/contacts to light those up.

> This is why the Set Piece "coverage" panel shows some visualizations as
> *needs positions / needs contacts / needs penalty detail* — it is telling the
> truth about what event data alone can and cannot produce.
