"""Event-shape inference for single-kind, header-light exports.

Some real-world exports are one kind of event with NO ``event_type`` column:
a bare ``x,y`` touch / heat-map dump, a shot map (``x,y,xG,result,bodyPart,…``)
or a pass file that only carries start/end coordinates. The canonical schema
requires ``event_type`` (:data:`fap.pipeline.schema.REQUIRED`), so these files
fail import with *"Missing required column: event_type"* even though their event
kind is obvious from the columns.

:func:`infer_event_shape` recognizes those shapes from the column *names* alone
and returns the constant ``event_type`` the importer should inject for every row,
plus any extra column mapping the shape implies (a shot map's ``result`` is a
shot outcome, not a generic outcome). It NEVER fires when the file already
supplies an event type - the importer consults it only as a fallback, so a real
event log is never reinterpreted. Pure: no I/O, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from fap.core.naming import normalize_name
from fap.pipeline.columns import ALIASES


@dataclass(frozen=True, slots=True)
class EventShape:
    """The event kind inferred for a whole file plus the mapping it implies."""
    event_type: str                                            # constant for every row
    extra_mapping: dict[str, str] = field(default_factory=dict)  # source col -> canonical
    label: str = ""                                            # human label, e.g. "Shot map"
    reason: str = ""                                           # why it was recognized


def _norm_set(*names: str) -> frozenset[str]:
    return frozenset(normalize_name(n) for n in names)


# alias groups, pre-normalized so they compare against normalized source names
_EVENT = _norm_set(*ALIASES["event_type"])
_XCOLS = _norm_set(*ALIASES["x"])
_YCOLS = _norm_set(*ALIASES["y"])
_END = _norm_set(*ALIASES["end_x"], *ALIASES["end_y"])
_BODY = _norm_set(*ALIASES["body_part"])
_XG = _norm_set(*ALIASES["shot_xg"], "xgot", "xg_ot", "post_shot_xg", "psxg")


# values a pass-tagging export puts in its single "Event" column - these are
# pass qualifiers/outcomes, NOT event kinds. Used to recognize a file whose
# event column is really a pass column in disguise (see looks_like_pass_qualifiers).
PASS_QUALIFIERS = frozenset({
    "accurate", "inaccurate", "complete", "completed", "incomplete",
    "successful", "unsuccessful", "key pass", "keypass", "key_pass",
    "assist", "assists", "through ball", "throughball", "chance created",
})


def looks_like_pass_qualifiers(values: Sequence[str]) -> bool:
    """True when a column's values are pass qualifiers rather than event names.

    A manual pass export often has a single ``Event`` column holding
    ``Accurate/Inaccurate/Key pass/Assist`` - which auto-maps to ``event_type``
    and then matches no real event. This recognizes that case so the importer can
    reclassify it to passes. Returns False the moment any value is a known event
    name, so a genuine event log is never touched.
    """
    from fap.pipeline.validation import KNOWN_EVENTS
    vals = {str(v).strip().lower() for v in values if str(v).strip()}
    if not vals or (vals & KNOWN_EVENTS):
        return False
    return vals <= PASS_QUALIFIERS


def _norm_map(columns: Sequence[str]) -> dict[str, str]:
    """normalized name -> first original column with that normalized name."""
    out: dict[str, str] = {}
    for c in columns:
        out.setdefault(normalize_name(c), str(c))
    return out


def infer_event_shape(columns: Sequence[str]) -> EventShape | None:
    """Best-effort event kind for a file that has no event_type column.

    Returns ``None`` when the file already declares an event type or has no pitch
    coordinates (nothing we could meaningfully assume). Otherwise returns the
    single event kind the columns point to.
    """
    norm = _norm_map(columns)
    keys = set(norm)

    if keys & _EVENT:                       # already has an event type - never override
        return None
    if not (keys & _XCOLS and keys & _YCOLS):
        return None                         # no location -> cannot help

    result_src = norm.get("result")         # shot maps label the outcome "result"
    has_xg = bool(keys & _XG)
    has_body = bool(keys & _BODY)
    has_end = bool(keys & _END)

    if has_xg or (result_src and has_body):
        extra = {result_src: "shot_result"} if result_src else {}
        return EventShape("shot", extra, "Shot map",
                          "xG / result / body-part columns identify a shot map")
    if has_end:
        return EventShape("pass", {}, "Pass map",
                          "start and end coordinates but no event type")
    return EventShape("touch", {}, "Touch / heat map",
                      "only pitch coordinates - treated as touches")
