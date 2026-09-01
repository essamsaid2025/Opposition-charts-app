"""Tagged-event export adapter (video-tagging tools: "Succ Short Pass", "Carry", ...).

A manual/video tagging export names each action in a single free-text ``tag_name``
column (e.g. ``Succ Short Pass``, ``Succ Receive``, ``Carry``, ``Tackle Won``,
``Shot Off Target``, ``Goal``) with start/end coordinates in ``x``/``y``/``x2``/``y2`` —
but NO canonical ``event_type`` column. Column detection does not recognise
``tag_name`` as an event type, so the importer falls back to the single-kind shape
inference and labels EVERY row ``pass`` (see [[import-event-shapes]]). All 47 real
action types collapse to one, and only pass charts have data.

This adapter reshapes that shape into canonical event columns BEFORE detection and
classification, so each tag becomes its proper ``event_type`` (+ ``outcome`` from the
Succ/Fail/Won/Lost wording and ``shot_result`` for shots). Every Open Play chart then
renders the real actions, and the availability gate (``fap.openplay.viz_support``)
offers exactly the charts this file supports.

Strictly GUARDED: it only fires on a frame that has a ``tag_name`` column, real
``x``/``y`` coordinates, and NO existing canonical event-type column — so every other
provider/format is untouched. The original tag text is preserved in ``sub_event``.
Pure/deterministic, no I/O. Vocabulary is derived from the tag wording by ordered
keyword rules (not a fixed 47-item list), so unseen tags of the same family map too.
"""
from __future__ import annotations

import pandas as pd

# Columns that, if present, mean the file already carries an event type — do not
# override real event data with the tag reader.
_EVENT_TYPE_COLS = {"event_type", "event", "type", "action", "event_name",
                    "type_name", "primary_event", "event_action", "action_type"}
_TAG_COLS = ("tag_name", "tag name", "tagname", "tag", "tag_type", "action_name")

# Success/failure wording -> canonical outcome vocabulary the engine understands
# (SUCCESS_WORDS = successful/success/complete/won).
_SUCCESS = ("succ", "success", "won", "complete", "recovered")
_FAILURE = ("fail", "lost", "unsucc", "miss")


def _norm(value: object) -> str:
    if value is None or value != value:            # None / NaN
        return ""
    s = str(value).strip().lower()
    return "" if s in ("", "nan", "none") else s


def _find_tag_col(df: pd.DataFrame) -> str | None:
    """The source tag column, matched by normalised name (case/space-insensitive)."""
    lookup = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}
    for cand in _TAG_COLS:
        key = cand.replace(" ", "_")
        if key in lookup:
            return lookup[key]
    return None


def looks_like_tagged_events(df: pd.DataFrame) -> bool:
    """True only for a tag-named event export that still needs reshaping."""
    if df is None or not hasattr(df, "columns"):
        return False
    norm = {str(c).strip().lower().replace(" ", "_") for c in df.columns}
    if norm & _EVENT_TYPE_COLS:            # already has an event-type column
        return False
    if not ({"x", "y"} <= norm):           # needs real coordinates
        return False
    return _find_tag_col(df) is not None


def event_type_for(tag: object) -> str:
    """Canonical ``event_type`` for one tag. Ordered keyword rules, most specific
    first; an unrecognised tag keeps its normalised text (still shown in generic
    charts, never silently dropped)."""
    t = _norm(tag)
    if not t:
        return ""
    if "shot" in t or t == "goal":
        return "shot"
    if "cross" in t:
        return "cross"
    if "tackle" in t:                      # before dribble -> "Dribble Tackle" is a tackle
        return "tackle"
    if "dribble" in t:
        return "dribble"
    if "intercept" in t:
        return "interception"
    if "clear" in t:
        return "clearance"
    if "recover" in t:
        return "recovery"
    if "block" in t:
        return "block"
    if "aerial" in t:
        return "duel"
    if "press" in t:
        return "pressure"
    if "carry" in t:
        return "carry"
    if "chance" in t or "assist" in t or "key pass" in t or "pass" in t:
        return "pass"
    if "receiv" in t:
        return "receive"
    if "foul" in t or "handball" in t:
        return "foul"
    if "offside" in t:
        return "offside"
    if "ball lost" in t or "dispossess" in t or "turnover" in t:
        return "dispossessed"
    return t                               # subs, cards, restart lines... kept as-is


def outcome_for(tag: object) -> str:
    """``successful`` / ``unsuccessful`` from the Succ/Fail/Won/Lost wording, or ""
    when the tag does not encode an outcome (never fabricated)."""
    t = _norm(tag)
    if not t:
        return ""
    if "dribble past" in t:                # a completed dribble past an opponent
        return "successful"
    if any(k in t for k in _FAILURE):
        return "unsuccessful"
    if any(k in t for k in _SUCCESS):
        return "successful"
    return ""


def shot_result_for(tag: object) -> str:
    """Shot outcome label for a shot tag (Goal / On Target / Off Target / Blocked),
    or "" for non-shot tags."""
    t = _norm(tag)
    if event_type_for(t) != "shot":
        return ""
    if t == "goal" or "goal" in t:
        return "Goal"
    if "on target" in t or "saved" in t:
        return "On Target"
    if "off target" in t:
        return "Off Target"
    if "blocked" in t or "block" in t:
        return "Blocked"
    return ""


def reshape(df: pd.DataFrame) -> pd.DataFrame:
    """Return a COPY with canonical ``event_type`` / ``outcome`` / ``shot_result`` /
    ``sub_event`` added from ``tag_name``, or the frame unchanged when it is not a
    tagged-event export. Original columns are preserved."""
    if not looks_like_tagged_events(df):
        return df
    tag_col = _find_tag_col(df)
    if tag_col is None:                    # defensive; guard already checked
        return df
    out = df.copy()
    tags = out[tag_col]
    out["event_type"] = tags.map(event_type_for)
    out["outcome"] = tags.map(outcome_for)
    out["shot_result"] = tags.map(shot_result_for)
    if "sub_event" not in out.columns:     # keep the exact tag for traceability
        out["sub_event"] = tags.map(_norm)
    return out


__all__ = [
    "looks_like_tagged_events",
    "reshape",
    "event_type_for",
    "outcome_for",
    "shot_result_for",
]
