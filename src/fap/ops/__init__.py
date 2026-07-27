"""Operational tooling (Phase 11.4/11.5): health checks, storage/connection
verification, backup & restore readiness, and a diagnostics snapshot. Pure
library code over the injected platform services — no UI, no football logic."""
from fap.ops.health import (
    CheckResult, HealthReport, backup_readiness, check_cache, check_database,
    check_migrations, check_storage, connection_verification, restore_readiness,
    run_health_checks, storage_verification,
)
from fap.ops.diagnostics import diagnostics

__all__ = [
    "CheckResult", "HealthReport", "run_health_checks", "check_database",
    "check_storage", "check_cache", "check_migrations", "storage_verification",
    "connection_verification", "backup_readiness", "restore_readiness",
    "diagnostics",
]
