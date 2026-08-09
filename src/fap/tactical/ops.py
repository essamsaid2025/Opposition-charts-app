"""Tactical Board operations - the interaction-agnostic COMMAND layer (Phase 14).

Every change to a board goes through ``apply_command(board, command)`` where a command
is plain JSON (``{"op": ..., ...}``). The Streamlit UI emits these today; the Phase 15
JavaScript drag-and-drop component will emit the SAME commands - so replacing the input
layer needs no change to the model, persistence, export or undo/redo.

``History`` gives undo/redo over serialized board snapshots (deterministic, JSON-only).
All functions are pure Python - no Streamlit.
"""
from __future__ import annotations

from typing import Any

from fap.tactical.models import Board, Frame, TacticalObject, new_id

# object types that carry an end point (drawn as an arrow/line to x2,y2)
_VECTOR_TYPES = {"arrow", "curved_arrow", "dashed_arrow", "line"}


def default_props(obj_type: str) -> dict[str, Any]:
    """Sensible starting props per object type (kept as data)."""
    if obj_type == "player":
        return {"number": 0, "team": "home", "color": "", "role": "", "name": "",
                "captain": False, "goalkeeper": False}
    if obj_type in _VECTOR_TYPES:
        return {"x2": 62.0, "y2": 50.0, "curvature": 0.0}
    if obj_type in ("zone", "highlight", "shape"):
        # stroke/fill defaults chosen so a freshly-added object looks EXACTLY like before:
        # filled, same-colour 2px solid border (the renderer applies the same fallbacks).
        return {"w": 20.0, "h": 16.0, "color": "", "opacity": 0.28, "shape": "rect",
                "filled": True, "stroke_color": "", "stroke_width": 2.0, "stroke_style": "solid"}
    if obj_type in ("text", "number"):
        return {"text": "T", "size": 14, "color": ""}
    if obj_type == "image":
        return {"src": "", "w": 12.0, "h": 12.0}
    return {}


# ---------------------------------------------------------------- command dispatch
def apply_command(board: Board, command: dict[str, Any]) -> dict[str, Any]:
    """Mutate ``board`` per ``command`` and return a small result (e.g. new object id).
    Unknown ops are ignored (forward-compatible). This is the ONE entry point both the
    current UI and the future JS component use."""
    op = str(command.get("op", ""))
    handler = _HANDLERS.get(op)
    result: dict[str, Any] = {}
    if handler is not None:
        result = handler(board, command) or {}
        board.touch()
    return result


def _add_object(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    fr = board.frame(int(c.get("frame", 0)))
    t = str(c.get("type", "player"))
    props = default_props(t)
    props.update(c.get("props") or {})
    obj = TacticalObject(id=new_id(), type=t, x=float(c.get("x", 50.0)),
                         y=float(c.get("y", 50.0)), rotation=float(c.get("rotation", 0.0)),
                         scale=float(c.get("scale", 1.0)),
                         z=int(c.get("z", len(fr.objects))), props=props)
    fr.objects.append(obj)
    return {"id": obj.id}


def _update_object(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    fr = board.frame(int(c.get("frame", 0)))
    obj = fr.object(str(c.get("id", "")))
    if obj is None or obj.locked and not c.get("force"):
        return {}
    for k in ("x", "y", "rotation", "scale", "z"):
        if k in c:
            setattr(obj, k, float(c[k]) if k != "z" else int(c[k]))
    if "locked" in c:
        obj.locked = bool(c["locked"])
    if "props" in c and isinstance(c["props"], dict):
        obj.props.update(c["props"])
    return {"id": obj.id}


def _delete_object(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    fr = board.frame(int(c.get("frame", 0)))
    oid = str(c.get("id", ""))
    fr.objects = [o for o in fr.objects if o.id != oid]
    return {"id": oid}


def _duplicate_object(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    fr = board.frame(int(c.get("frame", 0)))
    obj = fr.object(str(c.get("id", "")))
    if obj is None:
        return {}
    copy = obj.clone(fresh_id=True)
    copy.x = min(100.0, obj.x + 4.0)
    copy.y = min(100.0, obj.y + 4.0)
    copy.z = len(fr.objects)
    fr.objects.append(copy)
    return {"id": copy.id}


def _snap(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    step = float(c.get("step", 5.0))
    for fr in board.frames:
        for o in fr.objects:
            o.x = round(o.x / step) * step
            o.y = round(o.y / step) * step
    return {}


# ---- frames (timeline) ----
def _add_frame(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    src = board.frame(int(c.get("from", len(board.frames) - 1)))
    fr = src.clone(name=f"Frame {len(board.frames) + 1}")   # objects persist across frames
    board.frames.append(fr)
    return {"id": fr.id, "index": len(board.frames) - 1}


def _delete_frame(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    if len(board.frames) <= 1:
        return {}
    i = int(c.get("index", 0))
    if 0 <= i < len(board.frames):
        board.frames.pop(i)
    return {}


def _move_frame(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    i = int(c.get("index", 0)); delta = int(c.get("delta", 0))
    j = max(0, min(len(board.frames) - 1, i + delta))
    if 0 <= i < len(board.frames) and i != j:
        board.frames.insert(j, board.frames.pop(i))
    return {"index": j}


def _rename_frame(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    i = int(c.get("index", 0))
    if 0 <= i < len(board.frames):
        board.frames[i].name = str(c.get("name", board.frames[i].name))
    return {}


def _set_pitch(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    if "kind" in c:
        board.pitch.kind = str(c["kind"])
    if "orientation" in c:
        board.pitch.orientation = str(c["orientation"])
    return {}


def _rename_board(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    board.name = str(c.get("name", board.name))
    return {}


_HANDLERS = {
    "add_object": _add_object, "update_object": _update_object,
    "delete_object": _delete_object, "duplicate_object": _duplicate_object,
    "snap": _snap, "add_frame": _add_frame, "delete_frame": _delete_frame,
    "move_frame": _move_frame, "rename_frame": _rename_frame,
    "set_pitch": _set_pitch, "rename_board": _rename_board,
}


def command_names() -> tuple[str, ...]:
    return tuple(_HANDLERS)


# ---------------------------------------------------------------- undo / redo
class History:
    """Undo/redo over serialized board snapshots (JSON-only, deterministic)."""

    def __init__(self, limit: int = 60) -> None:
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []
        self._limit = limit

    def record(self, board: Board) -> None:
        """Push the CURRENT state before a mutation, so undo restores it."""
        self._undo.append(board.to_dict())
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, current: Board) -> Board | None:
        if not self._undo:
            return None
        self._redo.append(current.to_dict())
        return Board.from_dict(self._undo.pop())

    def redo(self, current: Board) -> Board | None:
        if not self._redo:
            return None
        self._undo.append(current.to_dict())
        return Board.from_dict(self._redo.pop())

    def to_dict(self) -> dict[str, Any]:
        return {"undo": self._undo, "redo": self._redo, "limit": self._limit}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "History":
        h = cls(limit=int(d.get("limit", 60)))
        h._undo = list(d.get("undo") or [])
        h._redo = list(d.get("redo") or [])
        return h
