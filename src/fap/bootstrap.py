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
from fap.reports import ReportsManager
from fap.storage import (
    DatasetStorage, LocalFileStorage, LocalImageStorage, ObjectDatasetStorage,
    ObjectFileStorage, ObjectImageStorage, ParquetDatasetStorage, make_object_store,
)
from fap.workspaces import WorkspaceManager, WorkspaceService


def _reports_manager(reg: "ServiceRegistry") -> ReportsManager:
    """Reports engine over the shared platform services: DB, branding, image
    storage, figure themes, cache, and the workspace's dataset frames (so chart
    blocks regenerate from the saved dataset at export). Headless-safe."""
    try:
        from fap.theme import DEFAULT_BRANDING
        branding = DEFAULT_BRANDING
    except Exception:
        branding = None
    workspace = reg.get("workspace_manager")
    return ReportsManager(
        reg.get("db"), branding=branding,
        frame_provider=workspace.dataset_frame,      # reuse persistent dataset storage
        images=reg.get("image_storage"),
        themes=reg.get("themes"),
        cache=reg.get("cache"))


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

    @property
    def dataset_storage(self) -> DatasetStorage:
        return self.services.get("dataset_storage")

    @property
    def workspace_manager(self) -> WorkspaceManager:
        return self.services.get("workspace_manager")

    @property
    def reports(self) -> "ReportsManager":
        return self.services.get("reports")

    @property
    def permissions(self):
        """Capability-based authorization decision service (Phase 7.1)."""
        return self.services.get("permissions")

    @property
    def administration(self):
        """Enterprise administration façade: users, roles, invitations, sessions,
        scoped grants and storage (Phase 7.1)."""
        return self.services.get("administration")

    @property
    def scouting(self):
        """Professional scouting platform: player database, notes, videos, media,
        attachments, watchlists and Studio-integrated reports (Phase 8.0)."""
        return self.services.get("scouting")

    @property
    def setpieces(self):
        """Professional set-piece analysis platform: provider-agnostic set-piece
        event store, box-occupancy positions, contact events, manual tagging and
        CSV/Excel/JSON import; analytics/reports extend it in 9.1+ (Phase 9.0)."""
        return self.services.get("setpieces")

    @property
    def players(self):
        """First Team Players platform: our own squad — roster, contracts, medical,
        training/GPS, media, notes, career and link-only match references. Reuses
        reports/visualization/storage; independent of scouting (Phase 10)."""
        return self.services.get("players")

    @property
    def teams(self):
        """Teams platform: club/academy squads (U19/U17…) grouping players, owning team
        info/crest and (later phases) matches, media, charts and notes. Reuses the shared
        engine, ImageStorage and the operational-id scheme; stores data persistently."""
        return self.services.get("teams")

    @property
    def datahub(self):
        """Universal Data Hub (Phase 12): the central import + dataset library.
        Reuses the ImportService engine and the WorkspaceManager dataset store;
        every module consumes datasets it activates via the active-dataset seam."""
        return self.services.get("datahub")

    # -- Phase 11 operations (health / diagnostics / config validation) ----
    def health(self) -> dict:
        """Full health report (database, migrations, storage tiers, cache,
        backup/restore readiness) as a serialisable dict — feeds a /healthz."""
        from fap.ops import run_health_checks
        return run_health_checks(self).to_dict()

    def diagnostics(self) -> dict:
        """Read-only runtime snapshot (backends, schema, counts, redacted config)."""
        from fap.ops import diagnostics
        return diagnostics(self)

    def config_issues(self) -> dict:
        """Environment/config validation summary (production readiness)."""
        from fap.config.validation import summarize
        return summarize(self.settings)


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
    services.register("db", lambda _: Database(settings=settings.database,
                                               production=settings.is_production))
    services.register("templates", lambda reg: TemplateRepository(reg.get("db")))
    services.register("custom_providers", lambda reg: CustomProviderRepository(reg.get("db")))
    services.register("providers", _providers)
    services.register("intelligence", _intelligence)
    services.register("validation", lambda _: ValidationEngine())
    services.register("pipeline", lambda _: DataPipeline())
    services.register("importer", _importer)
    # object store built once and shared by every asset tier (only when s3 is
    # selected; local deployments never import boto3).
    services.register("object_store", lambda _: (
        make_object_store(settings.storage) if settings.storage.backend == "s3" else None))
    services.register("dataset_storage", lambda reg: _dataset_storage(reg, settings))
    services.register("image_storage", lambda reg: _image_storage(reg, settings))
    services.register("themes", lambda _: ThemeManager(
        settings.themes_dir, Path(settings.user_data_dir) / "themes"))
    services.register("workspace_manager",
                      lambda reg: WorkspaceManager(reg.get("db"), cache=reg.get("cache"),
                                                   storage=reg.get("dataset_storage")))
    services.register("reports", _reports_manager)
    services.register("video_storage", lambda reg: _file_storage(reg, settings, "videos"))
    services.register("attachment_storage", lambda reg: _file_storage(reg, settings, "attachments"))
    services.register("permissions", _permissions)
    services.register("administration", lambda reg: _administration(reg, settings))
    services.register("scouting", _scouting)
    services.register("setpieces", _setpieces)
    services.register("players", _players)
    services.register("teams", _teams)
    services.register("datahub", _datahub)

    return PlatformContext(settings=settings, services=services,
                           version=platform_version())


def _image_storage(reg: "ServiceRegistry", settings: "AppSettings"):
    """Image tier: object storage in production (s3), local disk otherwise. Same
    ImageStorage interface either way, so reports/players/scouting never change."""
    if settings.storage.backend == "s3":
        return ObjectImageStorage(reg.get("object_store"), prefix=settings.storage.prefix)
    return LocalImageStorage(Path(settings.user_data_dir) / "images")


def _dataset_storage(reg: "ServiceRegistry", settings: "AppSettings"):
    """Dataset-frame tier: object storage (s3) or local parquet, same interface."""
    if settings.storage.backend == "s3":
        return ObjectDatasetStorage(reg.get("object_store"), prefix=settings.storage.prefix)
    return ParquetDatasetStorage(Path(settings.user_data_dir) / "datasets")


def _file_storage(reg: "ServiceRegistry", settings: "AppSettings", subdir: str):
    """Large-binary tier (videos, attachments, PDFs, thumbnails): object storage
    (s3) or local disk under user_data/<subdir>, same FileStorage interface."""
    if settings.storage.backend == "s3":
        return ObjectFileStorage(reg.get("object_store"), prefix=settings.storage.prefix,
                                 namespace=subdir)
    return LocalFileStorage(Path(settings.user_data_dir) / subdir)


def _scouting(reg: "ServiceRegistry"):
    """The scouting platform, wired to the shared platform services it reuses:
    reports (Studio), image storage, the new video/attachment storage,
    permissions and audit."""
    from fap.scouting.service import ScoutingService
    from fap.workspaces.audit import AuditService
    from fap.workspaces.repositories import AuditRepository
    db = reg.get("db")
    return ScoutingService(
        db, permissions=reg.get("permissions"),
        audit=AuditService(AuditRepository(db)), reports=reg.get("reports"),
        images=reg.get("image_storage"), videos=reg.get("video_storage"),
        attachments=reg.get("attachment_storage"), workspaces=reg.get("workspace_manager"),
        themes=reg.get("themes"))


def _teams(reg: "ServiceRegistry"):
    """The Teams platform (club/academy squads). Reuses the shared relational engine,
    ImageStorage (crest) and audit — no duplicate persistence or media store."""
    from fap.teams.service import TeamService
    from fap.workspaces.audit import AuditService
    from fap.workspaces.repositories import AuditRepository
    db = reg.get("db")
    return TeamService(db, images=reg.get("image_storage"), files=reg.get("video_storage"),
                       audit=AuditService(AuditRepository(db)),
                       workspaces=reg.get("workspace_manager"))


def _players(reg: "ServiceRegistry"):
    """The First Team Players platform (Phase 10), wired to the shared services it
    reuses: permissions, audit, reports (Studio), image storage, the file storage
    tier (documents/videos), workspaces and cache. The scouting service is injected
    read-only for the optional promote-from-scouting bridge. No service duplicated."""
    from fap.players.service import PlayersService
    from fap.workspaces.audit import AuditService
    from fap.workspaces.repositories import AuditRepository
    db = reg.get("db")
    return PlayersService(
        db, permissions=reg.get("permissions"),
        audit=AuditService(AuditRepository(db)), reports=reg.get("reports"),
        images=reg.get("image_storage"), files=reg.get("attachment_storage"),
        workspaces=reg.get("workspace_manager"), scouting=reg.get("scouting"),
        cache=reg.get("cache"))


def _datahub(reg: "ServiceRegistry"):
    """The Universal Data Hub (Phase 12): the central import + dataset-management
    module. Reuses the platform ImportService (the whole import engine) and the
    WorkspaceManager (datasets table, storage, active-dataset seam, presets,
    permissions, audit). It duplicates no engine, repository or storage."""
    from fap.datahub import DataHubService
    return DataHubService(importer=reg.get("importer"),
                          workspaces=reg.get("workspace_manager"),
                          permissions=reg.get("permissions"))


def _setpieces(reg: "ServiceRegistry"):
    """The set-piece platform (Phase 9.0), wired to the shared platform services
    it reuses: permissions, audit, reports (Studio), image/video/attachment
    storage, the workspace manager and the cache. No service is duplicated."""
    from fap.setpieces.service import SetPieceService
    from fap.workspaces.audit import AuditService
    from fap.workspaces.repositories import AuditRepository
    db = reg.get("db")
    return SetPieceService(
        db, permissions=reg.get("permissions"),
        audit=AuditService(AuditRepository(db)), reports=reg.get("reports"),
        images=reg.get("image_storage"), videos=reg.get("video_storage"),
        attachments=reg.get("attachment_storage"), workspaces=reg.get("workspace_manager"),
        cache=reg.get("cache"), themes=reg.get("themes"))


def _permissions(reg: "ServiceRegistry"):
    """Capability-based authorization over the directory tables, with org-tree
    scope inheritance sourced from the existing OrgRepository (no new hierarchy)."""
    from fap.identity.access import PermissionService
    from fap.identity.directory import GrantRepository, RoleRepository, UserDirectoryRepository
    from fap.workspaces.repositories import OrgRepository
    db = reg.get("db")
    org = OrgRepository(db)

    def node_parent(node_id: str) -> "str | None":
        node = org.get(node_id)
        return node.parent_id if node else None

    return PermissionService(RoleRepository(db), UserDirectoryRepository(db),
                             GrantRepository(db), node_parent)


def _administration(reg: "ServiceRegistry", settings: "AppSettings"):
    """Enterprise admin façade. Seeds built-in roles and the first Super Admin
    (from FAP_SUPER_ADMIN or [identity].super_admin) on first resolution."""
    import os
    from fap.identity.administration import AdministrationService
    from fap.identity.email import ConsoleEmailProvider
    from fap.workspaces.audit import AuditService
    from fap.workspaces.repositories import AuditRepository
    db = reg.get("db")
    svc = AdministrationService(
        db, audit=AuditService(AuditRepository(db)), permissions=reg.get("permissions"),
        storage=reg.get("dataset_storage"), images=reg.get("image_storage"),
        cache=reg.get("cache"), email=_email_provider(),
        base_url=os.environ.get("FAP_BASE_URL", ""),
        platform_name=getattr(settings, "app_name", "") or "the platform")
    owner = (os.environ.get("FAP_SUPER_ADMIN")
             or getattr(getattr(settings, "identity", None), "super_admin", "")
             or "").strip()
    if owner:
        svc.ensure_super_admin(owner)
    return svc


def _email_provider():
    """The invitation email transport. Microsoft Graph when app-registration
    secrets are present, else the Console provider (development default)."""
    import os
    tenant = os.environ.get("FAP_GRAPH_TENANT", "")
    client = os.environ.get("FAP_GRAPH_CLIENT_ID", "")
    secret = os.environ.get("FAP_GRAPH_CLIENT_SECRET", "")
    sender = os.environ.get("FAP_GRAPH_SENDER", "")
    if tenant and client and secret and sender:
        from fap.identity.email import GraphEmailProvider
        provider = GraphEmailProvider(tenant, client, secret, sender)
        if provider.available:
            return provider
    from fap.identity.email import ConsoleEmailProvider
    return ConsoleEmailProvider()


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
