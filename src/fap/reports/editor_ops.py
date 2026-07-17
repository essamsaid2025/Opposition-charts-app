"""Editor operations for the Report Studio - pure functions over a ``ReportStudio``.

No Streamlit, no I/O, no rendering. Every function mutates the studio in place and
returns a simple result (``bool`` for "did something change", or the created object),
mirroring the style of the existing :mod:`fap.reports.blocks` layout ops. The editor
UI (a later phase) is a thin caller: it invokes one of these inside
``ReportsManager.update_studio`` so the change is persisted by the existing autosave
path.

Two families:

* block ops  - move / resize / duplicate / delete / hide / lock / z-order /
               rotate / align content / align+distribute groups
* page ops   - create / duplicate / delete / move / reorder

Block content, kinds and rendering are untouched: these ops only move data around
the ``ReportDocument`` and its studio overlay. ``hide`` reuses the canonical
``Block.hidden`` flag (via :func:`fap.reports.blocks.set_hidden`) so exporters keep
one source of truth.
"""
from __future__ import annotations

import uuid
from typing import Any

from fap.reports import blocks as block_ops
from fap.reports.models import Block
from fap.reports.studio import (
    Align, Axis, BlockLayout, Edge, Page, ReportStudio, new_page,
)

# ================================================================ block ops
def _live(studio: ReportStudio, block_id: str) -> tuple[Block | None, BlockLayout | None]:
    return studio.block(block_id), studio.layouts.get(block_id)


def _snap(value: float, studio: ReportStudio) -> float:
    grid = studio.editor.grid_size
    if studio.editor.snap_to_grid and grid > 0:
        return round(value / grid) * grid
    return value


def move_block(studio: ReportStudio, block_id: str, x: float, y: float) -> bool:
    """Move a block to an absolute (x, y) on its page. Snaps to grid when enabled.
    Locked blocks do not move."""
    lay = studio.layouts.get(block_id)
    if lay is None or lay.locked:
        return False
    lay.x, lay.y = _snap(x, studio), _snap(y, studio)
    return True


def nudge_block(studio: ReportStudio, block_id: str, dx: float, dy: float) -> bool:
    lay = studio.layouts.get(block_id)
    if lay is None or lay.locked:
        return False
    return move_block(studio, block_id, lay.x + dx, lay.y + dy)


def resize_block(studio: ReportStudio, block_id: str, width: float, height: float,
                 *, min_size: float = 24.0) -> bool:
    """Resize a block. Snaps to grid when enabled; never smaller than ``min_size``.
    Locked blocks do not resize."""
    lay = studio.layouts.get(block_id)
    if lay is None or lay.locked:
        return False
    lay.width = max(min_size, _snap(width, studio))
    lay.height = max(min_size, _snap(height, studio))
    return True


def set_block_page(studio: ReportStudio, block_id: str, page_id: str) -> bool:
    """Reassign a block to another page (front of that page's stack)."""
    lay = studio.layouts.get(block_id)
    if lay is None or studio.page(page_id) is None:
        return False
    lay.page_id = page_id
    lay.z = studio.max_z(page_id) + 1
    return True


def rotate_block(studio: ReportStudio, block_id: str, degrees: float) -> bool:
    lay = studio.layouts.get(block_id)
    if lay is None or lay.locked:
        return False
    lay.rotation = degrees % 360
    return True


def set_content_alignment(studio: ReportStudio, block_id: str, align: str) -> bool:
    lay = studio.layouts.get(block_id)
    if lay is None:
        return False
    lay.align = align
    return True


def duplicate_block(studio: ReportStudio, block_id: str) -> Block | None:
    """Duplicate a block and its layout (offset slightly, brought to front, unlocked)."""
    block, lay = _live(studio, block_id)
    if block is None or lay is None:
        return None
    copy = Block(id=str(uuid.uuid4()), kind=block.kind, title=block.title,
                 hidden=block.hidden, payload=dict(block.payload))
    src_i = block_ops.index_of(studio.document, block_id)
    studio.document.blocks.insert(src_i + 1, copy)
    studio.layouts[copy.id] = BlockLayout(
        page_id=lay.page_id, x=lay.x + 24, y=lay.y + 24, width=lay.width,
        height=lay.height, z=studio.max_z(lay.page_id) + 1, rotation=lay.rotation,
        locked=False, align=lay.align)
    return copy


def delete_block(studio: ReportStudio, block_id: str) -> bool:
    """Remove a block and its layout. Reuses the canonical document-level delete."""
    if not block_ops.delete_block(studio.document, block_id):
        return False
    studio.layouts.pop(block_id, None)
    if block_id in studio.editor.selected:
        studio.editor.selected.remove(block_id)
    return True


def hide_block(studio: ReportStudio, block_id: str, hidden: bool = True) -> bool:
    """Toggle visibility using the canonical ``Block.hidden`` (honored by exporters)."""
    return block_ops.set_hidden(studio.document, block_id, hidden)


def lock_block(studio: ReportStudio, block_id: str, locked: bool = True) -> bool:
    lay = studio.layouts.get(block_id)
    if lay is None:
        return False
    lay.locked = locked
    return True


# -- z-order (stacking within a page) --------------------------------
def bring_forward(studio: ReportStudio, block_id: str) -> bool:
    return _restack(studio, block_id, +1)


def send_backward(studio: ReportStudio, block_id: str) -> bool:
    return _restack(studio, block_id, -1)


def bring_to_front(studio: ReportStudio, block_id: str) -> bool:
    lay = studio.layouts.get(block_id)
    if lay is None:
        return False
    lay.z = studio.max_z(lay.page_id) + 1
    _normalize_z(studio, lay.page_id)
    return True


def send_to_back(studio: ReportStudio, block_id: str) -> bool:
    lay = studio.layouts.get(block_id)
    if lay is None:
        return False
    lay.z = studio.min_z(lay.page_id) - 1
    _normalize_z(studio, lay.page_id)
    return True


def _restack(studio: ReportStudio, block_id: str, direction: int) -> bool:
    lay = studio.layouts.get(block_id)
    if lay is None:
        return False
    ordered = studio.blocks_on(lay.page_id)
    i = next((k for k, b in enumerate(ordered) if b.id == block_id), -1)
    j = i + direction
    if i < 0 or j < 0 or j >= len(ordered):
        return False
    other = studio.layouts[ordered[j].id]
    lay.z, other.z = other.z, lay.z
    _normalize_z(studio, lay.page_id)
    return True


def _normalize_z(studio: ReportStudio, page_id: str) -> None:
    """Rewrite z-values on a page to a dense 0..n-1 sequence (keeps numbers small
    and stable after repeated re-stacking)."""
    for new_z, block in enumerate(studio.blocks_on(page_id)):
        studio.layouts[block.id].z = new_z


# -- multi-block alignment & distribution ----------------------------
def align_blocks(studio: ReportStudio, block_ids: list[str], edge: str) -> bool:
    """Align a group of blocks to a shared edge/center. Skips locked blocks."""
    lays = [studio.layouts[b] for b in block_ids if b in studio.layouts]
    movable = [l for l in lays if not l.locked]
    if len(movable) < 2:
        return False
    if edge == Edge.LEFT:
        target = min(l.x for l in lays)
        for l in movable: l.x = target
    elif edge == Edge.RIGHT:
        target = max(l.right for l in lays)
        for l in movable: l.x = target - l.width
    elif edge == Edge.TOP:
        target = min(l.y for l in lays)
        for l in movable: l.y = target
    elif edge == Edge.BOTTOM:
        target = max(l.bottom for l in lays)
        for l in movable: l.y = target - l.height
    elif edge == Edge.CENTER_X:
        target = sum(l.center_x for l in lays) / len(lays)
        for l in movable: l.x = target - l.width / 2
    elif edge == Edge.CENTER_Y:
        target = sum(l.center_y for l in lays) / len(lays)
        for l in movable: l.y = target - l.height / 2
    else:
        return False
    return True


def distribute_blocks(studio: ReportStudio, block_ids: list[str],
                      axis: str = Axis.HORIZONTAL) -> bool:
    """Even the gaps between three+ blocks along an axis (edge blocks stay put)."""
    lays = [studio.layouts[b] for b in block_ids if b in studio.layouts]
    if len(lays) < 3:
        return False
    if axis == Axis.HORIZONTAL:
        ordered = sorted(lays, key=lambda l: l.x)
        span = ordered[-1].x - ordered[0].x
        step = span / (len(ordered) - 1)
        for i, l in enumerate(ordered[1:-1], start=1):
            if not l.locked:
                l.x = ordered[0].x + step * i
    elif axis == Axis.VERTICAL:
        ordered = sorted(lays, key=lambda l: l.y)
        span = ordered[-1].y - ordered[0].y
        step = span / (len(ordered) - 1)
        for i, l in enumerate(ordered[1:-1], start=1):
            if not l.locked:
                l.y = ordered[0].y + step * i
    else:
        return False
    return True


# ================================================================ page ops
def create_page(studio: ReportStudio, *, title: str = "", size: str | None = None,
                orientation: str | None = None, at: int | None = None) -> Page:
    """Add a new page. Inherits size/orientation from the active (or last) page
    unless overridden."""
    ref = studio.page(studio.editor.active_page or "") or (studio.pages[-1] if studio.pages else None)
    page = new_page(
        title=title or f"Page {len(studio.pages) + 1}",
        size=size or (ref.size if ref else "A4"),
        orientation=orientation or (ref.orientation if ref else "portrait"))
    if at is None or at >= len(studio.pages):
        studio.pages.append(page)
    else:
        studio.pages.insert(max(at, 0), page)
    studio.editor.active_page = page.id
    return page


def duplicate_page(studio: ReportStudio, page_id: str) -> Page | None:
    """Clone a page and every block on it (new ids, copied layout on the new page)."""
    src = studio.page(page_id)
    if src is None:
        return None
    clone = Page(id=str(uuid.uuid4()), title=f"{src.title or 'Page'} (copy)", size=src.size,
                 orientation=src.orientation, background=src.background,
                 background_color=src.background_color, margin=src.margin, columns=src.columns)
    idx = studio.page_index(page_id)
    studio.pages.insert(idx + 1, clone)
    for block in studio.blocks_on(page_id):
        src_lay = studio.layouts[block.id]
        copy = Block(id=str(uuid.uuid4()), kind=block.kind, title=block.title,
                     hidden=block.hidden, payload=dict(block.payload))
        studio.document.blocks.append(copy)
        studio.layouts[copy.id] = BlockLayout(
            page_id=clone.id, x=src_lay.x, y=src_lay.y, width=src_lay.width,
            height=src_lay.height, z=src_lay.z, rotation=src_lay.rotation,
            locked=src_lay.locked, align=src_lay.align)
    studio.editor.active_page = clone.id
    return clone


def delete_page(studio: ReportStudio, page_id: str) -> bool:
    """Delete a page and all blocks living on it. Refuses to delete the last page."""
    if len(studio.pages) <= 1 or studio.page(page_id) is None:
        return False
    for block in list(studio.blocks_on(page_id)):
        delete_block(studio, block.id)
    idx = studio.page_index(page_id)
    studio.pages.pop(idx)
    if studio.editor.active_page == page_id:
        studio.editor.active_page = studio.pages[min(idx, len(studio.pages) - 1)].id
    return True


def move_page(studio: ReportStudio, page_id: str, delta: int) -> bool:
    """Move a page earlier (-1) or later (+1) in the report."""
    i = studio.page_index(page_id)
    if i < 0:
        return False
    j = max(0, min(len(studio.pages) - 1, i + delta))
    if i == j:
        return False
    studio.pages.insert(j, studio.pages.pop(i))
    return True


def reorder_pages(studio: ReportStudio, ordered_ids: list[str]) -> None:
    """Apply an explicit page order; pages omitted keep their relative tail order."""
    by_id = {p.id: p for p in studio.pages}
    ordered = [by_id[i] for i in ordered_ids if i in by_id]
    ordered += [p for p in studio.pages if p.id not in set(ordered_ids)]
    studio.pages = ordered


# ================================================================ block creation on a page
def add_block_to_page(studio: ReportStudio, block: Block, page_id: str | None = None,
                      *, x: float = 40.0, y: float = 40.0,
                      width: float = 520.0, height: float = 220.0) -> Block:
    """Append a block to the document and place it on a page (front of the stack).
    Reuses the existing document-level ``add_block`` so ordering/back-compat hold."""
    page_id = page_id or studio.editor.active_page or (studio.pages[0].id if studio.pages else "")
    block_ops.add_block(studio.document, block)
    studio.layouts[block.id] = BlockLayout(
        page_id=page_id, x=_snap(x, studio), y=_snap(y, studio),
        width=width, height=height, z=studio.max_z(page_id) + 1)
    return block


__all__ = [
    # block ops
    "move_block", "nudge_block", "resize_block", "set_block_page", "rotate_block",
    "set_content_alignment", "duplicate_block", "delete_block", "hide_block",
    "lock_block", "bring_forward", "send_backward", "bring_to_front", "send_to_back",
    "align_blocks", "distribute_blocks", "add_block_to_page",
    # page ops
    "create_page", "duplicate_page", "delete_page", "move_page", "reorder_pages",
]
