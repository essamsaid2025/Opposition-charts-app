"""Report Studio editor (Phase 6D - performance-first, structured editor).

A fast, section-based report editor. All UI: it mutates reports through
``ReportsManager.update_studio`` (autosave) and reuses the studio/block models,
the 6C LayoutEngine + exporters, ImageStorage and the visualization registry.
The old custom-component canvas was removed (it caused the blank-canvas / slow
reloads); charts render once at Export/Refresh, never live. Adds no storage and
touches no engine.
"""
from fap.ui.studio.editor import render_studio

__all__ = ["render_studio"]
