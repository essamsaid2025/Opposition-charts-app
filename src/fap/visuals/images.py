"""Image Engine: club/competition/opponent logos, player photos, backgrounds,
watermark images. PNG/JPEG with transparency, resizable, positionable
(anchor presets act as the 'draggable' position control)."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.axes import Axes
from matplotlib.offsetbox import AnnotationBbox, OffsetImage

ANCHORS: dict[str, tuple[float, float]] = {
    "top_left": (0.04, 0.96), "top_center": (0.5, 0.96), "top_right": (0.96, 0.96),
    "center": (0.5, 0.5),
    "bottom_left": (0.04, 0.04), "bottom_center": (0.5, 0.04), "bottom_right": (0.96, 0.04),
}


class ImageEngine:
    @staticmethod
    def load(source: bytes | str | Path) -> np.ndarray:
        """Load PNG/JPEG (alpha preserved) into an RGBA array."""
        from PIL import Image
        img = Image.open(BytesIO(source) if isinstance(source, bytes) else source)
        return np.asarray(img.convert("RGBA"))

    @staticmethod
    def place(ax: Axes, image: np.ndarray, *, anchor: str = "top_right",
              position: tuple[float, float] | None = None, zoom: float = 0.12,
              alpha: float = 1.0, zorder: int = 30) -> AnnotationBbox:
        """Place an image at an anchor preset or explicit axes-fraction
        position (0-1, 0-1). Zoom resizes; alpha supports watermarking."""
        xy = position or ANCHORS.get(anchor, ANCHORS["top_right"])
        box = AnnotationBbox(OffsetImage(image, zoom=zoom, alpha=alpha), xy,
                             xycoords="axes fraction", frameon=False, zorder=zorder)
        ax.add_artist(box)
        return box

    @classmethod
    def logo(cls, ax: Axes, source: bytes | str | Path, *, anchor: str = "top_right",
             zoom: float = 0.12, alpha: float = 1.0) -> AnnotationBbox:
        return cls.place(ax, cls.load(source), anchor=anchor, zoom=zoom, alpha=alpha)

    @classmethod
    def background(cls, ax: Axes, source: bytes | str | Path, *, alpha: float = 0.15) -> None:
        img = cls.load(source)
        ax.imshow(img, extent=[*ax.get_xlim(), *ax.get_ylim()],
                  aspect="auto", alpha=alpha, zorder=-1)
