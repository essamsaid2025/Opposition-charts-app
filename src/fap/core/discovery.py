"""Auto-discovery: importing every module inside a package triggers the
``@registry.register`` decorators inside it. This is what makes 'drop a file
in the folder' equal 'plugin installed'."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

logger = logging.getLogger(__name__)


def discover_plugins(package: ModuleType, *, fail_hard: bool = False) -> list[str]:
    """Import all submodules of *package* (recursively). Returns imported names.

    A broken third-party plugin must not take down the app, so failures are
    logged and skipped unless ``fail_hard`` is set (useful in CI).
    """
    imported: list[str] = []
    prefix = package.__name__ + "."
    for mod in pkgutil.walk_packages(package.__path__, prefix):
        try:
            importlib.import_module(mod.name)
            imported.append(mod.name)
        except Exception:  # noqa: BLE001 - isolation of faulty plugins is the point
            logger.exception("Failed to load plugin module %s", mod.name)
            if fail_hard:
                raise
    return imported
