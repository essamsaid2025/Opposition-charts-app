"""Export Engine: every visualization exports identically.

Formats come from the exporter plugin family; this engine adds DPI presets,
transparency, presentation mode, batch export (zip), and clipboard-ready
bytes. New formats = new exporter plugin modules, no engine changes."""
from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Iterable

from matplotlib.figure import Figure

from fap.exports.base import ExportPayload, ExportResult, export_registry
from fap.utils.text import slugify

DPI_PRESETS = {"screen": 160, "standard": 240, "print": 300, "ultra": 600}


class ExportEngine:
    def __init__(self, registry=export_registry) -> None:
        self._registry = registry

    def formats(self) -> list[str]:
        return self._registry.ids()

    # ------------------------------------------------------------ single
    def export(self, fig: Figure, title: str, *, fmt: str = "png",
               dpi: int | str = "standard", transparent: bool = False,
               presentation: bool = False) -> ExportResult:
        resolved_dpi = DPI_PRESETS.get(dpi, dpi) if isinstance(dpi, str) else dpi
        payload = ExportPayload(figure=fig, title=title, meta={
            "dpi": int(resolved_dpi), "transparent": transparent,
            "presentation": presentation,
        })
        return self._registry.create(fmt).export(payload)

    # ------------------------------------------------------------ batch
    def batch(self, items: Iterable[tuple[Figure, str]], *, fmt: str = "png",
              dpi: int | str = "standard", transparent: bool = False,
              archive_name: str = "export_batch") -> ExportResult:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fig, title in items:
                result = self.export(fig, title, fmt=fmt, dpi=dpi, transparent=transparent)
                zf.writestr(result.filename, result.data)
        return ExportResult(buf.getvalue(), "application/zip", f"{slugify(archive_name)}.zip")

    # ------------------------------------------------------------ clipboard
    def clipboard_png(self, fig: Figure, title: str = "chart") -> bytes:
        """PNG bytes suitable for a browser clipboard write (the UI passes
        these to the front-end; servers cannot reach the OS clipboard)."""
        return self.export(fig, title, fmt="png", dpi="screen").data
