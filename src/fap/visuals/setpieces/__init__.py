"""Set-piece visualization library (Phase 9.2).

A dedicated subpackage of ``fap.visuals`` so the plugins live in the
visualization layer and reuse its base classes / pitch / layers / export - but
are NOT discovered by ``load_builtin_visuals`` (which scans only ``maps`` and
``charts``). That isolation matters: set-piece visualizations consume a set-piece
frame, not the canonical event frame, so they must never appear in the generic
Analysis picker. They register into the SAME ``visual_registry`` on demand via
``load_setpiece_visuals`` (idempotent - the module import is cached).
"""
from __future__ import annotations

_LOADED = False


def load_setpiece_visuals() -> None:
    """Register every set-piece visualization into the shared visual_registry.
    Idempotent and cheap after the first call."""
    global _LOADED
    if _LOADED:
        return
    from fap.visuals.layers.base import load_builtin_layers
    load_builtin_layers()                      # ensure the layers we compose exist
    import fap.visuals.setpieces.library        # noqa: F401 - import registers plugins
    _LOADED = True


def setpiece_visual_ids() -> list[str]:
    """Ids of all registered set-piece visualizations, in registration order."""
    load_setpiece_visuals()
    from fap.visuals.setpieces.library import SETPIECE_IDS
    return list(SETPIECE_IDS)


__all__ = ["load_setpiece_visuals", "setpiece_visual_ids"]
