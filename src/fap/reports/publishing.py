"""Publishing settings for the Report Studio - master pages, headers/footers,
watermarks, page numbering, print settings and export presets.

Like the studio overlay, this is stored INSIDE the document (``meta["publish"]``),
so it persists through the existing repository / versioning / autosave with no
schema change and no second storage. It is pure data (JSON round-trip); the
:mod:`fap.reports.layout` engine consumes it, and every exporter consumes the
engine's output - nothing here renders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PUBLISH_META_KEY = "publish"
PUBLISH_SCHEMA_VERSION = 1


# ---------------------------------------------------------------- print geometry
@dataclass(slots=True)
class Margins:
    top: float = 18.0            # millimetres
    right: float = 16.0
    bottom: float = 18.0
    left: float = 16.0


@dataclass(slots=True)
class PrintSettings:
    size: str = ""               # "" = follow each page's own size; else "A4"/"Letter"
    orientation: str = ""        # "" = follow page; else portrait/landscape
    margins: Margins = field(default_factory=Margins)
    bleed_mm: float = 0.0
    safe_area_mm: float = 5.0
    crop_marks: bool = False


# ---------------------------------------------------------------- furniture
@dataclass(slots=True)
class Zone:
    """A header/footer band: three token templates (left / center / right)."""
    left: str = ""
    center: str = ""
    right: str = ""

    def is_empty(self) -> bool:
        return not (self.left or self.center or self.right)


@dataclass(slots=True)
class MasterPage:
    """Reusable page furniture applied to a class of pages (cover / inside / last
    / custom). Headers, footers, logos, background and decorations live here so a
    report styles every page from one place."""
    id: str = "inside"
    name: str = "Inside"
    show_header: bool = True
    header: Zone = field(default_factory=Zone)
    show_footer: bool = True
    footer: Zone = field(default_factory=Zone)
    show_logos: bool = True
    background_color: str = ""
    background_image: str = ""       # image_id
    confidential: bool = False


@dataclass(slots=True)
class Watermark:
    text: str = ""
    image_id: str = ""
    opacity: float = 0.12
    rotation: float = 30.0
    position: str = "center"         # center | tile | topright | ...
    font_size: int = 64
    color: str = ""                  # "" -> theme muted


@dataclass(slots=True)
class PageNumbering:
    enabled: bool = True
    style: str = "arabic"            # arabic | roman | ROMAN
    start: int = 1
    hide_on_cover: bool = True
    prefix: str = ""
    template: str = "{n}"            # e.g. "Page {n} of {total}"
    section_numbering: bool = False


@dataclass(slots=True)
class CoverDesign:
    enabled: bool = True
    background_image: str = ""       # image_id; falls back to Cover.cover_image
    overlay_color: str = "#0b1f3a"
    overlay_opacity: float = 0.35
    alignment: str = "left"          # left | center | right (title default)
    show_logos: bool = True
    # -- designer fields (Phase 6E; all optional, back-compatible) --------
    template: str = "minimal_white"  # named cover template this design came from
    background_color: str = ""       # solid page background (design)
    gradient: bool = False           # two-colour background (preview + solid fallback in export)
    gradient_color: str = ""
    accent_color: str = ""           # divider / rule colour
    title_align: str = ""            # overrides alignment for the title
    subtitle_align: str = ""         # overrides alignment for the subtitle
    logo_position: str = "top"       # top | center | corner
    divider: bool = True             # show an accent divider under the title
    text_color: str = ""             # cover text colour (design)


# ---------------------------------------------------------------- settings root
@dataclass(slots=True)
class PublishSettings:
    preset: str = "professional"
    cover: CoverDesign = field(default_factory=CoverDesign)
    inside_master: MasterPage = field(default_factory=lambda: MasterPage(id="inside", name="Inside"))
    last_master: MasterPage | None = None
    custom_masters: list[MasterPage] = field(default_factory=list)
    watermark: Watermark = field(default_factory=Watermark)
    page_numbering: PageNumbering = field(default_factory=PageNumbering)
    print: PrintSettings = field(default_factory=PrintSettings)
    confidential_label: str = ""
    schema_version: int = PUBLISH_SCHEMA_VERSION

    # -- serialization ------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PublishSettings":
        def zone(z): return Zone(**z) if z else Zone()
        def master(m, dflt_id):
            if not m:
                return MasterPage(id=dflt_id, name=dflt_id.title())
            m = dict(m)
            m["header"] = zone(m.get("header"))
            m["footer"] = zone(m.get("footer"))
            return MasterPage(**m)
        pr = dict(d.get("print", {}) or {})
        pr["margins"] = Margins(**pr["margins"]) if pr.get("margins") else Margins()
        return cls(
            preset=d.get("preset", "professional"),
            cover=CoverDesign(**d["cover"]) if d.get("cover") else CoverDesign(),
            inside_master=master(d.get("inside_master"), "inside"),
            last_master=master(d["last_master"], "last") if d.get("last_master") else None,
            custom_masters=[master(m, m.get("id", "custom")) for m in d.get("custom_masters", [])],
            watermark=Watermark(**d["watermark"]) if d.get("watermark") else Watermark(),
            page_numbering=PageNumbering(**d["page_numbering"]) if d.get("page_numbering") else PageNumbering(),
            print=PrintSettings(**pr) if pr else PrintSettings(),
            confidential_label=d.get("confidential_label", ""),
            schema_version=int(d.get("schema_version", PUBLISH_SCHEMA_VERSION)))

    @classmethod
    def from_document(cls, document: Any) -> "PublishSettings":
        """Load the report's publish settings, or the default preset if none were
        saved (so legacy reports publish with professional defaults)."""
        overlay = (getattr(document, "meta", None) or {}).get(PUBLISH_META_KEY)
        if isinstance(overlay, dict) and overlay:
            return cls.from_dict(overlay)
        return preset("professional")

    def write_to(self, document: Any) -> None:
        meta = dict(getattr(document, "meta", None) or {})
        meta[PUBLISH_META_KEY] = self.to_dict()
        document.meta = meta


# ---------------------------------------------------------------- presets
def _default_header() -> Zone:
    return Zone(left="{club}", center="{competition}", right="{date}")


def _default_footer() -> Zone:
    return Zone(left="{analyst}", center="{confidential}", right="{n}")


def preset(name: str) -> PublishSettings:
    """One of the professional export presets. 'custom' returns the professional
    base for the user to edit."""
    name = (name or "professional").lower()
    base = PublishSettings(
        preset=name,
        inside_master=MasterPage(id="inside", name="Inside",
                                 header=_default_header(), footer=_default_footer()),
    )
    if name in ("professional", "custom"):
        return base
    if name == "presentation":
        base.cover.alignment = "center"
        base.inside_master.header = Zone(center="{competition}")
        base.inside_master.footer = Zone(right="{n}")
        base.page_numbering.template = "{n}"
        base.print.orientation = "landscape"
        return base
    if name == "executive":                       # Executive Summary
        base.inside_master.header = Zone(left="{title}", right="{date}")
        base.inside_master.footer = Zone(left="{analyst}", right="Page {n} of {total}")
        base.page_numbering.template = "Page {n} of {total}"
        return base
    if name == "coach":
        base.inside_master.header = Zone(left="{club}", center="{match}", right="{date}")
        base.inside_master.footer = Zone(left="Coaching report", right="{n}")
        base.watermark = Watermark(text="COACHING", opacity=0.06)
        return base
    if name == "scout":
        base.inside_master.header = Zone(left="{club}", center="Scouting", right="{date}")
        base.inside_master.footer = Zone(left="{analyst}", center="{confidential}", right="{n}")
        base.confidential_label = "CONFIDENTIAL"
        base.watermark = Watermark(text="CONFIDENTIAL", opacity=0.10)
        return base
    if name == "print":
        base.print.bleed_mm = 3.0
        base.print.crop_marks = True
        base.print.margins = Margins(top=12, right=12, bottom=12, left=12)
        return base
    return base


PRESETS: tuple[str, ...] = (
    "professional", "presentation", "executive", "coach", "scout", "print", "custom",
)
