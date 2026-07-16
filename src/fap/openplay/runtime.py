"""Runtime service access for the Open Play controllers.

The import service is built and cached by the UI layer (app.py, via
``st.cache_resource`` keyed by the platform version). Controllers here must NOT
import Streamlit, so the UI injects that accessor once at startup and the
controllers resolve it through this hook. Headless callers (tests) that never
inject fall back to a fresh platform.

This keeps the dependency graph one-way: UI -> controllers -> services; no
controller ever imports Streamlit.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from fap.pipeline.importer import ImportService

_provider: "Callable[[], ImportService] | None" = None


def set_import_service(provider: "Callable[[], ImportService]") -> None:
    """Injected by the UI: a zero-arg callable returning the ImportService."""
    global _provider
    _provider = provider


def import_service() -> "ImportService":
    if _provider is not None:
        return _provider()
    from fap.bootstrap import init_platform      # headless fallback (no UI injected)
    return init_platform().importer
