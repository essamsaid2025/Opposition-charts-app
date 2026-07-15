"""Platform bootstrap, service lifetime and versioned caching (Phase 2B.2.1).

Regression context: Phase 2B.2 crashed in production because Streamlit's
st.cache_resource kept an ImportService built from the *previous* fap modules
after a deploy. The cached service handed back ColumnMapping objects of a
superseded class, so a method added in that very deploy did not exist on them.
st.cache_resource invalidates on the decorated function's body only, and that
body had not changed.

These tests pin the fix: platform services are cached under a version derived
from the platform's own source, so an implementation change forces a rebuild.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import app
from fap.bootstrap import PlatformContext, init_import_service, init_platform
from fap.core.exceptions import ConfigurationError
from fap.core.services import ServiceRegistry
from fap.core.version import platform_version, source_fingerprint
from fap.pipeline.importer import ImportService


# ---------------------------------------------------------------- version fingerprint
def _module_tree(root: pathlib.Path, body: str = "x = 1\n") -> pathlib.Path:
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "mod.py").write_text(body)
    (root / "pkg" / "__init__.py").write_text("")
    return root


def test_fingerprint_is_stable_when_nothing_changes(tmp_path):
    _module_tree(tmp_path)
    assert source_fingerprint(tmp_path) == source_fingerprint(tmp_path)


def test_fingerprint_changes_when_an_implementation_changes(tmp_path):
    _module_tree(tmp_path)
    before = source_fingerprint(tmp_path)
    (tmp_path / "pkg" / "mod.py").write_text("def confidence_for(): return 1.0\n")
    assert source_fingerprint(tmp_path) != before


def test_fingerprint_changes_when_a_module_is_added(tmp_path):
    _module_tree(tmp_path)
    before = source_fingerprint(tmp_path)
    (tmp_path / "pkg" / "extra.py").write_text("y = 2\n")
    assert source_fingerprint(tmp_path) != before


def test_fingerprint_ignores_bytecode_caches(tmp_path):
    _module_tree(tmp_path)
    before = source_fingerprint(tmp_path)
    cache_dir = tmp_path / "pkg" / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "mod.cpython-313.py").write_text("garbage\n")
    assert source_fingerprint(tmp_path) == before


def test_platform_version_carries_package_version_and_fingerprint():
    from fap import __version__
    version = platform_version()
    assert version.startswith(f"{__version__}+")
    assert len(version.split("+")[1]) == 16


def test_platform_version_is_derived_from_source_not_a_constant():
    """It must come from the platform itself, so nobody has to remember to bump it,
    and the platform must not import its host to work that out."""
    import inspect
    from fap.core import version as version_module
    assert "import streamlit" not in inspect.getsource(version_module)
    assert source_fingerprint() in platform_version()


# ---------------------------------------------------------------- service registry
def test_registry_is_lazy():
    built = []
    reg = ServiceRegistry()
    reg.register("thing", lambda _: built.append(1) or "made")
    assert built == []                    # registration must not construct
    assert not reg.created("thing")
    assert reg.get("thing") == "made"
    assert built == [1]


def test_registry_builds_each_service_once():
    calls = []
    reg = ServiceRegistry()
    reg.register("thing", lambda _: calls.append(1) or object())
    first, second, third = reg.get("thing"), reg.get("thing"), reg.get("thing")
    assert first is second is third
    assert calls == [1]                   # no duplicate instances


def test_registry_resolves_dependencies_through_itself():
    reg = ServiceRegistry()
    reg.register("db", lambda _: {"db": True})
    reg.register("repo", lambda r: {"uses": r.get("db")})
    assert reg.get("repo")["uses"] is reg.get("db")


def test_registry_rejects_duplicate_registration_and_unknown_service():
    reg = ServiceRegistry()
    reg.register("a", lambda _: 1)
    with pytest.raises(ConfigurationError):
        reg.register("a", lambda _: 2)
    with pytest.raises(ConfigurationError):
        reg.get("nope")


def test_registry_replace_discards_the_previous_instance():
    reg = ServiceRegistry()
    reg.register("a", lambda _: "old")
    assert reg.get("a") == "old"
    reg.register("a", lambda _: "new", replace=True)
    assert reg.get("a") == "new"


# ---------------------------------------------------------------- platform context
def test_cold_start_constructs_nothing():
    ctx = init_platform()
    assert isinstance(ctx, PlatformContext)
    assert [n for n in ctx.services.names() if ctx.services.created(n)] == []


def test_services_are_built_on_first_request_only():
    ctx = init_platform()
    assert not ctx.services.created("importer")
    ctx.importer
    assert ctx.services.created("importer")
    assert ctx.services.created("cache") and ctx.services.created("templates")


def test_requesting_one_service_does_not_build_the_others():
    ctx = init_platform()
    ctx.validation
    assert ctx.services.created("validation")
    assert not ctx.services.created("db")        # nothing else paid for


def test_platform_context_hands_out_single_instances():
    ctx = init_platform()
    assert ctx.importer is ctx.importer
    assert ctx.db is ctx.db
    assert ctx.cache is ctx.cache


def test_import_service_receives_its_dependencies_from_the_bootstrap():
    """ImportService must never construct its own collaborators."""
    ctx = init_platform()
    importer = ctx.importer
    assert importer._cache is ctx.cache
    assert importer._templates is ctx.templates
    assert importer._validator is ctx.validation
    assert importer._pipeline is ctx.pipeline


def test_template_repository_shares_the_one_database():
    ctx = init_platform()
    assert ctx.templates._db is ctx.db


def test_platform_context_carries_its_version():
    ctx = init_platform()
    assert ctx.version == platform_version()


# ---------------------------------------------------------------- backwards compatibility
def test_init_import_service_still_works_and_shares_injected_collaborators(tmp_path):
    from fap.cache import CacheManager
    from fap.config.settings import CacheSettings
    from fap.db.engine import Database

    cache = CacheManager(CacheSettings(backend="memory"))
    db = Database(tmp_path / "b.sqlite3")
    importer = init_import_service(cache=cache, db=db)
    assert isinstance(importer, ImportService)
    assert importer._cache is cache
    assert importer._templates._db is db


def test_import_service_constructed_directly_still_works(tmp_path):
    """The historical constructor keeps working for direct use in tests."""
    from fap.cache import CacheManager
    from fap.config.settings import CacheSettings
    from fap.db.engine import Database
    from fap.pipeline.templates import TemplateRepository

    svc = ImportService(CacheManager(CacheSettings(backend="memory")),
                        TemplateRepository(Database(tmp_path / "c.sqlite3")))
    assert svc._validator is not None and svc._pipeline is not None


# ---------------------------------------------------------------- streamlit lifetime
def test_warm_start_reuses_the_cached_platform():
    """Multiple reruns must reuse services, not rebuild them."""
    assert app.platform() is app.platform()
    assert app.import_service() is app.import_service()


def test_import_service_is_resolved_through_the_bootstrap():
    assert app.import_service() is app.platform().importer


def test_streamlit_reload_same_version_reuses_services(monkeypatch):
    """A rerun with no code change must not rebuild anything."""
    monkeypatch.setattr(app, "platform_version", lambda: "fap-test+aaaaaaaaaaaaaaaa")
    first = app.platform()
    second = app.platform()          # simulates the next Streamlit rerun
    assert first is second
    assert first.importer is second.importer


def test_streamlit_reload_after_implementation_change_rebuilds_services(monkeypatch):
    """The Phase 2B.2 outage, reproduced: same app code, changed platform.

    A new fingerprint must produce a new context and a new ImportService, so
    the app can never be served services built from superseded modules.
    """
    monkeypatch.setattr(app, "platform_version", lambda: "fap-test+bbbbbbbbbbbbbbbb")
    before = app.platform()
    before_importer = before.importer

    # platform source changes -> fingerprint changes -> new cache key
    monkeypatch.setattr(app, "platform_version", lambda: "fap-test+cccccccccccccccc")
    after = app.platform()

    assert after is not before
    assert after.importer is not before_importer


def test_cache_invalidation_is_driven_by_the_real_fingerprint(monkeypatch):
    """platform() must key the cache on the platform's own version function."""
    seen = []

    def fake_version():
        seen.append(1)
        return "fap-test+dddddddddddddddd"

    monkeypatch.setattr(app, "platform_version", fake_version)
    app.platform()
    assert seen, "platform() must consult platform_version() on every rerun"
