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
        # ``variant`` is empty by default so existing arrows render byte-identically;
        # setting it (pass/run/movement/pressing/defensive/dribble/shot) opts into the
        # semantic style. label is an optional caption.
        return {"x2": 62.0, "y2": 50.0, "curvature": 0.0, "variant": "", "label": ""}
    if obj_type == "freehand":
        return {"points": [], "color": "", "width": 3.0, "closed": False}
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


# ---- multi-object / group / z-order / visibility (Phase 3) ----
def _ids(c: dict[str, Any]) -> list[str]:
    ids = c.get("ids")
    if isinstance(ids, (list, tuple)):
        return [str(i) for i in ids if str(i)]
    one = str(c.get("id", ""))
    return [one] if one else []


def _delete_objects(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    fr = board.frame(int(c.get("frame", 0)))
    ids = set(_ids(c))
    kept = [o for o in fr.objects if o.id not in ids]
    removed = len(fr.objects) - len(kept)
    fr.objects = kept
    return {"removed": removed}


def _duplicate_objects(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    """Duplicate several objects at once, preserving any shared group (the copies form
    a NEW group), offset by (4,4). Returns the new ids in order."""
    fr = board.frame(int(c.get("frame", 0)))
    ids = _ids(c)
    originals = [o for o in fr.objects if o.id in set(ids)]
    if not originals:
        return {"ids": []}
    new_group = new_id("grp") if any((o.props or {}).get("group") for o in originals) else ""
    new_ids: list[str] = []
    z0 = len(fr.objects)
    for i, o in enumerate(originals):
        copy = o.clone(fresh_id=True)
        copy.x = min(100.0, o.x + 4.0)
        copy.y = min(100.0, o.y + 4.0)
        copy.z = z0 + i
        if new_group:
            copy.props["group"] = new_group
        fr.objects.append(copy)
        new_ids.append(copy.id)
    return {"ids": new_ids, "group": new_group}


def _move_objects(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    """Translate several objects by (dx, dy) in 0-100 pitch space (nudge / group drag).
    Respects ``locked`` unless ``force``. Clamps to the pitch. One undo step."""
    fr = board.frame(int(c.get("frame", 0)))
    dx, dy = float(c.get("dx", 0.0)), float(c.get("dy", 0.0))
    force = bool(c.get("force"))
    moved = 0
    for o in fr.objects:
        if o.id in set(_ids(c)) and (force or not o.locked):
            o.x = min(100.0, max(0.0, o.x + dx))
            o.y = min(100.0, max(0.0, o.y + dy))
            moved += 1
    return {"moved": moved}


def _group_objects(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    fr = board.frame(int(c.get("frame", 0)))
    ids = set(_ids(c))
    if len(ids) < 2:
        return {"group": ""}
    gid = str(c.get("group") or new_id("grp"))
    for o in fr.objects:
        if o.id in ids:
            o.props["group"] = gid
    return {"group": gid}


def _ungroup_objects(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    """Clear the group on the given ids, or on every member of a named group."""
    fr = board.frame(int(c.get("frame", 0)))
    ids = set(_ids(c))
    gid = str(c.get("group") or "")
    for o in fr.objects:
        if (ids and o.id in ids) or (gid and (o.props or {}).get("group") == gid):
            o.props.pop("group", None)
    return {}


def _reorder_object(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    """Z-order: front|back|forward|backward. Renormalizes z to a stable 0..n-1 order."""
    fr = board.frame(int(c.get("frame", 0)))
    ids = set(_ids(c))
    direction = str(c.get("dir", "forward"))
    ordered = sorted(fr.objects, key=lambda o: o.z)
    sel = [o for o in ordered if o.id in ids]
    rest = [o for o in ordered if o.id not in ids]
    if not sel:
        return {}
    if direction == "front":
        ordered = rest + sel
    elif direction == "back":
        ordered = sel + rest
    else:                                                # forward / backward: shift by one
        idxs = [i for i, o in enumerate(ordered) if o.id in ids]
        step = 1 if direction == "forward" else -1
        for i in (reversed(idxs) if step > 0 else idxs):
            j = i + step
            if 0 <= j < len(ordered) and ordered[j].id not in ids:
                ordered[i], ordered[j] = ordered[j], ordered[i]
    for k, o in enumerate(ordered):
        o.z = k
    return {}


def _set_hidden(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    fr = board.frame(int(c.get("frame", 0)))
    hidden = bool(c.get("hidden", True))
    for o in fr.objects:
        if o.id in set(_ids(c)):
            if hidden:
                o.props["hidden"] = True
            else:
                o.props.pop("hidden", None)
    return {}


def _set_locked(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    fr = board.frame(int(c.get("frame", 0)))
    locked = bool(c.get("locked", True))
    for o in fr.objects:
        if o.id in set(_ids(c)):
            o.locked = locked
    return {}


# arrow visual props that _set_arrow_properties may write (head is independent of variant)
_ARROW_PROP_KEYS = ("arrowhead", "arrowhead_size", "arrowhead_stroke_width", "stroke_width")


def _set_arrow_properties(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    """Set arrowhead/body visual props on the selected ARROW objects (``ids``) in ONE undo
    step. Only vector (arrow/line) types are touched; non-arrows and locked objects are
    skipped safely. Absent keys are left untouched, so this composes with legacy defaults."""
    fr = board.frame(int(c.get("frame", 0)))
    ids = set(_ids(c))
    changed = 0
    for o in fr.objects:
        if o.id in ids and o.type in _VECTOR_TYPES and not o.locked:
            for k in _ARROW_PROP_KEYS:
                if k in c and c[k] is not None:
                    o.props[k] = c[k]
            changed += 1
    return {"changed": changed}


def _align_objects(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    """Align the selected objects on one edge/centre (0-100 pitch space): left|right|
    top|bottom|center_h|center_v. Locked objects are skipped. One undo step."""
    fr = board.frame(int(c.get("frame", 0)))
    sel = [o for o in fr.objects if o.id in set(_ids(c))]
    movable = [o for o in sel if not o.locked]
    if len(movable) < 2:
        return {"aligned": 0}
    how = str(c.get("align", "left"))
    xs = [o.x for o in movable]; ys = [o.y for o in movable]
    if how == "left":
        for o in movable: o.x = min(xs)
    elif how == "right":
        for o in movable: o.x = max(xs)
    elif how == "center_h":
        mid = (min(xs) + max(xs)) / 2
        for o in movable: o.x = mid
    elif how == "top":
        for o in movable: o.y = min(ys)
    elif how == "bottom":
        for o in movable: o.y = max(ys)
    elif how == "center_v":
        mid = (min(ys) + max(ys)) / 2
        for o in movable: o.y = mid
    return {"aligned": len(movable)}


def _distribute_objects(board: Board, c: dict[str, Any]) -> dict[str, Any]:
    """Evenly space the selected objects between the two extremes along ``axis``
    (horizontal|vertical). Needs >= 3 movable objects. One undo step."""
    fr = board.frame(int(c.get("frame", 0)))
    movable = [o for o in fr.objects if o.id in set(_ids(c)) and not o.locked]
    if len(movable) < 3:
        return {"distributed": 0}
    horizontal = str(c.get("axis", "horizontal")) == "horizontal"
    movable.sort(key=lambda o: o.x if horizontal else o.y)
    lo = movable[0].x if horizontal else movable[0].y
    hi = movable[-1].x if horizontal else movable[-1].y
    step = (hi - lo) / (len(movable) - 1)
    for i, o in enumerate(movable):
        if horizontal:
            o.x = lo + step * i
        else:
            o.y = lo + step * i
    return {"distributed": len(movable)}


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
    "delete_objects": _delete_objects, "duplicate_objects": _duplicate_objects,
    "move_objects": _move_objects, "group_objects": _group_objects,
    "ungroup_objects": _ungroup_objects, "reorder_object": _reorder_object,
    "set_hidden": _set_hidden, "set_locked": _set_locked,
    "set_arrow_properties": _set_arrow_properties,
    "align_objects": _align_objects, "distribute_objects": _distribute_objects,
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
