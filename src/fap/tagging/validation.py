"""Validation — reject impossible tags before they reach the CSV.

Checks event type, coordinate space, geometry-required coordinates, coordinate
ranges and outcome relevance. Rendering and export stay separate: this module only
reports problems (as human-readable messages); it never mutates data.
"""
from __future__ import annotations

from typing import Any

from fap.tagging.coordinates import in_range
from fap.tagging.models import TagEvent, TaggingSession
from fap.tagging.schema import tag_by_key


def validate_event(event: TagEvent) -> list[str]:
    errors: list[str] = []
    tag = tag_by_key(event.event_type)
    if tag is None:
        return [f"unknown event type {event.event_type!r}"]
    if event.coordinate_space != tag.coordinate_space:
        errors.append(f"{tag.label}: coordinate space must be "
                      f"{tag.coordinate_space!r}, got {event.coordinate_space!r}")
    for f in tag.required_fields:
        v = getattr(event, f, None)
        if v is None:
            errors.append(f"{tag.label}: missing required coordinate {f!r}")
        elif not in_range(v):
            errors.append(f"{tag.label}: {f}={v} is outside 0–100")
    if event.outcome and tag.outcomes and event.outcome not in tag.outcomes:
        errors.append(f"{tag.label}: outcome {event.outcome!r} is not one of "
                      f"{', '.join(tag.outcomes)}")
    return errors


def validate_session(session: TaggingSession) -> list[tuple[str, str]]:
    """Returns ``(event_id, message)`` for every problem across the session."""
    problems: list[tuple[str, str]] = []
    seen: set[str] = set()
    for e in session.events:
        if e.id in seen:
            problems.append((e.id, "duplicate event id"))
        seen.add(e.id)
        for msg in validate_event(e):
            problems.append((e.id, msg))
    return problems


def is_exportable(session: TaggingSession) -> bool:
    return not validate_session(session)
