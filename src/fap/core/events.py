"""Tiny synchronous event bus used to decouple layers.

Examples: the ProjectService publishes ``project.saved``; the UI toasts on it;
the cache subscribes to ``data.loaded`` to invalidate derived entries.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    def publish(self, topic: str, payload: dict[str, Any] | None = None) -> None:
        for handler in self._subs.get(topic, []):
            try:
                handler(topic, payload or {})
            except Exception:  # noqa: BLE001 - one bad subscriber must not break others
                logger.exception("Event handler failed for topic %s", topic)
