"""Report Studio - the editable, page-based representation of a ReportDocument.

This is an OVERLAY, not a replacement. A ``ReportStudio`` is built from a
``ReportDocument`` and writes back into it: the studio-specific data (pages,
per-block layout, editor state) lives in ``document.meta["studio"]``, while the
document's flat ``blocks`` list stays the canonical render/export surface. That
single decision is what keeps the whole phase backward compatible:

* every existing exporter/renderer keeps reading ``document.blocks`` (unchanged);
* persistence, versioning and autosave already store the document dict wholesale,
  so the overlay is saved/versioned/autosaved with **no schema change and no
  second storage**;
* a report saved before this phase has no overlay - ``from_document`` synthesizes
  one default page and a flow layout for it, so old reports load untouched.

Pure data and pure geometry: no Streamlit, no I/O, no rendering. All mutation is
done through :mod:`fap.reports.editor_ops`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fap.reports.models import Block, ReportDocument

#: Version of the studio overlay payload (independent of the document schema).
#: Bump + migrate in ``_hydrate`` when the overlay shape changes.
STUDIO_SCHEMA_VERSION = 1

#: Where the overlay is stored inside the document (kept out of ``blocks`` so the
#: flat list the exporters read never changes shape).
STUDIO_META_KEY = "studio"


# ---------------------------------------------------------------- alignment
class Align:
    """Text alignment tokens for a block's own content."""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class Edge:
    """Multi-block alignment edges (align_blocks)."""
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    CENTER_X = "center_x"       # align horizontal centers
    CENTER_Y = "center_y"       # align vertical centers


class Axis:
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


# ---------------------------------------------------------------- page size
def _mm_to_px(mm: float, dpi: int = 96) -> int:
    return round(mm / 25.4 * dpi)


@dataclass(slots=True)
class PageSize:
    """A named paper size in millimetres; pixel geometry is derived on demand
    so the editor can render at any DPI/zoom without storing device units."""
    name: str
    width_mm: float
    height_mm: float

    def pixels(self, orientation: str = "portrait", dpi: int = 96) -> tuple[int, int]:
        w, h = _mm_to_px(self.width_mm, dpi), _mm_to_px(self.height_mm, dpi)
        return (h, w) if orientation == "landscape" else (w, h)


A4 = PageSize("A4", 210.0, 297.0)
LETTER = PageSize("Letter", 215.9, 279.4)
PAGE_SIZES: dict[str, PageSize] = {A4.name: A4, LETTER.name: LETTER}
DEFAULT_PAGE_SIZE = A4.name


def page_size(name: str) -> PageSize:
    return PAGE_SIZES.get(name, A4)


# ---------------------------------------------------------------- block layout
@dataclass(slots=True)
class BlockLayout:
    """Where and how one block sits on its page.

    Geometry is in page pixels at 96 DPI (the editor scales by ``EditorState.zoom``).
    ``hidden`` is intentionally NOT stored here: it already lives on ``Block.hidden``
    - the canonical flag every exporter honors - and the studio reads through to it
    so there is one source of truth. Everything else (position, size, stacking,
    rotation, lock, content alignment, owning page) lives here.
    """
    page_id: str
    x: float = 40.0
    y: float = 40.0
    width: float = 520.0
    height: float = 220.0
    z: int = 0                       # stacking order within the page (higher = front)
    rotation: float = 0.0            # degrees
    locked: bool = False
    align: str = Align.LEFT          # the block's own content alignment

    def to_dict(self) -> dict[str, Any]:
        return {"page_id": self.page_id, "x": self.x, "y": self.y,
                "width": self.width, "height": self.height, "z": self.z,
                "rotation": self.rotation, "locked": self.locked, "align": self.align}

    @classmethod
    def from_dict(cls, d: dict[str, Any], *, page_id: str) -> "BlockLayout":
        return cls(
            page_id=d.get("page_id") or page_id,
            x=float(d.get("x", 40.0)), y=float(d.get("y", 40.0)),
            width=float(d.get("width", 520.0)), height=float(d.get("height", 220.0)),
            z=int(d.get("z", 0)), rotation=float(d.get("rotation", 0.0)),
            locked=bool(d.get("locked", False)), align=str(d.get("align", Align.LEFT)))

    # geometry helpers (pure) -----------------------------------------
    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2


# ---------------------------------------------------------------- page
@dataclass(slots=True)
class Page:
    """One canvas in the report. Blocks are assigned to a page via their layout's
    ``page_id`` (a page does not own a block list - the document's flat block list
    stays the single source of truth; the page is just a coordinate space)."""
    id: str
    title: str = ""
    size: str = DEFAULT_PAGE_SIZE            # "A4" | "Letter"
    orientation: str = "portrait"            # portrait | landscape
    background: str = ""                     # image_id of a background image (optional)
    background_color: str = ""               # optional solid fill
    margin: float = 40.0                     # px guide margin
    columns: int = 1                         # multi-column guide count (layout aid)

    def dimensions(self, dpi: int = 96) -> tuple[int, int]:
        return page_size(self.size).pixels(self.orientation, dpi)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "size": self.size,
                "orientation": self.orientation, "background": self.background,
                "background_color": self.background_color, "margin": self.margin,
                "columns": self.columns}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Page":
        return cls(
            id=d["id"], title=d.get("title", ""), size=d.get("size", DEFAULT_PAGE_SIZE),
            orientation=d.get("orientation", "portrait"), background=d.get("background", ""),
            background_color=d.get("background_color", ""), margin=float(d.get("margin", 40.0)),
            columns=int(d.get("columns", 1)))


def new_page(title: str = "", size: str = DEFAULT_PAGE_SIZE,
             orientation: str = "portrait") -> Page:
    return Page(id=str(uuid.uuid4()), title=title, size=size, orientation=orientation)


# ---------------------------------------------------------------- editor state
@dataclass(slots=True)
class EditorState:
    """The editor's own working state - persisted WITH the report (in the overlay),
    never in session_state. Only *navigation* (which report is open) belongs to the
    UI layer; zoom, selection, active page and the guide toggles belong here."""
    zoom: float = 1.0
    selected: list[str] = field(default_factory=list)   # selected block ids
    active_page: str | None = None
    snap_to_grid: bool = True
    grid_size: int = 8
    guides: bool = True
    rulers: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"zoom": self.zoom, "selected": list(self.selected),
                "active_page": self.active_page, "snap_to_grid": self.snap_to_grid,
                "grid_size": self.grid_size, "guides": self.guides, "rulers": self.rulers}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EditorState":
        return cls(
            zoom=float(d.get("zoom", 1.0)), selected=list(d.get("selected", [])),
            active_page=d.get("active_page"), snap_to_grid=bool(d.get("snap_to_grid", True)),
            grid_size=int(d.get("grid_size", 8)), guides=bool(d.get("guides", True)),
            rulers=bool(d.get("rulers", True)))


# ---------------------------------------------------------------- studio
#: default flow layout used when synthesizing an overlay for a legacy report
_FLOW_X = 40.0
_FLOW_TOP = 40.0
_FLOW_W = 520.0
_FLOW_H = 220.0
_FLOW_GAP = 24.0


@dataclass(slots=True)
class ReportStudio:
    """Editable, page-based view over a ``ReportDocument``.

    Build with :meth:`from_document`, mutate through :mod:`fap.reports.editor_ops`,
    then :meth:`to_document` to fold the overlay back into the document before it is
    handed to the (unchanged) ``ReportsManager`` persistence path.
    """
    document: ReportDocument
    pages: list[Page] = field(default_factory=list)
    layouts: dict[str, BlockLayout] = field(default_factory=dict)  # block_id -> layout
    editor: EditorState = field(default_factory=EditorState)
    schema_version: int = STUDIO_SCHEMA_VERSION

    # -- construction -------------------------------------------------
    @classmethod
    def from_document(cls, document: ReportDocument) -> "ReportStudio":
        overlay = (document.meta or {}).get(STUDIO_META_KEY)
        if isinstance(overlay, dict) and overlay.get("pages"):
            studio = cls._hydrate(document, overlay)
        else:
            studio = cls._synthesize(document)
        studio._reconcile()
        return studio

    @classmethod
    def _hydrate(cls, document: ReportDocument, overlay: dict[str, Any]) -> "ReportStudio":
        pages = [Page.from_dict(p) for p in overlay.get("pages", [])]
        first = pages[0].id if pages else str(uuid.uuid4())
        layouts = {bid: BlockLayout.from_dict(ld, page_id=first)
                   for bid, ld in overlay.get("layouts", {}).items()}
        editor = EditorState.from_dict(overlay.get("editor", {}))
        return cls(document=document, pages=pages, layouts=layouts, editor=editor,
                   schema_version=int(overlay.get("schema_version", STUDIO_SCHEMA_VERSION)))

    @classmethod
    def _synthesize(cls, document: ReportDocument) -> "ReportStudio":
        """A legacy report (no overlay) becomes one page with its existing blocks
        stacked in a simple vertical flow - so it opens in the studio unchanged."""
        page = new_page(title=document.title or "Page 1")
        layouts: dict[str, BlockLayout] = {}
        y = _FLOW_TOP
        for block in document.blocks:
            layouts[block.id] = BlockLayout(page_id=page.id, x=_FLOW_X, y=y,
                                            width=_FLOW_W, height=_FLOW_H, z=0)
            y += _FLOW_H + _FLOW_GAP
        editor = EditorState(active_page=page.id)
        return cls(document=document, pages=[page], layouts=layouts, editor=editor)

    # -- invariants ---------------------------------------------------
    def _reconcile(self) -> None:
        """Keep the overlay consistent with the document's block list:
        guarantee >=1 page, give every block a layout on a valid page, drop layouts
        for deleted blocks, and normalize the editor's active page/selection."""
        if not self.pages:
            self.pages = [new_page(title="Page 1")]
        page_ids = {p.id for p in self.pages}
        default_page = self.pages[0].id

        block_ids = {b.id for b in self.document.blocks}
        # prune orphans
        for orphan in [bid for bid in self.layouts if bid not in block_ids]:
            del self.layouts[orphan]
        # ensure every block has a layout, on a page that exists
        y = _flow_start(self.layouts, default_page)
        for block in self.document.blocks:
            lay = self.layouts.get(block.id)
            if lay is None:
                self.layouts[block.id] = BlockLayout(page_id=default_page, x=_FLOW_X, y=y,
                                                     width=_FLOW_W, height=_FLOW_H)
                y += _FLOW_H + _FLOW_GAP
            elif lay.page_id not in page_ids:
                lay.page_id = default_page

        if self.editor.active_page not in page_ids:
            self.editor.active_page = default_page
        self.editor.selected = [b for b in self.editor.selected if b in block_ids]

    # -- queries (pure) ----------------------------------------------
    def page(self, page_id: str) -> Page | None:
        return next((p for p in self.pages if p.id == page_id), None)

    def page_index(self, page_id: str) -> int:
        return next((i for i, p in enumerate(self.pages) if p.id == page_id), -1)

    def layout(self, block_id: str) -> BlockLayout | None:
        return self.layouts.get(block_id)

    def block(self, block_id: str) -> Block | None:
        return next((b for b in self.document.blocks if b.id == block_id), None)

    def blocks_on(self, page_id: str) -> list[Block]:
        """Blocks assigned to a page, ordered back-to-front by z (then document
        order as a stable tie-break)."""
        order = {b.id: i for i, b in enumerate(self.document.blocks)}
        on = [b for b in self.document.blocks
              if (self.layouts.get(b.id) or _MISSING).page_id == page_id]
        return sorted(on, key=lambda b: (self.layouts[b.id].z, order[b.id]))

    def max_z(self, page_id: str) -> int:
        zs = [l.z for l in self.layouts.values() if l.page_id == page_id]
        return max(zs) if zs else 0

    def min_z(self, page_id: str) -> int:
        zs = [l.z for l in self.layouts.values() if l.page_id == page_id]
        return min(zs) if zs else 0

    # -- serialization ------------------------------------------------
    def to_document(self) -> ReportDocument:
        """Fold the overlay back into the document and return it. Also re-syncs the
        flat ``document.blocks`` order to page order then z order, so unchanged
        exporters lay blocks out in the same order the studio shows them."""
        self._reconcile()
        page_pos = {p.id: i for i, p in enumerate(self.pages)}
        doc_pos = {b.id: i for i, b in enumerate(self.document.blocks)}

        def sort_key(b: Block) -> tuple[int, int, int]:
            lay = self.layouts[b.id]
            return (page_pos.get(lay.page_id, 0), lay.z, doc_pos[b.id])

        self.document.blocks = sorted(self.document.blocks, key=sort_key)
        meta = dict(self.document.meta or {})
        meta[STUDIO_META_KEY] = self.to_overlay()
        self.document.meta = meta
        return self.document

    def to_overlay(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pages": [p.to_dict() for p in self.pages],
            "layouts": {bid: lay.to_dict() for bid, lay in self.layouts.items()},
            "editor": self.editor.to_dict(),
        }


# ---------------------------------------------------------------- internals
class _Missing:
    page_id = None


_MISSING = _Missing()


def _flow_start(layouts: dict[str, BlockLayout], page_id: str) -> float:
    used = [l.bottom for l in layouts.values() if l.page_id == page_id]
    return (max(used) + _FLOW_GAP) if used else _FLOW_TOP
