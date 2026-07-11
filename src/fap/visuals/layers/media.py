from __future__ import annotations

from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch

from fap.core.plugin import PluginInfo
from fap.visuals.context import LayerContext
from fap.visuals.images import ImageEngine
from fap.visuals.layers.base import Layer, layer_registry


@layer_registry.register
class ImageLayer(Layer):
    """PNG/JPEG image (player photo, background). Params: source (bytes/path),
    anchor or position (axes fraction), zoom, image_alpha, background (bool)."""
    info = PluginInfo(id="image", name="Image", category="media")
    zorder = 30

    def draw(self, ctx: LayerContext) -> None:
        source = self.params.get("source")
        if source is None:
            return
        if self.params.get("background"):
            ImageEngine.background(ctx.ax, source,
                                   alpha=float(self.p("image_alpha", ctx, 0.15)))
            return
        ImageEngine.place(ctx.ax, ImageEngine.load(source),
                          anchor=self.params.get("anchor", "top_right"),
                          position=self.params.get("position"),
                          zoom=float(self.params.get("zoom", ctx.tokens.get("logo_zoom"))),
                          alpha=float(self.p("image_alpha", ctx)),
                          zorder=self.zorder)


@layer_registry.register
class LogoLayer(ImageLayer):
    """Club/competition/opponent logo - an ImageLayer preset anchored top-right
    with token-driven zoom."""
    info = PluginInfo(id="logo", name="Logo", category="media")
    zorder = 31


@layer_registry.register
class SVGLayer(Layer):
    """Vector icon from SVG path data (M/L/H/V/C/Q/Z commands).
    Params: path (d string), x, y (canonical), scale, color."""
    info = PluginInfo(id="svg", name="SVG icon", category="media")
    zorder = 30

    def draw(self, ctx: LayerContext) -> None:
        d = self.params.get("path", "")
        if not d:
            return
        vertices, codes = _parse_svg_path(d)
        if not vertices:
            return
        import numpy as np
        verts = np.asarray(vertices, dtype=float)
        # normalize to unit box, then scale/translate into display coords
        span = max(float(np.ptp(verts[:, 0])) or 1.0, float(np.ptp(verts[:, 1])) or 1.0)
        verts = (verts - verts.min(axis=0)) / span
        verts[:, 1] = 1 - verts[:, 1]                       # svg y-down -> up
        scale = float(self.params.get("scale", 6.0))
        px, py = ctx.to_display([self.params.get("x", 50)], [self.params.get("y", 50)])
        verts = verts * scale + [px[0] - scale / 2, py[0] - scale / 2]
        patch = PathPatch(MplPath(verts, codes),
                          facecolor=self.params.get("color") or ctx.theme.colors["text"],
                          edgecolor="none", zorder=self.zorder)
        ctx.ax.add_patch(patch)


def _parse_svg_path(d: str) -> tuple[list[tuple[float, float]], list[int]]:
    """Minimal SVG path parser: absolute M, L, H, V, C, Q, Z."""
    import re
    tokens = re.findall(r"([MLHVCQZmlhvcqz])|(-?\d*\.?\d+)", d)
    verts: list[tuple[float, float]] = []
    codes: list[int] = []
    nums: list[float] = []
    cmd = ""
    cur = (0.0, 0.0)

    def flush() -> None:
        nonlocal cur, nums
        while nums:
            if cmd in "Mm":
                cur = (nums[0], nums[1]); nums = nums[2:]
                verts.append(cur); codes.append(MplPath.MOVETO)
            elif cmd in "Ll":
                cur = (nums[0], nums[1]); nums = nums[2:]
                verts.append(cur); codes.append(MplPath.LINETO)
            elif cmd in "Hh":
                cur = (nums[0], cur[1]); nums = nums[1:]
                verts.append(cur); codes.append(MplPath.LINETO)
            elif cmd in "Vv":
                cur = (cur[0], nums[0]); nums = nums[1:]
                verts.append(cur); codes.append(MplPath.LINETO)
            elif cmd in "Cc":
                pts = [(nums[i], nums[i + 1]) for i in range(0, 6, 2)]; nums = nums[6:]
                verts.extend(pts); codes.extend([MplPath.CURVE4] * 3); cur = pts[-1]
            elif cmd in "Qq":
                pts = [(nums[i], nums[i + 1]) for i in range(0, 4, 2)]; nums = nums[4:]
                verts.extend(pts); codes.extend([MplPath.CURVE3] * 2); cur = pts[-1]
            else:
                nums = []

    for letter, number in tokens:
        if letter:
            flush()
            cmd = letter
            if cmd in "Zz" and verts:
                verts.append(verts[0]); codes.append(MplPath.CLOSEPOLY)
        else:
            nums.append(float(number))
    flush()
    return verts, codes
