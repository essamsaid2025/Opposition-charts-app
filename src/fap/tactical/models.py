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
    "arrow", "curved_arrow", "dashed_arrow", "line", "freehand",
    "zone", "highlight", "circle", "text", "number", "shape", "image",
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
    """A snapshot of every object at one coaching moment (Tacticalista-style frame).

    ``duration_ms`` is how long this frame is held in an animated (GIF) export;
    it is additive with a sensible default, so old saved boards that never stored
    it load unchanged (``from_dict`` just fills the default)."""
    id: str
    name: str = ""
    objects: list[TacticalObject] = field(default_factory=list)
    duration_ms: int = 800

    def object(self, object_id: str) -> TacticalObject | None:
        return next((o for o in self.objects if o.id == object_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "duration_ms": self.duration_ms,
                "objects": [o.to_dict() for o in self.objects]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Frame":
        try:
            duration = int(d.get("duration_ms", 800))
        except (TypeError, ValueError):
            duration = 800
        return cls(id=str(d.get("id") or new_id("frame")), name=str(d.get("name", "")),
                   duration_ms=duration if duration > 0 else 800,
                   objects=[TacticalObject.from_dict(o) for o in (d.get("objects") or [])])

    def clone(self, *, name: str | None = None) -> "Frame":
        # keep object ids stable so an object "moves between frames" (the animation)
        return Frame(id=new_id("frame"), name=name if name is not None else self.name,
                     duration_ms=self.duration_ms,
                     objects=[o.clone(fresh_id=False) for o in self.objects])


#: how far (in 0-100 pitch units) a "sticky" ball sits from its player's centre, so it renders
#: at the player's feet (down-right, dribbling pose) rather than on top of the marker. The x/y
#: split roughly matches an equal on-screen pixel offset on the 1050x680 plane (_H/_W ~ 0.65).
BALL_ATTACH_OFFSET: tuple[float, float] = (1.8, 2.6)


def resolve_position(frame: "Frame", obj: "TacticalObject") -> tuple[float, float]:
    """The (x, y) an object should DRAW at, in 0-100 pitch space. This is the SINGLE source of
    truth both renderers (``render.py`` and ``export_render.py``) call for balls, so the live
    board and every export stay in lockstep.

    Identical to ``obj.x``/``obj.y`` for everything EXCEPT a ball whose ``props['attached_to']``
    holds the id of a player STILL present in ``frame`` - then it returns that player's current
    position plus ``BALL_ATTACH_OFFSET`` (clamped to the pitch), so the ball sticks to the player
    and moves with them across frames. A ball with no ``attached_to`` (every existing board) hits
    the fallback and is a pure no-op. Never raises."""
    if obj.type == "ball":
        pid = str((obj.props or {}).get("attached_to") or "")
        if pid:
            player = frame.object(pid)
            if player is not None and player.type == "player":
                dx, dy = BALL_ATTACH_OFFSET
                return (min(100.0, max(0.0, player.x + dx)),
                        min(100.0, max(0.0, player.y + dy)))
    return (obj.x, obj.y)


def nearest_player(x: float, y: float, players: "list[TacticalObject]") -> "TacticalObject | None":
    """The player nearest to (x, y) by straight-line pitch distance (0-100 space), or ``None``
    if ``players`` is empty. Pure - used to pick which player a ball sticks to."""
    best: "TacticalObject | None" = None
    best_d: float | None = None
    for p in players:
        d = (p.x - x) ** 2 + (p.y - y) ** 2          # squared distance is fine for comparison
        if best_d is None or d < best_d:
            best, best_d = p, d
    return best


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
