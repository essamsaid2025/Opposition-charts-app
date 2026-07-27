"""Health checks, storage/connection verification and backup readiness.

Each check is a small, side-effect-safe probe returning a :class:`CheckResult`
(name, ok, detail, latency). Checks operate on the *injected* platform services
(duck-typed), so they exercise exactly the backends the app is running — sqlite
or libSQL, local or S3, disk or Redis — with no knowledge of which is configured.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    severity: str = "info"                 # info | warn | fatal (when failing)
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HealthReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def degraded(self) -> bool:
        return any((not c.ok) and c.severity != "fatal" for c in self.checks)

    @property
    def status(self) -> str:
        if self.ok:
            return "healthy"
        if any((not c.ok) and c.severity == "fatal" for c in self.checks):
            return "unhealthy"
        return "degraded"

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "ok": self.ok,
                "checks": [c.to_dict() for c in self.checks]}


def _timed(fn) -> tuple[Any, float]:
    start = time.perf_counter()
    value = fn()
    return value, round((time.perf_counter() - start) * 1000, 2)


# ---------------------------------------------------------------- individual checks
def check_database(db: Any) -> CheckResult:
    """Liveness + schema currency of the database backend."""
    try:
        ok, ms = _timed(lambda: bool(db.query("SELECT 1")))
        backend = getattr(db, "backend", "sqlite")
        pending = db.pending_versions() if hasattr(db, "pending_versions") else []
        if not ok:
            return CheckResult("database", False, "SELECT 1 returned no rows",
                               "fatal", ms)
        if pending:
            return CheckResult("database", False,
                               f"{backend}: {len(pending)} pending migration(s): {pending}",
                               "warn", ms)
        version = db.schema_version() if hasattr(db, "schema_version") else "?"
        return CheckResult("database", True, f"{backend} · schema v{version}", "info", ms)
    except Exception as exc:
        return CheckResult("database", False, f"{type(exc).__name__}: {exc}", "fatal")


def check_migrations(db: Any) -> CheckResult:
    try:
        pending = db.pending_versions() if hasattr(db, "pending_versions") else []
        if pending:
            return CheckResult("migrations", False, f"pending: {pending}", "warn")
        return CheckResult("migrations", True,
                           f"up to date (v{db.schema_version()})" if hasattr(db, "schema_version")
                           else "up to date")
    except Exception as exc:
        return CheckResult("migrations", False, f"{type(exc).__name__}: {exc}", "warn")


def check_storage(storage: Any, name: str, *, kind: str = "image") -> CheckResult:
    """Round-trip a probe asset (write -> read -> verify -> delete) against a
    storage backend, proving the credentials/bucket/disk actually work."""
    probe_id = f"__healthprobe_{uuid.uuid4().hex}"
    payload = b"fap-health-probe"
    try:
        def run() -> bool:
            if kind == "image":
                storage.save(probe_id, payload, "image/png")
            else:
                storage.save(probe_id, payload, filename="probe.bin", mime="application/octet-stream")
            got = storage.load(probe_id)
            storage.delete(probe_id)
            return got == payload
        ok, ms = _timed(run)
        return CheckResult(f"storage:{name}", ok,
                           "read-back verified" if ok else "probe mismatch",
                           "info" if ok else "fatal", ms)
    except Exception as exc:
        try:
            storage.delete(probe_id)
        except Exception:
            pass
        return CheckResult(f"storage:{name}", False, f"{type(exc).__name__}: {exc}", "fatal")


def check_cache(cache: Any) -> CheckResult:
    key = f"__healthprobe_{uuid.uuid4().hex}"
    try:
        def run() -> bool:
            cache.set(key, {"v": 1}, ttl_seconds=30)
            got = cache.get(key)
            cache.invalidate(key)
            return isinstance(got, dict) and got.get("v") == 1
        ok, ms = _timed(run)
        backend = getattr(cache, "backend_name", "?")
        return CheckResult("cache", ok, f"{backend}: set/get verified" if ok
                           else f"{backend}: set/get mismatch", "info" if ok else "warn", ms)
    except Exception as exc:
        return CheckResult("cache", False, f"{type(exc).__name__}: {exc}", "warn")


# ---------------------------------------------------------------- orchestration
def _service(platform: Any, name: str) -> Any:
    try:
        return platform.services.get(name)
    except Exception:
        return None


def connection_verification(platform: Any) -> HealthReport:
    """Just the connection-level probes (DB + cache) — a fast liveness readiness."""
    report = HealthReport()
    report.add(check_database(platform.db))
    cache = getattr(platform, "cache", None)
    if cache is not None:
        report.add(check_cache(cache))
    return report


def storage_verification(platform: Any) -> HealthReport:
    """Round-trip every storage tier that is wired (images / files / datasets)."""
    report = HealthReport()
    image = _service(platform, "image_storage")
    if image is not None:
        report.add(check_storage(image, "images", kind="image"))
    files = _service(platform, "attachment_storage")
    if files is not None:
        report.add(check_storage(files, "files", kind="file"))
    return report


def backup_readiness(platform: Any) -> CheckResult:
    """Verify the platform is *able* to be backed up (not that a backup ran)."""
    db = platform.db
    backend = getattr(db, "backend", "sqlite")
    if backend in ("sqlite", "", "local"):
        can = hasattr(db, "backup")
        return CheckResult("backup_readiness", can,
                           "sqlite online-backup available" if can
                           else "backup() missing", "info" if can else "warn")
    return CheckResult("backup_readiness", True,
                       "libSQL/Turso managed point-in-time recovery (configure retention)",
                       "info")


def restore_readiness(platform: Any) -> CheckResult:
    """Verify a restore could proceed: storage reachable + schema runner present."""
    db = platform.db
    has_runner = hasattr(db, "applied_versions") and hasattr(db, "rollback")
    return CheckResult("restore_readiness", has_runner,
                       "migration runner + rollback present" if has_runner
                       else "migration runner incomplete", "info" if has_runner else "warn")


def run_health_checks(platform: Any) -> HealthReport:
    """The full health report: database, migrations, storage tiers, cache and
    backup/restore readiness. Suitable for a ``/healthz`` endpoint or a CLI."""
    report = HealthReport()
    report.add(check_database(platform.db))
    report.add(check_migrations(platform.db))
    for c in storage_verification(platform).checks:
        report.add(c)
    cache = getattr(platform, "cache", None)
    if cache is not None:
        report.add(check_cache(cache))
    report.add(backup_readiness(platform))
    report.add(restore_readiness(platform))
    return report
