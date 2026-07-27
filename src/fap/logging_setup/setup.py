"""Central logging bootstrap: console + rotating file. Called once at startup.
Modules simply do ``logger = logging.getLogger(__name__)``.

Phase 11.5: an optional structured JSON formatter (``logging.json: true``) makes
logs ingestible by aggregators (CloudWatch / Loki / Datadog); the console handler
can be turned off for containers that only want file/JSON output. Defaults are
unchanged (human console + rotating file)."""
from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from fap.config.settings import LoggingSettings

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"


class _JsonFormatter(logging.Formatter):
    """One JSON object per line — timestamp, level, logger, message, plus
    exception text when present. No secrets are logged by the platform."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(cfg: LoggingSettings) -> None:
    root = logging.getLogger()
    if getattr(root, "_fap_configured", False):   # idempotent across Streamlit reruns
        return
    root.setLevel(cfg.level.upper())
    formatter: logging.Formatter = _JsonFormatter() if getattr(cfg, "json", False) \
        else logging.Formatter(_FORMAT)

    if getattr(cfg, "console", True):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    log_dir = Path(cfg.directory)
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "fap.log", maxBytes=cfg.max_bytes, backupCount=cfg.backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root._fap_configured = True  # type: ignore[attr-defined]
