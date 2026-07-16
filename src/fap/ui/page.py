"""Pages as a plugin family.

A screen in the application shell is a ``Page`` registered in ``page_registry``.
The shell builds its navigation from the registry - role-filtered, grouped by
section, ordered - so there is no switch statement and no ``if page == ...``
chain anywhere. Adding a screen is one class + one registration.

Lazy loading: registering a page is cheap (metadata only). A page's real work
lives in ``render`` and its heavy imports happen inside ``render``, so only the
*active* page ever initializes; the rest are never rendered.
"""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from fap.core.plugin import Plugin, PluginInfo, PluginRegistry
from fap.identity.roles import Role

if TYPE_CHECKING:                       # avoid importing the shell at module load
    from fap.ui.app_shell import ShellContext

# Navigation groups, in display order. A page names its section; unknown
# sections sort last.
NAV_SECTIONS: tuple[str, ...] = ("Overview", "Analysis", "Squad", "Workspace", "Admin")


class Page(Plugin):
    """One screen. ``min_role`` gates visibility; ``section``/``order`` place it
    in the navigation. ``render`` does the Streamlit work (heavy imports here)."""
    section: str = "Workspace"
    icon: str = ""
    order: int = 100
    min_role: Role = Role.READ_ONLY

    @abstractmethod
    def render(self, shell: "ShellContext") -> None: ...

    # sort key: section order, then explicit order, then name
    def sort_key(self) -> tuple[int, int, str]:
        section_rank = (NAV_SECTIONS.index(self.section)
                        if self.section in NAV_SECTIONS else len(NAV_SECTIONS))
        return (section_rank, self.order, self.info.name)


page_registry: PluginRegistry[Page] = PluginRegistry("page")


# -- delegated renderers -----------------------------------------------------
# A page whose body lives outside the shell (the Open Play visualization engine
# in app.py) registers a callback here instead of importing app - which would be
# circular. app.py injects it at startup; the page invokes it on render.
_renderers: dict[str, Callable[[], None]] = {}


def register_renderer(page_id: str, fn: Callable[[], None]) -> None:
    _renderers[page_id] = fn


def get_renderer(page_id: str) -> Callable[[], None] | None:
    return _renderers.get(page_id)


# -- discovery / queries -----------------------------------------------------
def load_builtin_pages() -> None:
    from fap.core.discovery import discover_plugins
    from fap.ui import builtin
    discover_plugins(builtin)


def all_pages() -> list[Page]:
    return sorted((cls() for cls in page_registry), key=lambda p: p.sort_key())


def visible_pages(role: Role) -> list[Page]:
    """Pages this role may see, in navigation order. Never renders anything."""
    return [p for p in all_pages() if role >= p.min_role]


def visible_by_section(role: Role) -> dict[str, list[Page]]:
    grouped: dict[str, list[Page]] = {}
    for page in visible_pages(role):
        grouped.setdefault(page.section, []).append(page)
    return grouped


def get_page(page_id: str) -> Page | None:
    return page_registry.create(page_id) if page_id in page_registry else None


def default_page_id(role: Role) -> str:
    pages = visible_pages(role)
    return pages[0].info.id if pages else ""
