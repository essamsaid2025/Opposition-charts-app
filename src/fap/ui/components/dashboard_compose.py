"""Compose several already-rendered chart PNGs into one dashboard image (PNG/PDF).

A custom dashboard is just a grid of charts the user chose. Each chart is rendered
by the EXISTING engine (or any renderer) to PNG bytes; this module only lays those
images out on a themed grid and exports the sheet — so it adds no chart logic, works
with any visualization, and supports any number of panels. Pure (matplotlib Agg),
no Streamlit.
"""
from __future__ import annotations

from io import BytesIO
from math import ceil
from typing import Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt


def compose_grid(items: Sequence[tuple[str, bytes]], *, title: str = "",
                 subtitle: str = "", columns: int = 2, bg: str = "#0E1117",
                 text: str = "#FFFFFF", fmt: str = "png", dpi: int = 200) -> bytes:
    """Lay out ``items`` (``(caption, png_bytes)``) on a ``columns``-wide grid and
    return the sheet as ``fmt`` bytes. Empty/failed panels degrade to a placeholder;
    an empty item list returns ``b""``."""
    panels = [(str(name), png) for name, png in items if png]
    if not panels:
        return b""
    columns = max(1, min(int(columns), 3))
    rows = ceil(len(panels) / columns)
    has_head = bool(title or subtitle)
    fig = plt.figure(figsize=(columns * 6.2, rows * 4.4 + (0.9 if has_head else 0.2)),
                     facecolor=bg, dpi=dpi)
    for i, (name, png) in enumerate(panels):
        ax = fig.add_subplot(rows, columns, i + 1)
        ax.set_facecolor(bg)
        ax.axis("off")
        try:
            ax.imshow(mpimg.imread(BytesIO(png), format="png"))
        except Exception:
            ax.text(0.5, 0.5, "(could not render)", ha="center", va="center",
                    color=text, fontsize=10, transform=ax.transAxes)
        if name:
            ax.set_title(name, color=text, fontsize=11, fontweight="bold", pad=4)
    if title:
        fig.suptitle(title, color=text, fontsize=18, fontweight="bold", y=0.997)
    if subtitle:
        fig.text(0.5, 0.965, subtitle, color=text, ha="center", va="top",
                 fontsize=10, alpha=0.75)
    fig.subplots_adjust(top=0.92 if has_head else 0.98, bottom=0.02,
                        left=0.02, right=0.98, hspace=0.16, wspace=0.05)
    buf = BytesIO()
    fig.savefig(buf, format=fmt, dpi=dpi, facecolor=bg, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


__all__ = ["compose_grid"]
