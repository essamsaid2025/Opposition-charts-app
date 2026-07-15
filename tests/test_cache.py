import pandas as pd

from fap.cache.backends import DiskCache, MemoryCache
from fap.cache.manager import CacheManager, cached, hash_dataframe
from fap.config.settings import CacheSettings


def test_memory_cache_roundtrip() -> None:
    cache = MemoryCache(max_entries=2)
    cache.set("a", 1, ttl_seconds=60)
    assert cache.get("a") == 1
    cache.set("b", 2, ttl_seconds=60)
    cache.set("c", 3, ttl_seconds=60)  # evicts LRU "a"
    assert cache.get("a") is None


def test_dataframe_hash_stable() -> None:
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    assert hash_dataframe(df) == hash_dataframe(df.copy())
    assert hash_dataframe(df) != hash_dataframe(df.assign(x=[9, 9]))


def test_cached_decorator() -> None:
    manager = CacheManager(CacheSettings(backend="memory"))
    calls = {"n": 0}

    @cached(manager, "test")
    def expensive(df: pd.DataFrame, k: int) -> int:
        calls["n"] += 1
        return int(df["x"].sum()) + k

    df = pd.DataFrame({"x": [1, 2, 3]})
    assert expensive(df, 1) == 7
    assert expensive(df, 1) == 7
    assert calls["n"] == 1


def test_disk_cache_handles_namespaced_keys(tmp_path):
    """Keys are namespaced with '::' (ImportService uses "import::<hash>").
    ':' is illegal in Windows filenames, so the key must never be used as a
    filename verbatim - this crashed every import on Windows."""
    cache = DiskCache(tmp_path)
    cache.set("import::abc123", {"rows": 1}, 60)
    assert cache.get("import::abc123") == {"rows": 1}
    cache.delete("import::abc123")
    assert cache.get("import::abc123") is None


def test_disk_cache_keys_cannot_escape_the_directory(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("../../evil", "x", 60)
    assert cache.get("../../evil") == "x"
    assert not (tmp_path.parent.parent / "evil.pkl").exists()
    assert list(tmp_path.glob("*.pkl"))


def test_disk_cache_distinct_keys_do_not_collide(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("import::a", 1, 60)
    cache.set("import::b", 2, 60)
    assert cache.get("import::a") == 1 and cache.get("import::b") == 2
