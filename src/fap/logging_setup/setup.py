"""Central logging bootstrap: console + rotating file. Called once at startup.
Modules simply do ``logger = logging.getLogger(__name__)``."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from fap.config.settings import LoggingSettings

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"


def configure_logging(cfg: LoggingSettings) -> None:
    root = logging.getLogger()
    if getattr(root, "_fap_configured", False):   # idempotent across Streamlit reruns
        return
    root.setLevel(cfg.level.upper())

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(console)

    log_dir = Path(cfg.directory)
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "fap.log", maxBytes=cfg.max_bytes, backupCount=cfg.backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)
    root._fap_configured = True  # type: ignore[attr-defined]
