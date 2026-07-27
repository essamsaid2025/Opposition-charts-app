"""Environment & configuration validation (Phase 11.5).

Turns silent misconfiguration into an explicit, actionable list of issues at
boot. ``validate_settings`` never raises (so tools can render every issue);
``require_production_ready`` raises on any *fatal* issue so a bad production
deploy fails fast instead of losing data at first write.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fap.config.settings import AppSettings
from fap.core.exceptions import ConfigurationError

FATAL, WARN, INFO = "fatal", "warn", "info"


@dataclass(slots=True)
class Issue:
    level: str
    field: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.field}: {self.message}"


def validate_settings(settings: AppSettings) -> list[Issue]:
    """Collect configuration issues. In production, ephemeral persistence and
    missing secrets are fatal; in development they are informational."""
    issues: list[Issue] = []
    prod = settings.is_production
    lvl = FATAL if prod else WARN

    db = settings.database
    if db.backend in ("libsql", "turso"):
        if not (db.url or db.sync_url):
            issues.append(Issue(FATAL, "database.url",
                                 "libSQL backend needs a Turso database url."))
        if not db.auth_token:
            issues.append(Issue(lvl, "database.auth_token",
                                 "libSQL backend needs an auth token (set FAP_DATABASE__AUTH_TOKEN)."))
    elif prod:
        issues.append(Issue(WARN, "database.backend",
                            "sqlite on a stateless host is EPHEMERAL — data is lost on redeploy. "
                            "Set database.backend='libsql' with a Turso url + token."))

    st = settings.storage
    if st.backend == "s3":
        if not st.bucket:
            issues.append(Issue(FATAL, "storage.bucket", "s3 backend needs a bucket."))
        if not (st.access_key_id and st.secret_access_key):
            issues.append(Issue(lvl, "storage.credentials",
                                 "s3 backend needs access_key_id + secret_access_key "
                                 "(set via FAP_STORAGE__* env)."))
    elif prod:
        issues.append(Issue(WARN, "storage.backend",
                            "local storage on a stateless host is EPHEMERAL — uploaded assets "
                            "are lost on redeploy. Set storage.backend='s3'."))

    if settings.cache.backend == "redis" and not (settings.cache.redis_url
                                                  or settings.cache.redis_host):
        issues.append(Issue(WARN, "cache.redis", "redis backend needs a url or host."))

    if prod and not settings.auth.enabled:
        issues.append(Issue(FATAL, "auth.enabled",
                            "authentication is disabled in a production environment."))

    if prod and not (settings.deployment.super_admin):
        issues.append(Issue(WARN, "deployment.super_admin",
                            "no bootstrap super admin configured (FAP_SUPER_ADMIN)."))

    return issues


def fatal_issues(settings: AppSettings) -> list[Issue]:
    return [i for i in validate_settings(settings) if i.level == FATAL]


def require_production_ready(settings: AppSettings) -> None:
    """Raise if any fatal configuration issue would make production unsafe."""
    fatal = fatal_issues(settings)
    if fatal:
        raise ConfigurationError(
            "Configuration is not production-ready:\n  " + "\n  ".join(str(i) for i in fatal))


def summarize(settings: AppSettings) -> dict[str, Any]:
    issues = validate_settings(settings)
    return {
        "production_ready": not any(i.level == FATAL for i in issues),
        "fatal": [str(i) for i in issues if i.level == FATAL],
        "warnings": [str(i) for i in issues if i.level == WARN],
        "info": [str(i) for i in issues if i.level == INFO],
    }
