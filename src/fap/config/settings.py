"""Layered configuration.

Precedence (lowest -> highest):
    1. built-in dataclass defaults
    2. config/defaults.yaml           (shipped with the app)
    3. config/settings.local.yaml     (per-deployment overrides, gitignored)
    4. environment variables FAP_*    (containers / CI)

Settings are frozen after load: components receive them via injection, never
mutate them, and never read YAML themselves.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml

from fap.core.exceptions import ConfigurationError

_ENV_PREFIX = "FAP_"


@dataclass(frozen=True, slots=True)
class CacheSettings:
    backend: str = "disk"                  # "memory" | "disk"
    directory: str = "user_data/cache"
    max_entries: int = 256
    ttl_seconds: int = 3600


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    path: str = "user_data/fap.sqlite3"


@dataclass(frozen=True, slots=True)
class AuthSettings:
    enabled: bool = True
    provider: str = "local"                # id of an Authenticator plugin
    session_ttl_minutes: int = 480


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str = "INFO"
    directory: str = "user_data/logs"
    max_bytes: int = 2_000_000
    backup_count: int = 5


@dataclass(frozen=True, slots=True)
class AppSettings:
    app_name: str = "First Team Analysis Platform"
    environment: str = "production"        # "development" bypasses login; anything else = production
    default_theme: str = "opta_light"
    themes_dir: str = "assets/themes"
    user_data_dir: str = "user_data"
    cache: CacheSettings = field(default_factory=CacheSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)


def _merge_section(obj: Any, data: dict[str, Any]) -> Any:
    """Overlay a dict onto a (possibly nested) frozen dataclass."""
    updates: dict[str, Any] = {}
    for f in fields(obj):
        if f.name not in data:
            continue
        current = getattr(obj, f.name)
        incoming = data[f.name]
        if hasattr(current, "__dataclass_fields__") and isinstance(incoming, dict):
            updates[f.name] = _merge_section(current, incoming)
        else:
            updates[f.name] = incoming
    return replace(obj, **updates)


def _apply_env(settings: AppSettings) -> AppSettings:
    """FAP_DATABASE__PATH=/x/y  ->  settings.database.path. Double underscore
    separates nesting levels."""
    result = settings
    for key, value in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        path = key[len(_ENV_PREFIX):].lower().split("__")
        overlay: dict[str, Any] = {path[-1]: _coerce(value)}
        for part in reversed(path[:-1]):
            overlay = {part: overlay}
        result = _merge_section(result, overlay)
    return result


def _coerce(raw: str) -> Any:
    low = raw.lower()
    if low in {"true", "false"}:
        return low == "true"
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            continue
    return raw


def load_settings(root: Path | None = None) -> AppSettings:
    root = root or Path.cwd()
    settings = AppSettings()
    for candidate in ("config/defaults.yaml", "config/settings.local.yaml"):
        file = root / candidate
        if not file.exists():
            continue
        try:
            data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigurationError(f"Invalid YAML in {file}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigurationError(f"{file} must contain a mapping")
        settings = _merge_section(settings, data)
    return _apply_env(settings)
