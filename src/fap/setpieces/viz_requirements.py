"""Set-piece visualization REQUIREMENTS (Phase 9.6) - the single source of truth.

Requirements are a property of the dataset a visualization consumes, so they are
declared once per ``sp_dataset`` kind here and resolved for a visualization via
its registered ``sp_dataset`` / ``sp_category`` / ``info.name``. Nothing about the
analytics, rendering engine, algorithms or the visualization plugins changes -
this module only *describes* what each visualization needs so the UI can validate
and guide before rendering.

Source status is three-state and truthful:
    "yes"      supported and available now
    "planned"  a valid source for this data, but not wired up yet (e.g. tracking)
    "no"       cannot produce this data
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SOURCES = ("csv", "excel", "json", "manual", "tracking", "statsbomb")
SOURCE_LABELS = {"csv": "CSV Import", "excel": "Excel", "json": "JSON",
                 "manual": "Manual Tagging", "tracking": "Tracking Data",
                 "statsbomb": "StatsBomb Open"}

# the five coverage axes surfaced in the panel (Part 7)
COVERAGE_AXES = ("coordinates", "contacts", "positions", "goalkeeper", "penalty")
COVERAGE_LABELS = {"coordinates": "Coordinates", "contacts": "Contacts",
                   "positions": "Player Positions", "goalkeeper": "Goalkeeper",
                   "penalty": "Penalty Detail"}


@dataclass(slots=True)
class DatasetSpec:
    kind: str
    label: str
    tier: str                                   # "A" | "B"
    min_events: int
    required_inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...] = ()
    derived_inputs: tuple[str, ...] = ()
    needs_positions: bool = False
    needs_contacts: bool = False
    needs_goalkeeper: bool = False
    needs_penalty: bool = False
    needs_tracking: bool = False                # always False today (tracking not wired)
    sources: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    guidance: tuple[str, ...] = ()
    demo: str = ""                              # demo-builder key (see viz_demo)
    # how "events available" is counted: rows (point maps) | set_pieces | penalties
    # (aggregated datasets bucket into a few rows, so they count underlying events)
    count_by: str = "rows"

    def can_csv_only(self) -> bool:
        return self.sources.get("csv") == "yes"

    def can_manual(self) -> bool:
        return self.sources.get("manual") == "yes"

    def can_tracking(self) -> bool:
        return self.sources.get("tracking") == "yes"


def _src(tier: str, *, positional: bool = False, penalty: bool = False) -> dict[str, str]:
    if tier == "A":
        return {"csv": "yes", "excel": "yes", "json": "yes", "manual": "yes",
                "tracking": "planned", "statsbomb": "planned"}
    # Tier B - not reachable by the generic import path
    return {"csv": "no", "excel": "no", "json": "no", "manual": "yes",
            "tracking": ("planned" if positional and not penalty else "no"),
            "statsbomb": "no"}


_POS_GUIDE = ("Open a set piece and add box positions (attackers, defenders).",
              "Set each player's role or drop them on the pitch.", "Save.")
_CON_GUIDE = ("Open a set piece and add contact events (first contact, second ball, shot).",
              "Set the contact location and outcome.", "Save.")
_GK_GUIDE = ("Add the goalkeeper position (mark 'goalkeeper').",
             "Tag it at the delivery moment (and 'before' for movement).", "Save.")
_PEN_GUIDE = ("Open a penalty and record its detail.",
              "Set placement, goalkeeper and dive direction.", "Save.")

# ------------------------------------------------------------------ registry
DATASETS: dict[str, DatasetSpec] = {}


def _add(spec: DatasetSpec) -> None:
    DATASETS[spec.kind] = spec


# ---- Tier A (event data; CSV/Excel/JSON or manual) --------------------------
_add(DatasetSpec("delivery", "Delivery landing", "A", 10, ("end_x", "end_y"),
                 optional_inputs=("outcome", "delivery_type", "side"),
                 sources=_src("A"), demo="delivery",
                 reason="Plots where deliveries land. Needs delivery landing coordinates "
                        "(end_x / end_y), which event import provides."))
_add(DatasetSpec("delivery_success", "Delivery outcome split", "A", 10, ("end_x", "end_y"),
                 optional_inputs=("shot", "goal"), derived_inputs=("success",),
                 sources=_src("A"), demo="delivery",
                 reason="Splits landings by whether they led to a shot/goal."))
_add(DatasetSpec("delivery_trajectory", "Delivery trajectory", "A", 5,
                 ("start_x", "start_y", "end_x", "end_y"), sources=_src("A"), demo="delivery_traj",
                 reason="Draws start→landing arcs. Needs both origin and landing coordinates."))
_add(DatasetSpec("occ_timeline", "Set pieces over time", "A", 5, ("minute",),
                 sources=_src("A"), demo="delivery", count_by="set_pieces",
                 reason="Counts set pieces per 15-minute band from the event minute."))
_add(DatasetSpec("delivery_accuracy", "Delivery accuracy", "B", 5,
                 ("target_x", "target_y", "end_x", "end_y"), derived_inputs=("error",),
                 sources={"csv": "no", "excel": "no", "json": "no", "manual": "yes",
                          "tracking": "planned", "statsbomb": "no"}, demo="delivery_acc",
                 reason="Compares the intended target to the actual landing. The target must be "
                        "tagged on each delivery — there is no import path for it yet.",
                 guidance=("Open a delivery and mark its intended target point.",
                           "The landing (end_x/end_y) is already stored.", "Save.")))
_add(DatasetSpec("pen_outcome", "Penalty outcomes", "A", 3, ("outcome",), needs_penalty=True,
                 sources=_src("A"), demo="penalty", count_by="penalties",
                 reason="Bars of penalty outcomes. Needs penalty events with an outcome."))
_add(DatasetSpec("pen_shooter", "Shooter conversion", "A", 3, ("taker", "outcome"),
                 optional_inputs=("placement",), needs_penalty=True, sources=_src("A"), demo="penalty",
                 count_by="penalties",
                 reason="Conversion per shooter from penalty events (taker + outcome)."))

# ---- Tier B · player positions ---------------------------------------------
for k, lbl, mn, rsn in (
    ("occ_attack_density", "Box occupancy (attack)", 15,
     "Analyses where attackers stand inside the box at delivery. Needs tagged player positions — "
     "event import only carries delivery locations."),
    ("occ_attack_avg", "Average attacker positions", 5,
     "Mean position of each attacker across set pieces. Needs tagged positions with player names."),
):
    _add(DatasetSpec(k, lbl, "B", mn, ("player_x", "player_y", "team_role"),
                     optional_inputs=("player", "role"), derived_inputs=("zone",),
                     needs_positions=True, sources=_src("B", positional=True),
                     reason=rsn, guidance=_POS_GUIDE, demo="occupancy"))
_add(DatasetSpec("def_positions", "Defensive positions", "B", 5,
                 ("player_x", "player_y", "team_role"), optional_inputs=("marking", "player"),
                 needs_positions=True, sources=_src("B", positional=True),
                 reason="Average defending positions / shape / marking. Needs tagged defender positions.",
                 guidance=_POS_GUIDE, demo="defence"))
_add(DatasetSpec("marking_assignment", "Marking assignments", "B", 5,
                 ("player_x", "player_y", "team_role"), derived_inputs=("nearest_attacker",),
                 needs_positions=True, sources=_src("B", positional=True),
                 reason="Links each defender to the nearest attacker. Needs BOTH attack and defence "
                        "positions on the same set piece.", guidance=_POS_GUIDE, demo="marking"))
for k, lbl, mn, rt in (("movement", "Attacking runs", 5, None),
                       ("movement_screen", "Screen routes", 3, "screen"),
                       ("movement_decoy", "Decoy runs", 3, "decoy"),
                       ("movement_edge", "Edge-box runs", 3, "edge"),
                       ("movement_post", "Near/far post runs", 3, "post")):
    req = ("player_x", "player_y", "moment") + (("run_type",) if rt else ())
    _add(DatasetSpec(k, lbl, "B", mn, req, derived_inputs=("vector",), needs_positions=True,
                     sources=_src("B", positional=True),
                     reason="Attacking movement vectors. Needs each player tagged at ≥2 moments "
                            "(before / at delivery)" + (f", with run_type={rt}." if rt else "."),
                     guidance=_POS_GUIDE, demo=("movement" if not rt else f"movement:{rt}")))
_add(DatasetSpec("blockers", "Blockers", "B", 3, ("player_x", "player_y", "run_type"),
                 needs_positions=True, sources=_src("B", positional=True),
                 reason="Players tagged as blockers (run_type=block).", guidance=_POS_GUIDE, demo="runtype:block"))
_add(DatasetSpec("screens", "Screens", "B", 3, ("player_x", "player_y", "run_type"),
                 needs_positions=True, sources=_src("B", positional=True),
                 reason="Screen locations (run_type=screen).", guidance=_POS_GUIDE, demo="runtype:screen"))
_add(DatasetSpec("wall", "Free-kick wall", "B", 3, ("player_x", "player_y", "team_role"),
                 needs_positions=True, sources=_src("B", positional=True),
                 reason="Free-kick wall placement. Needs defending positions on free kicks.",
                 guidance=_POS_GUIDE, demo="wall"))
# ---- Tier B · goalkeeper ----------------------------------------------------
_add(DatasetSpec("gk_start", "Goalkeeper position", "B", 5, ("gk_x", "gk_y"),
                 needs_goalkeeper=True, sources=_src("B", positional=True),
                 reason="Where the keeper starts / commands. Needs the goalkeeper position tagged.",
                 guidance=_GK_GUIDE, demo="gk"))
_add(DatasetSpec("gk_move", "Goalkeeper movement", "B", 5, ("gk_x", "gk_y", "moment"),
                 derived_inputs=("vector",), needs_goalkeeper=True,
                 sources=_src("B", positional=True),
                 reason="Keeper movement before→at delivery. Needs the GK tagged at ≥2 moments.",
                 guidance=_GK_GUIDE, demo="gk_move"))
# ---- Tier B · contacts ------------------------------------------------------
for k, lbl, mn, rsn, dm in (
    ("shot", "Shot locations", 5, "Set-piece shots. Needs tagged shot contacts (or a first-contact "
     "coordinate on shooting set pieces).", "shot"),
    ("threat", "Threat", 10, "Overall shot-based threat. Needs tagged shot contacts.", "shot"),
    ("goals", "Goal locations", 3, "Where goals are scored. Needs shot contacts with outcome=goal.", "shot"),
    ("first_contact", "First contact", 5, "Who wins the first contact and where. Needs first-contact "
     "contacts (or a first-contact coordinate).", "first_contact"),
    ("second_ball", "Second ball", 5, "Where loose balls are recovered. Needs second-ball contacts.", "second_ball"),
    ("clearance", "Clearances", 5, "Where defenders clear to. Needs clearance contacts.", "clearance"),
    ("flick_on", "Flick-ons", 3, "Near-post headed flick-ons. Needs headed first-contact contacts.", "flick"),
    ("shot_assist", "Shot assists", 5, "Delivery→shot links. Needs shots with coordinates.", "shot"),
):
    _add(DatasetSpec(k, lbl, "B", mn, ("contact_x", "contact_y", "contact_type"),
                     optional_inputs=("player", "body_part", "outcome"), derived_inputs=("won", "xg"),
                     needs_contacts=True, sources=_src("B"), reason=rsn, guidance=_CON_GUIDE, demo=dm))
# ---- Tier B · penalty detail ------------------------------------------------
for k, lbl, mn, req, rsn in (
    ("pen_placement", "Penalty placement", 10, ("placement",), "3×3 placement heatmap. Needs penalty placement tagged."),
    ("pen_goal", "Penalty goals", 10, ("placement",), "Placement of scored penalties. Needs placement + outcome."),
    ("pen_miss", "Penalty misses", 10, ("placement",), "Placement of missed/saved penalties. Needs placement + outcome."),
    ("pen_shots", "Penalty distribution", 10, ("placement",), "All penalty placements. Needs placement tagged."),
    ("pen_clusters", "Placement clusters", 10, ("placement",), "Per-cell conversion. Needs placement + outcome."),
    ("pen_zones", "Success/failure zones", 10, ("placement",), "Per-cell conversion grid. Needs placement + outcome."),
    ("pen_height", "Shot height", 5, ("placement",), "Height distribution. Needs placement (height is derived)."),
    ("pen_direction", "Shot direction", 5, ("placement",), "Side distribution. Needs placement (side is derived)."),
    ("pen_dive", "GK dive", 5, ("gk_dive",), "Keeper dive distribution. Needs gk_dive tagged."),
    ("pen_dive_direction", "GK dive direction", 5, ("gk_dive",), "Directional dives. Needs gk_dive tagged."),
    ("pen_reach", "GK reach", 5, ("gk_dive",), "Dive endpoints across the goal. Needs gk_dive tagged."),
    ("pen_gk", "GK preference", 3, ("goalkeeper",), "Save % per keeper. Needs the goalkeeper name tagged."),
):
    _add(DatasetSpec(k, lbl, "B", mn, req, optional_inputs=("outcome",),
                     needs_penalty=True, sources=_src("B", penalty=True), count_by="penalties",
                     reason=rsn, guidance=_PEN_GUIDE, demo="penalty"))


# ------------------------------------------------------------------ resolver
def dataset_spec(kind: str) -> DatasetSpec | None:
    return DATASETS.get(kind)


def requirements_for(viz_id: str, *, name: str = "", category: str = "",
                     kind: str = "") -> dict[str, Any]:
    """Full requirement metadata for a visualization: its dataset spec plus the
    plugin's own name/category. The caller passes name/category/kind resolved
    from the registry (so this module never imports the visualization engine)."""
    spec = DATASETS.get(kind)
    if spec is None:
        return {"viz_id": viz_id, "name": name or viz_id, "category": category,
                "dataset": kind, "known": False}
    return {
        "viz_id": viz_id, "name": name or viz_id, "category": category,
        "dataset": spec.kind, "dataset_label": spec.label, "tier": spec.tier,
        "min_events": spec.min_events,
        "required_inputs": list(spec.required_inputs),
        "optional_inputs": list(spec.optional_inputs),
        "derived_inputs": list(spec.derived_inputs),
        "needs_positions": spec.needs_positions, "needs_contacts": spec.needs_contacts,
        "needs_goalkeeper": spec.needs_goalkeeper, "needs_penalty": spec.needs_penalty,
        "needs_tracking": spec.needs_tracking,
        "can_csv_only": spec.can_csv_only(), "can_manual": spec.can_manual(),
        "can_tracking": spec.can_tracking(), "count_by": spec.count_by,
        "sources": dict(spec.sources), "reason": spec.reason,
        "guidance": list(spec.guidance), "known": True,
    }
