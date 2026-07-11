"""Annotation Engine: coach-editable, serializable annotations rendered by
the AnnotationLayer. Because AnnotationSet round-trips to plain dicts, it
persists inside project documents like everything else."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

KINDS = ("text", "callout", "box", "circle", "number", "arrow",
         "area_highlight", "player_highlight", "coach_note")


@dataclass(slots=True)
class Annotation:
    kind: str
    x: float                       # canonical 0-100
    y: float                       # canonical 0-100
    text: str = ""
    x2: float | None = None        # target (callout / arrow) or extent (box)
    y2: float | None = None
    color: str | None = None
    size: float | None = None      # radius / font size depending on kind
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AnnotationSet:
    def __init__(self, annotations: list[Annotation] | None = None) -> None:
        self._items: dict[str, Annotation] = {a.id: a for a in (annotations or [])}

    # ------------------------------------------------------------ editing
    def add(self, kind: str, x: float, y: float, **kwargs: Any) -> Annotation:
        if kind not in KINDS:
            raise ValueError(f"Unknown annotation kind {kind!r}; expected one of {KINDS}")
        ann = Annotation(kind=kind, x=x, y=y, **kwargs)
        self._items[ann.id] = ann
        return ann

    def update(self, annotation_id: str, **changes: Any) -> None:
        ann = self._items[annotation_id]
        for key, value in changes.items():
            setattr(ann, key, value)

    def remove(self, annotation_id: str) -> None:
        self._items.pop(annotation_id, None)

    def clear(self) -> None:
        self._items.clear()

    @property
    def items(self) -> list[Annotation]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self._items.values()]

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> "AnnotationSet":
        return cls([Annotation(**{k: v for k, v in d.items()
                                  if k in Annotation.__dataclass_fields__}) for d in data])
