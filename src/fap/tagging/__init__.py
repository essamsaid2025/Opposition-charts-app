"""Tagging Studio — a professional manual event-tagging environment.

Pure, Streamlit-free core (schema, coordinate engine, session + undo/redo history,
validation, CSV/JSON export). The Streamlit page (``fap.ui.builtin.tagging``) is a
thin view over this core; the interactive canvas only *reports* fractional clicks,
which the coordinate engine converts to canonical football coordinates here.

Responsibility layers (never mixed):

    schema      TagDefinition / presets / outcomes   (what can be tagged)
    coordinates canvas fraction -> canonical coords   (where it was tagged)
    models      TagEvent / TaggingSession            (the data)
    session     command + snapshot History           (undo/redo, reliability)
    validation  range/field/reference checks         (correctness before export)
    export      CSV (stable schema) + JSON project + canonical viz frame
"""
from __future__ import annotations

from fap.tagging.coordinates import (canonical_from_goal_fraction,
                                     canonical_from_pitch_fraction,
                                     goal_fraction_from_canonical,
                                     pitch_fraction_from_canonical)
from fap.tagging.export import (CSV_COLUMNS, session_to_canonical_frame,
                                session_to_csv)
from fap.tagging.models import TagEvent, TaggingSession
from fap.tagging.schema import (DEFAULT_TAGS, PERIODS, PRESETS, TEAMS,
                                TagDefinition, tag_by_key)
from fap.tagging.validation import validate_event, validate_session

__all__ = [
    "TagDefinition", "DEFAULT_TAGS", "PRESETS", "TEAMS", "PERIODS", "tag_by_key",
    "TagEvent", "TaggingSession",
    "canonical_from_pitch_fraction", "canonical_from_goal_fraction",
    "pitch_fraction_from_canonical", "goal_fraction_from_canonical",
    "validate_event", "validate_session",
    "CSV_COLUMNS", "session_to_csv", "session_to_canonical_frame",
]
