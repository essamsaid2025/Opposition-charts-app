"""Undo/redo command history for the editor.

The DURABLE report always lives in the database (every op is persisted through
``ReportsManager.update_studio``). This stack is an *ephemeral editing aid*: it
holds document snapshots so the user can step backward/forward within a session.
It therefore lives in ``st.session_state`` - the one thing the phase permits there
(temporary UI state), never as the source of truth. Restoring a snapshot reuses
``ReportsManager.save_document``; no mutation logic is duplicated here.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

_LIMIT = 50


def _stacks(report_id: str) -> tuple[list, list]:
    key = f"_studio_hist::{report_id}"
    if key not in st.session_state:
        st.session_state[key] = {"undo": [], "redo": []}
    s = st.session_state[key]
    return s["undo"], s["redo"]


def record(report_id: str, snapshot: dict[str, Any]) -> None:
    """Push the pre-mutation document snapshot; a new edit invalidates redo."""
    undo, redo = _stacks(report_id)
    undo.append(snapshot)
    del undo[:-_LIMIT]
    redo.clear()


def can_undo(report_id: str) -> bool:
    return bool(_stacks(report_id)[0])


def can_redo(report_id: str) -> bool:
    return bool(_stacks(report_id)[1])


def undo(report_id: str, current: dict[str, Any]) -> dict[str, Any] | None:
    undo_s, redo_s = _stacks(report_id)
    if not undo_s:
        return None
    redo_s.append(current)
    return undo_s.pop()


def redo(report_id: str, current: dict[str, Any]) -> dict[str, Any] | None:
    undo_s, redo_s = _stacks(report_id)
    if not redo_s:
        return None
    undo_s.append(current)
    return redo_s.pop()
