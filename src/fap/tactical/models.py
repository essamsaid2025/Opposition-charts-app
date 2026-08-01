"""Tactical Board domain model (Phase 14) - pure, serializable, interaction-agnostic.

This is the production-ready CORE. It knows nothing about Streamlit or how the board
is drawn or manipulated. A ``Board`` is a stack of ``Frame`` snapshots; each frame
holds ``TacticalObject`` items. An object keeps a stable ``id`` across frames, so the
same object at different positions in consecutive frames IS the animation. Everything
round-trips through ``to_dict``/``from_dict`` (plain JSON), so persistence (Workspace
Manager), export, and a future JS drag-and-drop component all share one contract.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass, field
from typing import Any

# controlled vocabularies (kept as data so new kinds need no code branches)
OBJECT_TYPES: tuple[str, ...] = (
    "player", "ball", "cone", "goal", "mannequin",
    "arrow", "curved_arrow", "dashed_arrow", "line",
    "zone", "highlight", "text", "number", "shape", "image",
)
PITCH_KINDS: tuple[str, ...] = ("full", "half", "thirds", "blank", "futsal", "custom")
ORIENTATIONS: tuple[str, ...] = ("horizontal", "vertical")


def new_id(prefix: str = "obj") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class TacticalObject:
    """One item on the board. ``x``/``y`` are 0-100 pitch coordinates (orientation-
    independent); ``props`` carries type-specific fields (player number/team/role,
    arrow end point + style, zone size, text, image src, ...)."""
    id: str
    type: str
    x: float = 50.0
    y: float = 50.0
    rotation: float = 0.0
    scale: float = 1.0
    z: int = 0
    locked: bool = False
    props: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "x": self.x, "y": self.y,
                "rotation": self.rotation, "scale": self.scale, "z": self.z,
                "locked": self.locked, "props": dict(self.props)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TacticalObject":
        return cls(id=str(d.get("id") or new_id()), type=str(d.get("type", "player")),
                   x=float(d.get("x", 50.0)), y=float(d.get("y", 50.0)),
                   rotation=float(d.get("rotation", 0.0)), scale=float(d.get("scale", 1.0)),
                   z=int(d.get("z", 0)), locked=bool(d.get("locked", False)),
                   props=dict(d.get("props") or {}))

    def clone(self, *, fresh_id: bool = True) -> "TacticalObject":
        return TacticalObject.from_dict({**self.to_dict(),
                                         "id": new_id() if fresh_id else self.id})

    def label(self) -> str:
        p = self.props
        if self.type == "player":
            return f"#{p.get('number', '')} {p.get('name', '') or self.type}".strip()
        if self.type in ("text", "number"):
            return str(p.get("text", "") or self.type)
        return self.type.replace("_", " ").title()


@dataclass
class Frame:
    """A snapshot of every object at one coaching moment (Tacticalista-style frame)."""
    id: str
    name: str = ""
    objects: list[TacticalObject] = field(default_factory=list)

    def object(self, object_id: str) -> TacticalObject | None:
        return next((o for o in self.objects if o.id == object_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "objects": [o.to_dict() for o in self.objects]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Frame":
        return cls(id=str(d.get("id") or new_id("frame")), name=str(d.get("name", "")),
                   objects=[TacticalObject.from_dict(o) for o in (d.get("objects") or [])])

    def clone(self, *, name: str | None = None) -> "Frame":
        # keep object ids stable so an object "moves between frames" (the animation)
        return Frame(id=new_id("frame"), name=name if name is not None else self.name,
                     objects=[o.clone(fresh_id=False) for o in self.objects])


@dataclass
class PitchSpec:
    kind: str = "full"                 # full|half|thirds|blank|futsal|custom
    orientation: str = "horizontal"    # horizontal|vertical
    length: float = 105.0              # custom metres (informational)
    width: float = 68.0

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "orientation": self.orientation,
                "length": self.length, "width": self.width}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PitchSpec":
        return cls(kind=str(d.get("kind", "full")), orientation=str(d.get("orientation", "horizontal")),
                   length=float(d.get("length", 105.0)), width=float(d.get("width", 68.0)))


@dataclass
class Board:
    """The whole tactical board: identity + pitch + an ordered list of frames."""
    id: str
    name: str = "Untitled Board"
    pitch: PitchSpec = field(default_factory=PitchSpec)
    frames: list[Frame] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    meta: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.frames:                         # a board always has at least one frame
            self.frames = [Frame(id=new_id("frame"), name="Frame 1")]

    # -- frame access -------------------------------------------------
    def frame(self, index: int) -> Frame:
        index = max(0, min(len(self.frames) - 1, index))
        return self.frames[index]

    def frame_index(self, frame_id: str) -> int:
        return next((i for i, f in enumerate(self.frames) if f.id == frame_id), -1)

    # -- serialization (the single JSON contract) ---------------------
    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "pitch": self.pitch.to_dict(),
                "frames": [f.to_dict() for f in self.frames],
                "created_at": self.created_at, "updated_at": self.updated_at,
                "meta": dict(self.meta), "schema_version": self.schema_version}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Board":
        b = cls(id=str(d.get("id") or new_id("board")), name=str(d.get("name", "Untitled Board")),
                pitch=PitchSpec.from_dict(d.get("pitch") or {}),
                frames=[Frame.from_dict(f) for f in (d.get("frames") or [])],
                created_at=str(d.get("created_at") or _now()),
                updated_at=str(d.get("updated_at") or _now()),
                meta=dict(d.get("meta") or {}),
                schema_version=int(d.get("schema_version", 1)))
        return b

    def touch(self) -> None:
        self.updated_at = _now()


def new_board(name: str = "Untitled Board", *, pitch_kind: str = "full") -> Board:
    return Board(id=new_id("board"), name=name, pitch=PitchSpec(kind=pitch_kind))
