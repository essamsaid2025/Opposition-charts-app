"""A production diagnostics snapshot: which backends are live, what version is
running, config with secrets redacted, and light row counts. Read-only; safe to
log or expose to an admin. No secret value is ever included."""
from __future__ import annotations

from typing import Any

_SECRET_HINTS = ("token", "secret", "password", "key")


def _is_secret(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in _SECRET_HINTS) and "key_prefix" not in n and "public" not in n


def redact(value: Any, name: str = "") -> Any:
    """Mask secret-looking scalars; recurse dicts. A set secret becomes
    ``"***set***"`` so operators can confirm presence without exposure."""
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if _is_secret(name):
        return "***set***" if value else ""
    return value


def _settings_dict(settings: Any) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass
    if is_dataclass(settings):
        return redact(asdict(settings))
    return {}


def _row_count(db: Any, table: str) -> int | None:
    try:
        rows = db.query(f"SELECT COUNT(*) AS n FROM {table}")
        return int(rows[0]["n"]) if rows else 0
    except Exception:
        return None


def diagnostics(platform: Any) -> dict[str, Any]:
    """A structured snapshot of the running platform."""
    settings = getattr(platform, "settings", None)
    db = getattr(platform, "db", None)
    cache = getattr(platform, "cache", None)

    backends = {
        "database": getattr(db, "backend", "sqlite") if db is not None else None,
        "cache": getattr(cache, "backend_name", None) if cache is not None else None,
        "storage": getattr(getattr(settings, "storage", None), "backend", None),
    }
    schema = {
        "version": db.schema_version() if hasattr(db, "schema_version") else None,
        "applied": db.applied_versions() if hasattr(db, "applied_versions") else None,
        "pending": db.pending_versions() if hasattr(db, "pending_versions") else None,
    } if db is not None else {}

    counts = {}
    if db is not None:
        for table in ("users", "workspaces", "projects", "datasets", "reports"):
            n = _row_count(db, table)
            if n is not None:
                counts[table] = n

    return {
        "version": getattr(platform, "version", None),
        "environment": getattr(settings, "environment", None),
        "is_production": getattr(settings, "is_production", None),
        "backends": backends,
        "schema": schema,
        "row_counts": counts,
        "config": _settings_dict(settings),
    }
