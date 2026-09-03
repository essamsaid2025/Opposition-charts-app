"""Data-driven availability of Open Play visualizations.

The Open Play engine registers every visualization it *can* draw, regardless of the
data that is actually loaded. Several of those visualizations only mean anything for
a specific kind of event: a Shot Map needs shot events, a Carry Map needs carries
with end coordinates, and so on. When a dataset carries only a little information (a
bare pass/heat export, a single-kind tag file) those charts render empty, which is
noise in the picker.

This module answers, for the CURRENTLY loaded frame, *which registered
visualizations would actually have something to draw* — so the UI can offer only the
charts a file supports and hide the rest. It is pure metadata: it never renders, and
it mirrors (does not change) each visualization's existing data predicate in
``app.py`` so a chart is hidden exactly when the engine would draw it empty.

Design rules:
- A visualization is hidden ONLY when we are confident it needs an event type / end
  coordinates the frame does not contain. Everything not listed here (heatmaps,
  zone %, tables, timelines, dashboards, unknown/plugin charts) is always offered.
- When there is no frame, no ``event_type`` column, or the frame is empty, nothing is
  gated — we never blank out the picker on missing information; the page's own empty
  state covers "no data".

Pure: no Streamlit, no matplotlib, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from fap.openplay.config import DEF_EVENTS


@dataclass(frozen=True, slots=True)
class VizRequirement:
    """What a visualization needs from the frame to draw something.

    ``events`` — at least one row whose ``event_type`` (lower-cased) is in this set.
    ``end_coords`` — at least one row with non-null end coordinates (``x2/y2`` or the
    canonical ``end_x/end_y``). Empty requirement == always available.
    """
    events: tuple[str, ...] = ()
    end_coords: bool = False

    def satisfied(self, present_events: frozenset[str], has_end: bool) -> bool:
        if self.events and not any(e in present_events for e in self.events):
            return False
        if self.end_coords and not has_end:
            return False
        return True


# Requirements keyed by the engine's registered visualization name. Each entry
# mirrors the data predicate the matching renderer in ``app.py`` applies:
#   make_arrow_viz("<event>")  -> event_type == "<event>" AND draws start->end arrows
#   viz_shots / viz_shot_summary -> event_type == "shot"
#   viz_defensive -> event_type in DEF_EVENTS
#   viz_pass_direction -> passes, direction from end coords
#   viz_start_end -> a start/end event (default "pass"), needs end coords
# Anything not listed is event-agnostic (heatmaps, zone %, tables, timelines,
# dashboards) or unknown (plugins) and is always offered.
_REQUIREMENTS: dict[str, VizRequirement] = {
    "Pass Map": VizRequirement(events=("pass",), end_coords=True),
    "Carry Map": VizRequirement(events=("carry",), end_coords=True),
    "Cross Map": VizRequirement(events=("cross",), end_coords=True),
    "Dribble Map": VizRequirement(events=("dribble",), end_coords=True),
    "Start / End Map": VizRequirement(end_coords=True),
    "Shot Map": VizRequirement(events=("shot",)),
    "Shot Result Bar": VizRequirement(events=("shot",)),
    "Pass Direction Bar": VizRequirement(events=("pass",), end_coords=True),
    "Passing Combination Matrix": VizRequirement(events=("pass",)),
    "Defensive Actions Map": VizRequirement(
        events=tuple(e.lower() for e in DEF_EVENTS)),
}

_END_COORD_PAIRS = (("x2", "y2"), ("end_x", "end_y"))


def present_event_types(frame: Any) -> frozenset[str]:
    """Lower-cased, stripped, non-blank ``event_type`` values present in the frame."""
    if frame is None or "event_type" not in getattr(frame, "columns", []):
        return frozenset()
    out = set()
    for v in frame["event_type"]:
        if v is None or v != v:           # skip None / NaN (v != v is NaN)
            continue
        s = str(v).strip().lower()
        if s and s != "nan":
            out.add(s)
    return frozenset(out)


def has_end_coordinates(frame: Any) -> bool:
    """True when at least one row carries both end-coordinate values.

    Tolerates either the Open Play field names (``x2``/``y2``) or the canonical
    schema (``end_x``/``end_y``), so it works on the derived frame either engine
    hands us.
    """
    cols = getattr(frame, "columns", [])
    for xa, ya in _END_COORD_PAIRS:
        if xa in cols and ya in cols:
            try:
                return bool(frame[[xa, ya]].notna().all(axis=1).any())
            except Exception:  # noqa: BLE001 - never let a gate break the picker
                return False
    return False


def is_supported(name: str, present_events: frozenset[str], has_end: bool) -> bool:
    """Whether the named visualization has something to draw for this frame state."""
    req = _REQUIREMENTS.get(name)
    if req is None:
        return True
    return req.satisfied(present_events, has_end)


def available_viz_names(names: Iterable[str], frame: Any) -> list[str]:
    """Filter ``names`` (order preserved) to those the frame can actually produce.

    When the frame is missing/empty or exposes no event types, nothing is gated and
    the full list is returned — we never blank the picker on missing information.
    """
    names = list(names)
    if frame is None or getattr(frame, "empty", True):
        return names
    present = present_event_types(frame)
    if not present:
        return names
    has_end = has_end_coordinates(frame)
    return [n for n in names if is_supported(n, present, has_end)]


def unsupported_viz_names(names: Iterable[str], frame: Any) -> list[str]:
    """The complement of :func:`available_viz_names` — charts hidden for this frame.
    Useful for an explanatory caption ("hidden: needs shot events")."""
    available = set(available_viz_names(names, frame))
    return [n for n in names if n not in available]


__all__ = [
    "VizRequirement",
    "present_event_types",
    "has_end_coordinates",
    "is_supported",
    "available_viz_names",
    "unsupported_viz_names",
]
