# Phase 11 — Production Persistence & Infrastructure

Infrastructure only. No football features, no UI redesign, no analytics/report/
visualization engine changes. The whole phase is **additive backends selected by
configuration**, plugged in at the single composition root (`fap.bootstrap`).

## What changed and why it is safe
The persistence stack was already built on clean seams: `Database` exposes only
`execute`/`query` (the repository interface), storage is three ABCs, cache is a
strategy behind `CacheManager`, and backends are constructed only in
`bootstrap.py`. Phase 11 fills those seams with production backends without
touching a repository or service.

- **11.1 Database** — `fap.db.connection` provides a backend factory (`sqlite`
  default, `libsql`/Turso import-guarded) and a generic, thread-safe
  `ConnectionPool`. `Database` gained `settings=`/`production=` construction, a
  pool path (`pool_size>1`), atomic per-migration application, `rollback()`,
  `schema_version()/applied/pending`, `ping()` and sqlite online `backup()`.
  `execute`/`query` keep their exact contract; the default local path is
  byte-compatible.
- **11.2 Object storage** — `fap.storage.objectstore` implements the existing
  `ImageStorage`/`FileStorage`/`DatasetStorage` ABCs over an S3-compatible store
  (`boto3`, guarded). Every asset tier (logos, report images, chart PNGs, PDFs,
  documents, video thumbnails, dataset frames) moves to object storage by config;
  consumers are untouched. A `MemoryObjectStore` makes the adapters testable.
- **11.3 Cache** — `RedisCache` added behind the existing `CacheBackend`
  interface; `CacheManager` selects it via config. Reports/previews/charts/
  queries already flow through this cache and the renderer byte-cache.
- **11.4 Reliability** — `fap.ops` adds health checks, storage/connection
  verification, backup/restore readiness and a redacted diagnostics snapshot,
  exposed on `PlatformContext` (`.health()`, `.diagnostics()`, `.config_issues()`).
- **11.5 Deployment** — `fap.config.validation` enforces production invariants
  (and flags the sqlite/local "ephemeral on a stateless host" data-loss risk);
  structured JSON logging; `scripts/manage_db.py` + `scripts/health_check.py`;
  `.env.example`, `config/production.example.yaml`, `docs/DEPLOYMENT.md`;
  optional `[production]` extras in `pyproject.toml`.

## Not runtime-verified here
`libsql-experimental`, `boto3` and `redis` are not installed in the sandbox, so
those backends are implemented + import-guarded + unit-tested via in-process
substitutes (`MemoryObjectStore`, the pool exercised on sqlite), the same
"implemented, guarded, degrade" pattern used for DOCX/PPTX export and Graph email.
Verify them in staging with `scripts/health_check.py`.
