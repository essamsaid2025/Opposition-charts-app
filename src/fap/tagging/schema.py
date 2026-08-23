"""Tagging schema — the configurable event system (no rendering, no UI).

A :class:`TagDefinition` declares one taggable event: its geometry (how many
coordinates it needs), which coordinate space it lives in (pitch vs goal), its
relevant outcomes and an optional keyboard shortcut. The canvas and export never
hard-code event types — they read this table, so new events are added here alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# geometry -> which coordinate fields an event needs
GEOMETRIES = ("point", "line")           # point = 1 coord; line = start -> end
COORDINATE_SPACES = ("pitch", "goal")

TEAMS: tuple[str, ...] = ("Team A", "Team B", "Neutral")
PERIODS: tuple[str, ...] = ("1H", "2H", "ET1", "ET2", "Unknown")


@dataclass(frozen=True, slots=True)
class TagDefinition:
    key: str
    label: str
    geometry: str                        # point | line
    coordinate_space: str                # pitch | goal
    outcomes: tuple[str, ...] = ()       # relevant outcomes only (empty = none)
    shortcut: str = ""                   # single key, case-insensitive
    category: str = "General"

    @property
    def required_fields(self) -> tuple[str, ...]:
        if self.coordinate_space == "goal":
            return ("goal_x", "goal_y")
        return ("x", "y", "x2", "y2") if self.geometry == "line" else ("x", "y")

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "geometry": self.geometry,
                "coordinate_space": self.coordinate_space, "outcomes": list(self.outcomes),
                "shortcut": self.shortcut, "category": self.category,
                "required_fields": list(self.required_fields)}


_WON_LOST = ("Won", "Lost")
_OK = ("Successful", "Unsuccessful")
_SHOT = ("Goal", "Saved", "Blocked", "Missed", "Post", "On target")
_GOAL_OUT = ("Goal", "Saved", "Missed", "Post", "Crossbar")

# ---------------------------------------------------------------- pitch events
_PITCH_TAGS: tuple[TagDefinition, ...] = (
    TagDefinition("pass", "Pass", "line", "pitch", _OK, "p", "Passing"),
    TagDefinition("carry", "Carry", "line", "pitch", _OK, "c", "Possession"),
    TagDefinition("cross", "Cross", "line", "pitch", _OK, "x", "Passing"),
    TagDefinition("switch", "Switch of Play", "line", "pitch", _OK, "", "Passing"),
    TagDefinition("progressive", "Progressive Action", "line", "pitch", _OK, "", "Possession"),
    TagDefinition("shot", "Shot", "point", "pitch", _SHOT, "s", "Shooting"),
    TagDefinition("pressure", "Pressure", "point", "pitch", _OK, "", "Defensive"),
    TagDefinition("duel", "Duel", "point", "pitch", _WON_LOST, "d", "Defensive"),
    TagDefinition("recovery", "Recovery", "point", "pitch", (), "r", "Defensive"),
    TagDefinition("interception", "Interception", "point", "pitch", (), "i", "Defensive"),
    TagDefinition("turnover", "Turnover", "point", "pitch", (), "", "Transition"),
    TagDefinition("foul", "Foul", "point", "pitch", _WON_LOST, "f", "Defensive"),
    TagDefinition("defensive_action", "Defensive Action", "point", "pitch", _OK, "", "Defensive"),
    TagDefinition("set_piece", "Set Piece", "point", "pitch", _OK, "", "Set Piece"),
    # set-piece deliveries tagged on the pitch. Their key is the canonical set-piece
    # event_type, so an exported tag classifies as a corner/free_kick/throw_in through
    # the SAME Data Hub derivation every other set-piece dataset uses (no special path).
    TagDefinition("corner", "Corner", "line", "pitch", _OK, "", "Set Piece"),
    TagDefinition("free_kick", "Free Kick", "line", "pitch", _OK, "", "Set Piece"),
    TagDefinition("throw_in", "Throw-in", "line", "pitch", _OK, "", "Set Piece"),
    TagDefinition("custom", "Custom Event", "point", "pitch", (), "", "General"),
)

# ---------------------------------------------------------------- goal events
_GOAL_TAGS: tuple[TagDefinition, ...] = (
    TagDefinition("shot_on_target", "Shot on Target", "point", "goal", _GOAL_OUT, "g", "Goal"),
    TagDefinition("goal", "Goal", "point", "goal", ("Goal",), "", "Goal"),
    TagDefinition("save", "Save", "point", "goal", ("Saved",), "v", "Goalkeeper"),
    TagDefinition("missed_target", "Missed Target", "point", "goal", ("Missed",), "", "Goal"),
    TagDefinition("post", "Hit Post", "point", "goal", ("Post",), "", "Goal"),
    TagDefinition("crossbar", "Hit Crossbar", "point", "goal", ("Crossbar",), "", "Goal"),
    TagDefinition("gk_save_location", "GK Save Location", "point", "goal", ("Saved",), "", "Goalkeeper"),
    TagDefinition("penalty", "Penalty", "point", "goal", _GOAL_OUT, "", "Set Piece"),
    TagDefinition("free_kick_target", "Free-kick Target", "point", "goal", _GOAL_OUT, "", "Set Piece"),
    TagDefinition("goal_other", "Other Goal-mouth Event", "point", "goal", (), "", "Goal"),
)

DEFAULT_TAGS: tuple[TagDefinition, ...] = _PITCH_TAGS + _GOAL_TAGS
_BY_KEY = {t.key: t for t in DEFAULT_TAGS}


def tag_by_key(key: str) -> TagDefinition | None:
    return _BY_KEY.get(str(key))


def tags_for_space(space: str) -> list[TagDefinition]:
    return [t for t in DEFAULT_TAGS if t.coordinate_space == space]


# ---------------------------------------------------------------- presets
# A preset only narrows which event types are *immediately* offered; the schema
# stays fully extensible and every tag remains available under "All".
PRESETS: dict[str, tuple[str, ...]] = {
    "All": tuple(t.key for t in DEFAULT_TAGS),
    "Open Play": ("pass", "carry", "shot", "cross", "duel", "recovery",
                  "interception", "turnover"),
    "Passing": ("pass", "cross", "switch", "progressive"),
    "Defensive": ("pressure", "duel", "recovery", "interception", "foul",
                  "defensive_action"),
    "Transition": ("recovery", "turnover", "interception", "carry", "progressive"),
    "Shooting": ("shot", "shot_on_target", "goal", "missed_target", "post", "crossbar"),
    "Goalkeeper": ("save", "gk_save_location", "shot_on_target", "goal"),
    "Set Piece": ("set_piece", "penalty", "free_kick_target", "cross"),
    "Custom": ("custom",),
}


def preset_tags(preset: str) -> list[TagDefinition]:
    keys = PRESETS.get(preset, PRESETS["All"])
    return [t for t in (tag_by_key(k) for k in keys) if t is not None]


def shortcut_map() -> dict[str, str]:
    """Lower-cased shortcut key -> tag key (first definition wins)."""
    out: dict[str, str] = {}
    for t in DEFAULT_TAGS:
        if t.shortcut and t.shortcut.lower() not in out:
            out[t.shortcut.lower()] = t.key
    return out
