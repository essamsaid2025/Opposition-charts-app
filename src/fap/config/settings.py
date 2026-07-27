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
    backend: str = "disk"                  # "memory" | "disk" | "redis"
    directory: str = "user_data/cache"
    max_entries: int = 256
    ttl_seconds: int = 3600
    # redis (production shared cache). URL wins; else host/port/db/password.
    redis_url: str = ""                    # e.g. rediss://:pw@host:6379/0
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""               # secret -> FAP_CACHE__REDIS_PASSWORD
    key_prefix: str = "fap:"


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    # backend "sqlite" (default, local file) | "libsql" (Turso / embedded replica)
    backend: str = "sqlite"
    path: str = "user_data/fap.sqlite3"
    # libSQL / Turso. ``url`` is the remote (libsql://<db>.turso.io) used either
    # directly or to sync an embedded replica living at ``path``. Secrets come
    # from the environment (FAP_DATABASE__AUTH_TOKEN), never YAML.
    url: str = ""
    auth_token: str = ""                   # secret
    sync_url: str = ""                     # embedded-replica sync target (optional)
    sync_interval_seconds: int = 0         # 0 = sync on open only
    encryption_key: str = ""               # secret (optional at-rest encryption)
    # connection pool: 1 = the classic single serialized connection (default,
    # correct for a local file); >1 = a bounded thread-safe pool (Turso/remote).
    pool_size: int = 1
    busy_timeout_ms: int = 5000
    wal: bool = True                       # WAL journal for the sqlite/local file


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
    json: bool = False                     # structured JSON logs for aggregators
    console: bool = True


@dataclass(frozen=True, slots=True)
class StorageSettings:
    """Where uploaded binary assets live: player/club/team logos, report images,
    generated chart PNGs, PDF assets, documents, video thumbnails, and dataset
    frames. ``local`` (default) keeps the on-disk tiers; ``s3`` moves every tier
    to S3-compatible object storage (AWS S3 / Cloudflare R2 / Backblaze B2 /
    MinIO) behind the SAME storage interfaces — consumers never change."""
    backend: str = "local"                 # "local" | "s3"
    bucket: str = ""
    prefix: str = ""                       # optional key prefix inside the bucket
    endpoint_url: str = ""                 # R2/MinIO/B2 endpoint; empty = AWS
    region: str = "auto"
    access_key_id: str = ""                # secret
    secret_access_key: str = ""            # secret
    use_ssl: bool = True


@dataclass(frozen=True, slots=True)
class DeploymentSettings:
    """Signals that flip production guardrails on. ``base_url`` is used for
    invitation links; ``require_secure_secrets`` makes secret validation fatal."""
    base_url: str = ""
    require_secure_secrets: bool = True
    super_admin: str = ""                  # bootstrap owner email


@dataclass(frozen=True, slots=True)
class AppSettings:
    app_name: str = "First Team Analysis Platform"
    environment: str = "production"        # "development" bypasses login; anything else = production
    default_theme: str = "opta_light"
    themes_dir: str = "assets/themes"
    user_data_dir: str = "user_data"
    cache: CacheSettings = field(default_factory=CacheSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    storage: StorageSettings = field(default_factory=StorageSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    deployment: DeploymentSettings = field(default_factory=DeploymentSettings)

    @property
    def is_production(self) -> bool:
        return (self.environment or "").lower() != "development"


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
