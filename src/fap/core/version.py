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
import importlib
import sys
from pathlib import Path
from typing import MutableMapping

from fap import __version__

_PACKAGE = "fap"
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


# ---------------------------------------------------------------- module freshness
def platform_module_names(modules: MutableMapping[str, object] | None = None) -> list[str]:
    """Every fap module currently imported."""
    modules = sys.modules if modules is None else modules
    return [n for n in list(modules) if n == _PACKAGE or n.startswith(_PACKAGE + ".")]


def platform_is_stale(version: str, modules: MutableMapping[str, object] | None = None) -> bool:
    """Do the imported fap modules predate the platform now on disk?

    Answered from a marker stamped on the package at import time. No marker and
    no package means nothing has been imported yet - nothing to be stale.
    """
    modules = sys.modules if modules is None else modules
    package = modules.get(_PACKAGE)
    if package is None:
        return False
    return getattr(package, "__platform_version__", None) != version


def ensure_fresh_platform(root: Path | None = None) -> str:
    """Guarantee the next ``import fap...`` reads the platform that is on disk.

    A host may re-execute the application script inside a process that still
    holds the *previous* deploy's modules in sys.modules - Streamlit does
    exactly this. The script then imports a name the loaded module does not
    have and dies before a single line of platform code runs, so no cache key
    can save it: ``st.cache_resource`` never gets the chance to be consulted.

    Dropping superseded fap modules makes the interpreter re-read them from
    disk. Call this once, before importing anything else from fap:

        from fap.core.version import ensure_fresh_platform
        ensure_fresh_platform()
        from fap.bootstrap import init_platform     # now guaranteed current

    Safe to call on every rerun: when nothing changed it is one stat per module
    and no imports are touched. It pairs with the versioned service cache -
    fresh modules, then services rebuilt against them, both keyed by the same
    fingerprint.
    """
    version = platform_version(root)
    if platform_is_stale(version):
        for name in platform_module_names():
            del sys.modules[name]          # this module included; our frame keeps it alive
    package = importlib.import_module(_PACKAGE)
    package.__platform_version__ = version  # type: ignore[attr-defined]
    return version
