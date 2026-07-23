"""Penalty domain model (Phase 9.4) - a typed view over the EXISTING set-piece
store. A penalty is a ``SetPiece(type='penalty')``; its rich shooter / goalkeeper
/ shootout attributes live in the extensible ``document`` (no migration, no new
storage layer). ``PenaltyView`` flattens a set piece + its document into one
record the analytics/intelligence read, and ``penalty_document`` whitelists the
fields the tagging UI writes back.

Shootouts are a logical grouping: penalties that share ``document['shootout_id']``
(with ``shootout_order`` and ``sudden_death``), reconstructed on read - so a
shootout needs no dedicated table either.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fap.setpieces.models import SetPiece

# ------------------------------------------------------------------ vocab
FEET = ("", "left", "right")
SIDES = ("", "left", "center", "right")               # horizontal shot side
HEIGHTS = ("", "low", "middle", "high")
TRAJECTORIES = ("", "straight", "dipping", "rising", "knuckle", "side_spin")
POWERS = ("", "hard", "medium", "soft")
BODY_ORIENTATIONS = ("", "open", "closed", "neutral")
TECHNIQUES = ("", "standard", "hop", "stutter", "paradinha")
LAST_STEP = ("", "left", "right", "straight")
DIVE_TIMINGS = ("", "early", "on_time", "late")
DISTRIBUTIONS = ("", "throw", "short_kick", "long_kick", "none")
IMPORTANCES = ("", "friendly", "league", "cup", "knockout", "final")
MATCH_STATES = ("", "winning", "drawing", "losing")
MISS_REASONS = ("", "wide_left", "wide_right", "over", "post", "bar", "blocked")
GK_DIVES = ("", "left", "right", "stay", "center")
# placement cells reuse the 9.2 penalty backend grid (3x3 goal)
from fap.setpieces.penalties import PLACEMENT_CELLS, PENALTY_OUTCOMES  # noqa: E402

# which document keys the tagging UI may write (whitelist)
PENALTY_FIELDS = (
    "placement", "side", "height", "trajectory", "power", "run_up_distance",
    "run_up_angle", "last_step", "body_orientation", "technique", "miss_reason",
    "pressure", "goalkeeper", "gk_dive", "gk_dive_timing", "gk_start_x",
    "gk_start_y", "gk_stayed_central", "gk_correct", "gk_reaction", "gk_reach",
    "distribution_after", "importance", "match_state", "shooter_order",
    "shootout_id", "shootout_order", "sudden_death", "winning_penalty",
    "deciding_penalty", "equalizing_penalty", "target_x", "target_y",
)


def penalty_document(**fields: Any) -> dict[str, Any]:
    """Whitelisted document payload for a penalty (used by tag_penalty)."""
    return {k: v for k, v in fields.items() if k in PENALTY_FIELDS and v not in (None, "")}


# ------------------------------------------------------------------ derivations
def _side_from_cell(cell: str) -> str:
    if not cell:
        return ""
    if "left" in cell:
        return "left"
    if "right" in cell:
        return "right"
    return "center"


def _height_from_cell(cell: str) -> str:
    if cell.startswith("top"):
        return "high"
    if cell.startswith("bottom"):
        return "low"
    if cell.startswith("middle") or cell == "center":
        return "middle"
    return ""


@dataclass(slots=True)
class PenaltyView:
    """Flattened penalty for analytics. Columns from the set piece; the rest from
    its document. Booleans for outcome are derived once."""
    id: str
    shooter: str = ""
    foot: str = ""
    team: str = ""
    opponent: str = ""
    competition: str = ""
    season: str = ""
    venue: str = ""                       # home | away | neutral
    minute: int | None = None
    outcome: str = ""                     # goal | saved | miss | post | bar
    goal: bool = False
    saved: bool = False
    missed: bool = False
    xg: float | None = None
    # shot
    placement: str = ""                   # PLACEMENT_CELLS key
    side: str = ""
    height: str = ""
    trajectory: str = ""
    power: str = ""
    run_up_distance: float | None = None
    run_up_angle: float | None = None
    last_step: str = ""
    body_orientation: str = ""
    technique: str = ""
    miss_reason: str = ""
    pressure: bool = False
    # goalkeeper
    goalkeeper: str = ""
    gk_dive: str = ""
    gk_dive_timing: str = ""
    gk_start_x: float | None = None
    gk_start_y: float | None = None
    gk_stayed_central: bool = False
    gk_correct: bool = False
    gk_reaction: float | None = None
    gk_reach: float | None = None
    distribution_after: str = ""
    # context
    importance: str = ""
    match_state: str = ""
    shooter_order: int | None = None
    # shootout
    shootout_id: str = ""
    shootout_order: int | None = None
    sudden_death: bool = False
    winning_penalty: bool = False
    deciding_penalty: bool = False
    equalizing_penalty: bool = False
    document: dict[str, Any] = field(default_factory=dict)

    @property
    def in_shootout(self) -> bool:
        return bool(self.shootout_id)


def view(sp: SetPiece) -> PenaltyView:
    d = sp.document or {}
    outcome = sp.outcome or ("goal" if sp.goal else "")
    goal = bool(sp.goal or outcome == "goal")
    saved = outcome == "saved"
    missed = (not goal and not saved) or outcome in ("miss", "post", "bar")
    placement = str(d.get("placement", ""))
    return PenaltyView(
        id=sp.id, shooter=sp.taker, foot=sp.foot, team=sp.team, opponent=sp.opponent,
        competition=sp.competition, season=sp.season, venue=sp.venue, minute=sp.minute,
        outcome=outcome, goal=goal, saved=saved, missed=missed, xg=sp.xg,
        placement=placement, side=d.get("side") or _side_from_cell(placement),
        height=d.get("height") or _height_from_cell(placement),
        trajectory=d.get("trajectory", ""), power=d.get("power", ""),
        run_up_distance=_num(d.get("run_up_distance")), run_up_angle=_num(d.get("run_up_angle")),
        last_step=d.get("last_step", ""), body_orientation=d.get("body_orientation", ""),
        technique=d.get("technique", ""), miss_reason=d.get("miss_reason", ""),
        pressure=bool(d.get("pressure", False)), goalkeeper=d.get("goalkeeper", ""),
        gk_dive=d.get("gk_dive", ""), gk_dive_timing=d.get("gk_dive_timing", ""),
        gk_start_x=_num(d.get("gk_start_x")), gk_start_y=_num(d.get("gk_start_y")),
        gk_stayed_central=bool(d.get("gk_stayed_central", False)),
        gk_correct=bool(d.get("gk_correct", False)), gk_reaction=_num(d.get("gk_reaction")),
        gk_reach=_num(d.get("gk_reach")), distribution_after=d.get("distribution_after", ""),
        importance=d.get("importance", ""), match_state=d.get("match_state", ""),
        shooter_order=_int(d.get("shooter_order")), shootout_id=str(d.get("shootout_id", "")),
        shootout_order=_int(d.get("shootout_order")), sudden_death=bool(d.get("sudden_death", False)),
        winning_penalty=bool(d.get("winning_penalty", False)),
        deciding_penalty=bool(d.get("deciding_penalty", False)),
        equalizing_penalty=bool(d.get("equalizing_penalty", False)), document=dict(d))


def views(sps: list[SetPiece]) -> list[PenaltyView]:
    return [view(s) for s in sps if s.type == "penalty"]


def _num(v: Any) -> float | None:
    try:
        return float(v) if v is not None and v != "" else None
    except (ValueError, TypeError):
        return None


def _int(v: Any) -> int | None:
    n = _num(v)
    return int(n) if n is not None else None
