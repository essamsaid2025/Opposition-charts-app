"""Phase 11 - Production Persistence & Infrastructure.

Infrastructure only: verifies the backend abstractions (libSQL-ready database,
S3-ready object storage, Redis-ready cache), connection pooling, migration
rollback, health/diagnostics and config validation - while proving the DEFAULT
sqlite/local/disk stack and the repository contract are unchanged.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
import pytest

from dataclasses import replace

from fap.config.settings import AppSettings, CacheSettings, DatabaseSettings, StorageSettings
from fap.core.exceptions import ConfigurationError
from fap.db.engine import Database, MIGRATIONS
from fap.db.connection import ConnectionPool, split_statements
from fap.db.models import Workspace
from fap.db.repositories import WorkspaceRepository
from fap.storage import (MemoryObjectStore, ObjectDatasetStorage, ObjectFileStorage,
                         ObjectImageStorage, make_object_store)


# ---------------------------------------------------------------- 11.1 database
def test_default_backend_is_sqlite_and_contract_unchanged(tmp_path):
    db = Database(tmp_path / "d.sqlite3")            # positional path (back-compat)
    try:
        assert db.backend == "sqlite"
        assert db.schema_version() == MIGRATIONS[-1][0]
        assert db.pending_versions() == []
        assert db.ping() is True
        repo = WorkspaceRepository(db)
        repo.save(Workspace(id="w1", name="Alpha", owner_id="o", document={"x": 1}))
        got = repo.get("w1")
        assert got.name == "Alpha" and got.document == {"x": 1}
    finally:
        db.close()


def test_sqlite_online_backup(tmp_path):
    db = Database(tmp_path / "src.sqlite3")
    WorkspaceRepository(db).save(Workspace(id="w1", name="Beta", owner_id="", document={}))
    dest = db.backup(tmp_path / "backup.sqlite3")
    db.close()
    restored = Database(dest)
    try:
        rows = restored.query("SELECT name FROM workspaces WHERE id='w1'")
        assert rows[0]["name"] == "Beta"
    finally:
        restored.close()


def test_rollback_refuses_without_down_migration(tmp_path):
    db = Database(tmp_path / "d.sqlite3")
    try:
        with pytest.raises(Exception) as exc:
            db.rollback(MIGRATIONS[-1][0] - 1)
        assert "no down migration" in str(exc.value).lower()
    finally:
        db.close()


def test_connection_pool_concurrent(tmp_path):
    db = Database(settings=DatabaseSettings(path=str(tmp_path / "p.sqlite3"), pool_size=4))
    try:
        assert db.pending_versions() == []
        errors = []

        def worker(i):
            try:
                WorkspaceRepository(db).save(
                    Workspace(id=f"w{i}", name=f"n{i}", owner_id="", document={}))
            except Exception as ex:  # pragma: no cover
                errors.append(repr(ex))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert not errors
        assert db.query("SELECT COUNT(*) AS n FROM workspaces")[0]["n"] == 12
    finally:
        db.close()


def test_connection_pool_primitive():
    import sqlite3
    pool = ConnectionPool(lambda: sqlite3.connect(":memory:"), size=3)
    try:
        with pool.acquire() as conn:
            conn.execute("CREATE TABLE t(x)")
            conn.execute("INSERT INTO t VALUES (7)")
            assert list(conn.execute("SELECT x FROM t"))[0][0] == 7
        assert pool.size() == 3
    finally:
        pool.close()


def test_split_statements_on_real_migration():
    # migration 5 has many statements + SQL comments; splitting must not choke
    stmts = split_statements(MIGRATIONS[4][1])
    assert len(stmts) >= 3
    assert all(";" not in s for s in stmts)


# ---------------------------------------------------------------- 11.2 storage
def test_object_image_storage_roundtrip():
    img = ObjectImageStorage(MemoryObjectStore(), prefix="p")
    img.save("i1", b"PNG", "image/png")
    assert img.load("i1") == b"PNG"
    assert img.mime("i1") == "image/png"
    assert img.exists("i1")
    img.delete("i1")
    assert not img.exists("i1")
    with pytest.raises(ValueError):
        img.save("bad", b"x", "application/x-msdownload")


def test_object_file_storage_roundtrip():
    fs = ObjectFileStorage(MemoryObjectStore(), prefix="p", namespace="videos")
    fs.save("f1", b"VIDEO", filename="c.mp4", mime="video/mp4")
    assert fs.load("f1") == b"VIDEO"
    assert fs.mime("f1") == "video/mp4"
    assert fs.size_bytes("f1") == 5


def test_object_dataset_storage_roundtrip():
    ds = ObjectDatasetStorage(MemoryObjectStore(), prefix="p")
    frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    ds.save("d1", frame)
    assert ds.exists("d1") and ds.size_bytes("d1") > 0
    assert ds.load("d1").equals(frame)
    ds.delete("d1")
    assert not ds.exists("d1")


def test_s3_requires_bucket_before_boto3():
    with pytest.raises(ConfigurationError):
        make_object_store(StorageSettings(backend="s3", bucket=""))


# ---------------------------------------------------------------- 11.3 cache
def test_cache_manager_backends():
    from fap.cache import CacheManager
    cm = CacheManager(CacheSettings(backend="memory"))
    cm.set("k", {"v": 1})
    assert cm.get("k") == {"v": 1}
    assert cm.backend_name == "memory"


# ---------------------------------------------------------------- 11.4 reliability
def _platform(tmp_path, **over):
    from fap.bootstrap import init_platform
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"),
                       storage=StorageSettings(backend="local"), **over)
    return init_platform(settings=settings)


def test_health_checks_healthy(tmp_path):
    platform = _platform(tmp_path)
    try:
        report = platform.health()
        assert report["status"] == "healthy"
        names = {c["name"] for c in report["checks"]}
        assert "database" in names and "cache" in names
        assert any(n.startswith("storage:") for n in names)
    finally:
        platform.db.close()


def test_diagnostics_redacts_secrets(tmp_path):
    import json
    platform = _platform(tmp_path, database=DatabaseSettings(
        path=str(tmp_path / "ud" / "fap.sqlite3"), auth_token="SUPERSECRET"))
    try:
        diag = platform.diagnostics()
        assert "SUPERSECRET" not in json.dumps(diag)
        assert diag["config"]["database"]["auth_token"] == "***set***"
        assert diag["backends"]["database"] == "sqlite"
    finally:
        platform.db.close()


# ---------------------------------------------------------------- 11.5 deployment
def test_config_validation_dev_vs_prod():
    from fap.config.validation import validate_settings, require_production_ready, fatal_issues
    assert not any(i.level == "fatal" for i in validate_settings(AppSettings(environment="development")))
    prod = validate_settings(AppSettings(environment="production"))
    assert any("EPHEMERAL" in i.message for i in prod)          # sqlite/local warning
    bad = AppSettings(environment="production",
                      database=DatabaseSettings(backend="libsql", url="", auth_token=""))
    assert fatal_issues(bad)
    with pytest.raises(ConfigurationError):
        require_production_ready(bad)
