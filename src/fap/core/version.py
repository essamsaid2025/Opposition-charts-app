"""Identity of the platform implementation currently on disk.

Why this exists
---------------
A host may cache platform services across a code update. Streamlit's
``st.cache_resource`` is the live example: it invalidates a cached value only
when the *decorated function's* body changes, and knows nothing about the
modules that function reaches into. After a deploy the host can therefore
re-import the platform (fresh modules) while still handing out a service built
from the *previous* modules - the service then returns objects of superseded
classes, and the application explodes on a method that "should" exist.

Keying every cached service by ``platform_version()`` removes that failure
mode: change any fap module and the identifier changes, so the host is forced
to rebuild the service against the modules it just loaded. The value is derived
from the platform itself - there is no constant for anyone to forget to bump.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from fap import __version__

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent   # .../src/fap


def source_fingerprint(root: Path | None = None) -> str:
    """Short digest over every platform module: relative path, size and mtime.

    stat() rather than file contents keeps this cheap enough to call on every
    Streamlit rerun (one stat per module, no reads). Any edit moves mtime, and
    a fresh checkout moves it too - erring toward rebuilding a cheap service
    rather than serving a stale one.
    """
    root = Path(root) if root is not None else _PACKAGE_ROOT
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            stat = path.stat()
        except OSError:                      # vanished mid-walk: ignore
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(str(stat.st_size).encode())
        digest.update(str(stat.st_mtime_ns).encode())
    return digest.hexdigest()[:16]


def platform_version(root: Path | None = None) -> str:
    """Cache key for platform services: package version + source fingerprint."""
    return f"{__version__}+{source_fingerprint(root)}"
