# Production Deployment Guide (Phase 11)

The platform runs in two modes, chosen entirely by configuration — **no code
change** between them:

| Tier      | Development (default) | Production                          |
|-----------|-----------------------|-------------------------------------|
| Database  | local SQLite file     | **libSQL / Turso** (`database.backend=libsql`) |
| Storage   | local disk            | **S3-compatible** (`storage.backend=s3`)       |
| Cache     | disk                  | **Redis** (`cache.backend=redis`)              |

Everything else (repositories, services, analytics, reports, visualizations) is
identical. Only `config/settings.local.yaml` + `FAP_*` secrets differ.

## 1. Provision backends
- **Turso**: create a database, copy its `libsql://…` URL and an auth token.
- **Object storage**: create a bucket (AWS S3 / Cloudflare R2 / Backblaze B2 /
  MinIO); create an access key/secret scoped to it.
- **Redis**: any managed Redis (Upstash, Elasticache, …); copy the connection URL.

## 2. Install production extras
```bash
pip install -r requirements.txt
pip install ".[production]"      # libsql-experimental + boto3 + redis
```

## 3. Configure (non-secrets in YAML, secrets in env)
- Copy `config/production.example.yaml` → `config/settings.local.yaml`.
- Copy `.env.example` → `.env` (or load into your secret manager) and fill the
  `SECRET`-marked values.

## 4. Validate before boot
```bash
python scripts/health_check.py --config     # exits non-zero on any FATAL issue
python scripts/manage_db.py status          # schema version + pending migrations
python scripts/health_check.py              # full health: db, storage, cache, backups
```

## 5. Run
```bash
streamlit run app.py
```
Migrations apply automatically on first DB open; `scripts/manage_db.py migrate`
can pre-apply them in a release step.

## Reliability
- **Health/readiness probe**: `python scripts/health_check.py --json` (exit 0 =
  healthy). Wire into a container `HEALTHCHECK` or k8s readiness probe.
- **Backups**: SQLite uses `python scripts/manage_db.py backup <path>` (online
  backup API). **libSQL/Turso uses managed point-in-time recovery** — enable PITR
  and set your retention window in the Turso dashboard. Object storage: enable
  bucket versioning + a lifecycle policy. Redis is a cache only (safe to lose).
- **Restore**: SQLite — restore the backup file and reopen. Turso — restore to a
  timestamp via PITR. Object storage — restore prior object versions. The
  migration runner (`Database.rollback`) can step the schema back where reverse
  migrations are registered.

## Deployment checklist
- [ ] `environment: production`
- [ ] `database.backend: libsql` with `url` set and `FAP_DATABASE__AUTH_TOKEN` present
- [ ] `storage.backend: s3` with `bucket` + `FAP_STORAGE__ACCESS_KEY_ID/SECRET_ACCESS_KEY`
- [ ] `cache.backend: redis` with `FAP_CACHE__REDIS_URL`
- [ ] `FAP_SUPER_ADMIN` set (bootstrap owner)
- [ ] `auth.enabled: true`
- [ ] `logging.json: true` and logs shipped to the aggregator
- [ ] `pip install ".[production]"` completed
- [ ] `scripts/health_check.py --config` → **production_ready: true**
- [ ] `scripts/health_check.py` → **STATUS: HEALTHY** (db + all storage tiers + cache)
- [ ] Turso PITR enabled; bucket versioning + lifecycle enabled
- [ ] No secrets committed to the repo (all via `FAP_*` env / secret manager)
- [ ] Smoke test: upload a player photo + a report image, redeploy, confirm both persist
