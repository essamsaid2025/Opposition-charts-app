"""Composition root. The single place where concrete implementations are
constructed and wired (Dependency Injection by hand). Everything downstream
receives its collaborators through AppContext - no globals, no hidden imports."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fap.auth.base import Authenticator, auth_registry
from fap.cache import CacheManager
from fap.config import AppSettings, load_settings
from fap.core.events import EventBus
from fap.core.plugin import PluginRegistry
from fap.db import Database
from fap.db.repositories import ProjectRepository, WorkspaceRepository
from fap.exports.base import Exporter, export_registry, load_builtin_exporters
from fap.logging_setup import configure_logging
from fap.metrics.base import Metric, metric_registry, load_builtin_metrics
from fap.pipeline import DataPipeline
from fap.projects import ProjectService
from fap.providers.base import DataProvider, provider_registry, load_builtin_providers
from fap.state import StateManager
from fap.themes import ThemeManager
from fap.visuals.base import Visualization, visual_registry, load_builtin_visuals
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
    visuals: PluginRegistry[Visualization]
    metrics: PluginRegistry[Metric]
    providers: PluginRegistry[DataProvider]
    exporters: PluginRegistry[Exporter]


def init_app(root: Path | None = None) -> AppContext:
    settings = load_settings(root)
    configure_logging(settings.logging)

    # plugin discovery (idempotent - registries dedupe by class identity)
    load_builtin_providers()
    load_builtin_metrics()
    load_builtin_visuals()
    load_builtin_exporters()

    events = EventBus()
    db = Database(settings.database.path)
    themes = ThemeManager(settings.themes_dir, Path(settings.user_data_dir) / "themes")
    cache = CacheManager(settings.cache)

    authenticator = auth_registry.get(settings.auth.provider)(db)  # type: ignore[call-arg]
    projects = ProjectService(ProjectRepository(db), events)
    workspaces = WorkspaceService(WorkspaceRepository(db), events)

    return AppContext(
        settings=settings, state=StateManager(), events=events, cache=cache, db=db,
        themes=themes, pipeline=DataPipeline(), authenticator=authenticator,
        projects=projects, workspaces=workspaces,
        visuals=visual_registry, metrics=metric_registry,
        providers=provider_registry, exporters=export_registry,
    )
