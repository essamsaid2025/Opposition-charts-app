"""Composition root. The single place where concrete implementations are
constructed and wired (Dependency Injection by hand). Everything downstream
receives its collaborators through AppContext - no globals, no hidden imports.

Two entry points, one wiring:

    init_platform(root) -> PlatformContext   lazy platform services (the layer
                                             an application resolves through)
    init_app(root)      -> AppContext        the full eager application graph,
                                             built on top of init_platform

Nothing outside this module constructs a platform service.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fap.auth.base import Authenticator, auth_registry
from fap.auth.workflow import ensure_bootstrap_admin
from fap.cache import CacheManager
from fap.config import AppSettings, load_settings
from fap.core.events import EventBus
from fap.core.plugin import PluginRegistry
from fap.core.services import ServiceRegistry
from fap.core.version import platform_version
from fap.db import Database
from fap.db.repositories import ProjectRepository, WorkspaceRepository
from fap.exports.base import Exporter, export_registry, load_builtin_exporters
from fap.logging_setup import configure_logging
from fap.metrics.base import Metric, metric_registry, load_builtin_metrics
from fap.pipeline import DataPipeline, ImportService, TemplateRepository
from fap.pipeline.validation import ValidationEngine
from fap.projects import ProjectService
from fap.providers.base import DataProvider, provider_registry, load_builtin_providers
from fap.providers.custom import CustomProviderRepository
from fap.providers.intelligence import ProviderIntelligence
from fap.state import StateManager
from fap.themes import ThemeManager
from fap.visuals.base import Visualization, visual_registry, load_builtin_visuals
from fap.visuals.export import ExportEngine
from fap.visuals.layers.base import Layer, layer_registry
from fap.visuals.layout import LayoutEngine
from fap.visuals.renderer import Renderer
from fap.workspaces import WorkspaceService


@dataclass(slots=True)
class AppContext:
    settings: AppSettings
    state: StateManager
    events: EventBus
    cache: CacheManager
    db: Database
    themes: ThemeManager
    pipeline: DataPipeline
    authenticator: Authenticator
    projects: ProjectService
    workspaces: WorkspaceService
    importer: ImportService
    visuals: PluginRegistry[Visualization]
    metrics: PluginRegistry[Metric]
    providers: PluginRegistry[DataProvider]
    exporters: PluginRegistry[Exporter]
    layers: PluginRegistry[Layer]
    renderer: Renderer
    layouts: LayoutEngine
    export_engine: ExportEngine


@dataclass(slots=True)
class PlatformContext:
    """What an application holds instead of constructing services itself.

    Every property resolves through the ServiceRegistry, so services are built
    on first use and exactly once. ``version`` identifies the implementation
    these services were built from - a host that caches this context must key
    it by that value (see fap.core.version).
    """
    settings: AppSettings
    services: ServiceRegistry
    version: str

    @property
    def cache(self) -> CacheManager:
        return self.services.get("cache")

    @property
    def db(self) -> Database:
        return self.services.get("db")

    @property
    def templates(self) -> TemplateRepository:
        return self.services.get("templates")

    @property
    def providers(self) -> PluginRegistry[DataProvider]:
        return self.services.get("providers")

    @property
    def validation(self) -> ValidationEngine:
        return self.services.get("validation")

    @property
    def pipeline(self) -> DataPipeline:
        return self.services.get("pipeline")

    @property
    def custom_providers(self) -> CustomProviderRepository:
        return self.services.get("custom_providers")

    @property
    def intelligence(self) -> ProviderIntelligence:
        return self.services.get("intelligence")

    @property
    def importer(self) -> ImportService:
        return self.services.get("importer")


def init_platform(root: Path | None = None, *,
                  settings: AppSettings | None = None) -> PlatformContext:
    """Register the platform's services and hand back the context to resolve
    them through. Nothing is constructed here - registration only; the first
    caller of a property pays for that service and nobody pays for the rest.

    Add a future service by registering one more factory: its dependencies come
    from the registry, so it shares the same Database/CacheManager as the rest.
    """
    settings = settings or load_settings(root)
    services = ServiceRegistry()

    def _providers(_: ServiceRegistry) -> PluginRegistry[DataProvider]:
        load_builtin_providers()   # idempotent - registries dedupe by class identity
        return provider_registry

    def _intelligence(reg: ServiceRegistry) -> ProviderIntelligence:
        return ProviderIntelligence(reg.get("providers"))

    def _importer(reg: ServiceRegistry) -> ImportService:
        reg.get("providers")       # discovery must precede any provider lookup
        return ImportService(reg.get("cache"), reg.get("templates"),
                             pipeline=reg.get("pipeline"), validator=reg.get("validation"),
                             intelligence=reg.get("intelligence"),
                             custom_providers=reg.get("custom_providers"))

    services.register("settings", lambda _: settings)
    services.register("cache", lambda _: CacheManager(settings.cache))
    services.register("db", lambda _: Database(settings.database.path))
    services.register("templates", lambda reg: TemplateRepository(reg.get("db")))
    services.register("custom_providers", lambda reg: CustomProviderRepository(reg.get("db")))
    services.register("providers", _providers)
    services.register("intelligence", _intelligence)
    services.register("validation", lambda _: ValidationEngine())
    services.register("pipeline", lambda _: DataPipeline())
    services.register("importer", _importer)

    return PlatformContext(settings=settings, services=services,
                           version=platform_version())


def init_import_service(root: Path | None = None, *, settings: AppSettings | None = None,
                        cache: CacheManager | None = None,
                        db: Database | None = None) -> ImportService:
    """The import engine, resolved through the platform bootstrap.

    Kept for backward compatibility (and used by init_app, which already owns a
    Database/CacheManager it wants shared). Prefer ``init_platform(...).importer``.
    """
    context = init_platform(root, settings=settings)
    if cache is not None:
        context.services.register("cache", lambda _: cache, replace=True)
    if db is not None:
        context.services.register("db", lambda _: db, replace=True)
    context.services.get("providers")      # preserve eager discovery for callers
    return context.importer


def init_app(root: Path | None = None) -> AppContext:
    # The platform layer owns settings/cache/db/importer; init_app adds the
    # application graph (auth, projects, themes, visual engine) on top of it.
    platform = init_platform(root)
    settings = platform.settings
    configure_logging(settings.logging)

    # plugin discovery (idempotent - registries dedupe by class identity)
    load_builtin_providers()
    load_builtin_metrics()
    load_builtin_visuals()
    load_builtin_exporters()

    events = EventBus()
    db = platform.db
    themes = ThemeManager(settings.themes_dir, Path(settings.user_data_dir) / "themes")
    cache = platform.cache

    authenticator = auth_registry.get(settings.auth.provider)(db)  # type: ignore[call-arg]
    if settings.auth.enabled:
        ensure_bootstrap_admin(authenticator)
    projects = ProjectService(ProjectRepository(db), events)
    workspaces = WorkspaceService(WorkspaceRepository(db), events)
    importer = platform.importer

    return AppContext(
        settings=settings, state=StateManager(), events=events, cache=cache, db=db,
        themes=themes, pipeline=DataPipeline(), authenticator=authenticator,
        projects=projects, workspaces=workspaces, importer=importer,
        visuals=visual_registry, metrics=metric_registry,
        providers=provider_registry, exporters=export_registry,
        layers=layer_registry, renderer=Renderer(cache),
        layouts=LayoutEngine(), export_engine=ExportEngine(),
    )
