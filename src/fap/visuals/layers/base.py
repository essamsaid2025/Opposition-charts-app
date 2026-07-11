"""Layer plugin family - the heart of the visualization framework.

A Layer is a small, independently reusable rendering unit. A visualization is
just an ordered list of configured layers; the Renderer draws them onto a
themed pitch/canvas in zorder. New layer types drop into this package and
register - no framework file changes (Open/Closed, same as every other
plugin family).

Styling resolution inside a layer: explicit layer param > control value >
theme token > framework default (see LayerContext.style)."""
from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from typing import Any

from fap.core.plugin import Plugin, PluginRegistry
from fap.visuals.context import LayerContext


class Layer(Plugin):
    zorder: int = 5

    def __init__(self, **params: Any) -> None:
        self.params: dict[str, Any] = params
        if "zorder" in params:
            self.zorder = int(params["zorder"])

    # ------------------------------------------------------------ styling
    def p(self, key: str, ctx: LayerContext, default: Any = None) -> Any:
        """Param -> control -> token -> default."""
        if key in self.params and self.params[key] is not None:
            return self.params[key]
        return ctx.style(key, default)

    # ------------------------------------------------------------ caching
    def signature(self) -> str:
        """Stable hash of this layer's configuration - the change-detection
        key the Renderer uses to skip recomputation of unchanged layers."""
        payload = json.dumps({"id": self.info.id, "params": self.params},
                             sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    # ------------------------------------------------------------ rendering
    @abstractmethod
    def draw(self, ctx: LayerContext) -> None: ...


layer_registry: PluginRegistry[Layer] = PluginRegistry("layer")


def load_builtin_layers() -> None:
    from fap.core.discovery import discover_plugins
    import fap.visuals.layers as pkg
    discover_plugins(pkg)
