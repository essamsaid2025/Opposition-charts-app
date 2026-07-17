"""Report blocks: factories, layout operations, and chart regeneration.

Layout operations are pure functions over a document's block list (add, delete,
duplicate, move, hide) so the editor UI holds no logic and the model stays the
single source of truth.

Chart blocks store only a REFERENCE (viz_id + controls). ``ChartBlockRenderer``
regenerates the image at export time from the saved dataset by reusing the
platform's own visualization Renderer - no chart code is duplicated and no
image is stored twice.
"""
from __future__ import annotations

import base64
import logging
import uuid
from typing import Any

import pandas as pd

from fap.reports.models import Block, ReportDocument

logger = logging.getLogger(__name__)

TEXT, IMAGE, CHART = "text", "image", "chart"
BLOCK_KINDS: tuple[str, ...] = (TEXT, IMAGE, CHART)


# ---------------------------------------------------------------- factories
def text_block(text: str = "", title: str = "") -> Block:
    return Block(id=str(uuid.uuid4()), kind=TEXT, title=title, payload={"text": text})


def image_block(image_id: str, caption: str = "", width_pct: int = 100,
                title: str = "") -> Block:
    return Block(id=str(uuid.uuid4()), kind=IMAGE, title=title,
                 payload={"image_id": image_id, "caption": caption,
                          "width_pct": int(width_pct)})


def chart_block(viz_id: str, controls: dict[str, Any] | None = None, caption: str = "",
                title: str = "") -> Block:
    return Block(id=str(uuid.uuid4()), kind=CHART, title=title,
                 payload={"viz_id": viz_id, "controls": dict(controls or {}),
                          "caption": caption})


# ---------------------------------------------------------------- layout ops (pure)
def index_of(document: ReportDocument, block_id: str) -> int:
    for i, b in enumerate(document.blocks):
        if b.id == block_id:
            return i
    return -1


def add_block(document: ReportDocument, block: Block, at: int | None = None) -> Block:
    if at is None or at >= len(document.blocks):
        document.blocks.append(block)
    else:
        document.blocks.insert(max(at, 0), block)
    return block


def delete_block(document: ReportDocument, block_id: str) -> bool:
    i = index_of(document, block_id)
    if i < 0:
        return False
    document.blocks.pop(i)
    return True


def duplicate_block(document: ReportDocument, block_id: str) -> Block | None:
    i = index_of(document, block_id)
    if i < 0:
        return None
    src = document.blocks[i]
    copy = Block(id=str(uuid.uuid4()), kind=src.kind, title=src.title,
                 hidden=src.hidden, payload=dict(src.payload))
    document.blocks.insert(i + 1, copy)
    return copy


def move_block(document: ReportDocument, block_id: str, delta: int) -> bool:
    """Move up (-1) / down (+1). Also the primitive a drag-reorder UI calls."""
    i = index_of(document, block_id)
    if i < 0:
        return False
    j = max(0, min(len(document.blocks) - 1, i + delta))
    if i == j:
        return False
    document.blocks.insert(j, document.blocks.pop(i))
    return True


def reorder_blocks(document: ReportDocument, ordered_ids: list[str]) -> None:
    """Apply an explicit order (drag-and-drop ready): ids not listed keep their
    relative position at the end."""
    by_id = {b.id: b for b in document.blocks}
    ordered = [by_id[i] for i in ordered_ids if i in by_id]
    ordered += [b for b in document.blocks if b.id not in set(ordered_ids)]
    document.blocks = ordered


def set_hidden(document: ReportDocument, block_id: str, hidden: bool) -> bool:
    i = index_of(document, block_id)
    if i < 0:
        return False
    document.blocks[i].hidden = hidden
    return True


def visible_blocks(document: ReportDocument) -> list[Block]:
    return [b for b in document.blocks if not b.hidden]


# ---------------------------------------------------------------- chart regeneration
class ChartBlockRenderer:
    """Regenerates chart blocks from the saved dataset, reusing the platform
    visualization Renderer (byte-cached). Never draws anything itself."""

    def __init__(self, themes: Any = None, cache: Any = None, theme_id: str = "opta_light") -> None:
        self._themes = themes
        self._cache = cache
        self._theme_id = theme_id

    def _theme(self, override: str | None = None):
        if self._themes is None:
            return None
        try:
            return self._themes.get(override or self._theme_id)
        except Exception:
            return None

    def render_png(self, viz_id: str, frame: pd.DataFrame, controls: dict[str, Any],
                   theme_id: str | None = None, dpi: int = 160) -> bytes | None:
        """PNG bytes for one visualization, or None if it cannot be rendered."""
        try:
            from fap.core.types import RenderContext
            from fap.visuals.base import load_builtin_visuals, visual_registry
            from fap.visuals.renderer import Renderer

            load_builtin_visuals()
            if viz_id not in visual_registry:
                return None
            theme = self._theme(theme_id)
            if theme is None:
                return None
            viz = visual_registry.create(viz_id)
            ctx = RenderContext(df=frame, theme=theme, controls=dict(controls or {}))
            return Renderer(self._cache).render_png(viz, ctx, dpi=dpi)
        except Exception:
            logger.exception("Chart block %s could not be regenerated", viz_id)
            return None

    def materialize(self, document: ReportDocument, frame: pd.DataFrame | None,
                    theme_id: str | None = None, dpi: int = 160) -> ReportDocument:
        """Fill every visible chart block's ``image_b64`` from the dataset, so
        exporters embed images and never touch the visualization engine.
        Deterministic: same document + same data -> same bytes."""
        if frame is None:
            return document
        for block in document.blocks:
            if block.kind != CHART or block.hidden:
                continue
            png = self.render_png(block.payload.get("viz_id", ""), frame,
                                  block.payload.get("controls", {}), theme_id, dpi)
            if png:
                block.payload["image_b64"] = base64.b64encode(png).decode("ascii")
        return document
