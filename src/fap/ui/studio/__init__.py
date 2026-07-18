"""Professional Visual Report Editor (Phase 6B).

The interactive Canva/PowerPoint-style editor built on the Phase-6A Report Studio
foundation. Everything here is UI: it mutates reports exclusively through
``fap.reports.editor_ops`` applied via ``ReportsManager.update_studio``, and reuses
the visualization registry, ImageStorage, themes, Renderer and CacheManager. It
adds no storage and touches no engine.
"""
from fap.ui.studio.editor import render_studio

__all__ = ["render_studio"]
