"""Single inventory of all session-state keys. Add new keys here only."""
from __future__ import annotations

from typing import Any

from fap.state.manager import StateKey

# auth
CURRENT_USER: StateKey[dict[str, Any]] = StateKey("auth", "current_user")

# workspace / project context
ACTIVE_WORKSPACE_ID: StateKey[str] = StateKey("workspace", "active_id")
ACTIVE_PROJECT_ID: StateKey[str] = StateKey("project", "active_id")

# data
DATASET_TOKEN: StateKey[str] = StateKey("data", "dataset_token")     # cache key of loaded data
ACTIVE_FILTERS: StateKey[dict[str, Any]] = StateKey("data", "filters", default=None)

# ui
ACTIVE_THEME_ID: StateKey[str] = StateKey("ui", "theme_id")
ACTIVE_VISUAL_ID: StateKey[str] = StateKey("ui", "visual_id")
VISUAL_CONTROL_VALUES: StateKey[dict[str, Any]] = StateKey("ui", "control_values")
