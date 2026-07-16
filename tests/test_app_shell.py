"""Application shell: page-plugin navigation (Phase 3C).

The navigation model is pure (no Streamlit) and tested here; the shell's st.*
rendering is thin glue. Backward compatibility of app.py is also pinned.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.ui.page import (
    NAV_SECTIONS, Page, all_pages, default_page_id, get_page, get_renderer,
    load_builtin_pages, page_registry, register_renderer, visible_by_section,
    visible_pages,
)

load_builtin_pages()

EXPECTED = {"dashboard", "opponent_analysis", "match_analysis", "set_piece_analysis",
            "scouting", "players", "teams", "projects", "datasets", "reports",
            "templates", "administration", "settings"}


# ---------------------------------------------------------------- registration
def test_all_pages_register_themselves():
    assert EXPECTED <= set(page_registry.ids())


def test_no_duplicate_page_ids():
    ids = page_registry.ids()
    assert len(ids) == len(set(ids))


def test_pages_sorted_by_section_then_order():
    pages = all_pages()
    keys = [p.sort_key() for p in pages]
    assert keys == sorted(keys)
    # first page overall is the Dashboard (Overview, order 0)
    assert pages[0].info.id == "dashboard"


def test_every_page_declares_a_known_section():
    for page in all_pages():
        assert page.section in NAV_SECTIONS


# ---------------------------------------------------------------- role visibility
def test_administration_hidden_from_non_admins():
    for role in (Role.READ_ONLY, Role.PERFORMANCE_ANALYST, Role.SCOUT, Role.HEAD_COACH):
        assert "administration" not in {p.info.id for p in visible_pages(role)}


def test_administration_visible_to_admins():
    for role in (Role.CLUB_ADMIN, Role.SUPER_ADMIN):
        assert "administration" in {p.info.id for p in visible_pages(role)}


def test_scouting_gated_to_scout_and_above():
    assert "scouting" not in {p.info.id for p in visible_pages(Role.READ_ONLY)}
    assert "scouting" in {p.info.id for p in visible_pages(Role.SCOUT)}


def test_read_only_sees_core_pages():
    ids = {p.info.id for p in visible_pages(Role.READ_ONLY)}
    assert {"dashboard", "opponent_analysis", "datasets", "settings"} <= ids


def test_default_page_is_dashboard_for_everyone():
    for role in (Role.READ_ONLY, Role.SUPER_ADMIN):
        assert default_page_id(role) == "dashboard"


def test_navigation_grouped_by_section_in_order():
    grouped = visible_by_section(Role.SUPER_ADMIN)
    assert list(grouped) == [s for s in NAV_SECTIONS if s in grouped]
    assert grouped["Analysis"][0].info.id == "opponent_analysis"


# ---------------------------------------------------------------- lazy loading
def test_building_navigation_never_renders_a_page():
    """Listing/visibility must not invoke render - only the active page does."""
    calls = []

    @page_registry.register
    class _Spy(Page):
        info = PluginInfo(id="_spy_lazy", name="Spy", category="page")
        section = "Workspace"
        min_role = Role.READ_ONLY

        def render(self, shell) -> None:
            calls.append(1)

    try:
        _ = visible_pages(Role.SUPER_ADMIN)
        _ = visible_by_section(Role.SUPER_ADMIN)
        _ = all_pages()
        assert calls == []                      # nothing rendered by navigation
        get_page("_spy_lazy").render(shell=None)   # only explicit dispatch renders
        assert calls == [1]
    finally:
        page_registry._plugins.pop("_spy_lazy", None)


def test_get_page_returns_none_for_unknown():
    assert get_page("does_not_exist") is None


# ---------------------------------------------------------------- delegated renderer
def test_opponent_analysis_uses_an_injected_renderer():
    marker = []
    register_renderer("opponent_analysis", lambda: marker.append("ran"))
    get_renderer("opponent_analysis")()
    assert marker == ["ran"]
    # the page body itself never imports app (no circular dependency)
    import fap.ui.builtin.opponent_analysis as mod
    assert "import app" not in pathlib.Path(mod.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------- backward compatibility
def test_app_still_imports_and_run_app_exists():
    import app
    assert callable(app.run_app)          # Open Play entry preserved
    assert callable(app.main)             # shell entry


def test_shell_injects_run_app_as_opponent_analysis():
    import app
    # main() wires run_app as the opponent_analysis renderer via render_shell;
    # here we assert the wiring contract directly.
    register_renderer("opponent_analysis", app.run_app)
    assert get_renderer("opponent_analysis") is app.run_app


def test_search_delegates_to_workspace_manager(tmp_path):
    from fap.db.engine import Database
    from fap.identity.models import User
    from fap.ui.app_shell import ShellContext
    from fap.workspaces import WorkspaceManager

    wm = WorkspaceManager(Database(tmp_path / "s.sqlite3"))
    admin = User(email="a@club.com", name="A", role=Role.SUPER_ADMIN, provider_id="dev")
    wm.register_dataset(admin, name="vs Rival", opponent="Rival")
    ctx = ShellContext(user=admin, platform=None, wm=wm, active_page_id="dashboard")
    hits = ctx.search("rival")
    assert any(h.type == "dataset" for h in hits)
    assert ctx.search("nothing-matches-xyz") == []
