"""Open Play configuration constants.

Hard-coded vocabularies and defaults migrated out of app.py. Behaviour is
unchanged - these are the exact values the engine has always used.
"""
from __future__ import annotations

from typing import Dict, List

# canonical pitch dimensions (0-100 internal space)
PITCH_LENGTH = 100
PITCH_WIDTH = 68
W = PITCH_WIDTH  # shorthand kept for backward compatibility

# event vocabularies
DEF_EVENTS: List[str] = ["duel", "recovery", "interception", "clearance", "tackle", "block"]
ARROW_EVENTS: List[str] = ["pass", "carry", "cross", "dribble"]
SUCCESS_WORDS: List[str] = ["successful", "success", "complete", "won"]

# required minimal schema
REQUIRED_MINIMUM: List[str] = ["event_type", "x", "y"]

# Open Play <-> platform coordinate-system id mapping
COORD_SYSTEM_IDS: Dict[str, str] = {"0-100": "0-100", "120 x 80": "120x80"}

# column-mapping vocabulary
REQUIRED_CANONICAL: List[str] = ["event_type", "x", "y"]
OPTIONAL_CANONICAL: List[str] = ["x2", "y2"]
CANONICAL_LABELS: Dict[str, str] = {
    "event_type": "Event type", "x": "X (start)", "y": "Y (start)",
    "x2": "X (end)", "y2": "Y (end)"}

# Open Play field names -> platform canonical schema. x2/y2 are the schema's
# legacy aliases for end_x/end_y and are kept in sync by coerce_schema.
APP_TO_PLATFORM: Dict[str, str] = {"event_type": "event_type", "x": "x", "y": "y",
                                   "x2": "end_x", "y2": "end_y"}
PLATFORM_TO_APP: Dict[str, str] = {v: k for k, v in APP_TO_PLATFORM.items()}
