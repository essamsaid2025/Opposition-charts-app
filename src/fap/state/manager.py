"""State management.

A thin, typed, namespaced facade over the UI framework's session state.
Rules the codebase follows:

* Nobody touches ``st.session_state`` directly - only through StateManager.
* Keys are declared as StateKey constants (see fap.state.keys) so there is a
  single greppable inventory of all session state.
* The manager falls back to a plain dict when Streamlit is absent, so every
  service and test runs headlessly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, MutableMapping, TypeVar

try:  # UI-framework dependency is optional at import time
    import streamlit as st
    _HAS_ST = True
except Exception:  # pragma: no cover
    _HAS_ST = False

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class StateKey(Generic[T]):
    namespace: str
    name: str
    default: T | None = None

    @property
    def full(self) -> str:
        return f"{self.namespace}::{self.name}"


class StateManager:
    def __init__(self, backend: MutableMapping[str, Any] | None = None) -> None:
        if backend is not None:
            self._store: MutableMapping[str, Any] = backend
        elif _HAS_ST:
            self._store = st.session_state  # type: ignore[assignment]
        else:
            self._store = {}

    def get(self, key: StateKey[T]) -> T | None:
        return self._store.get(key.full, key.default)

    def set(self, key: StateKey[T], value: T) -> None:
        self._store[key.full] = value

    def setdefault(self, key: StateKey[T], value: T) -> T:
        return self._store.setdefault(key.full, value)  # type: ignore[return-value]

    def delete(self, key: StateKey[Any]) -> None:
        self._store.pop(key.full, None)

    def clear_namespace(self, namespace: str) -> None:
        prefix = f"{namespace}::"
        for existing in [k for k in list(self._store) if str(k).startswith(prefix)]:
            self._store.pop(existing, None)
