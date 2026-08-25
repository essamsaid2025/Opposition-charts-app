"""Central configuration for the Internal xG model project.

Everything that a future maintainer might reasonably want to change lives here:
filesystem paths, the StatsBomb Open Data source URLs, the geometry of the
pitch, and the exact competition/season selection used to build the training
dataset.

IMPORTANT: This is an *internal* xG model. It is trained on actual shot
outcomes (goal / no-goal) from public historical event data. It is NOT Opta,
StatsBomb, or Wyscout xG. See README.md for the full statement of limitations.
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Filesystem layout
# --------------------------------------------------------------------------- #
# Project root = internal-xg/  (this file lives in internal-xg/src/xg/config.py)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = PROJECT_ROOT / "models"
REPORTS_DIR = PROJECT_ROOT / "reports"

# The processed, model-ready shot table. Small (~a few MB) -> safe to commit.
PROCESSED_SHOTS = PROCESSED_DIR / "shots.parquet"
PROCESSED_SHOTS_CSV = PROCESSED_DIR / "shots.csv"

# --------------------------------------------------------------------------- #
# Raw data cache
# --------------------------------------------------------------------------- #
# Raw StatsBomb event JSON is large (several GB for the full selection). We keep
# it OUT of the git repository AND out of any cloud-synced folder (the project
# lives under OneDrive) to avoid multi-GB sync churn. Override with the
# XG_CACHE_DIR environment variable if you want it elsewhere.
DEFAULT_CACHE_DIR = Path(os.environ.get("XG_CACHE_DIR", Path.home() / ".cache" / "statsbomb_open_data"))
CACHE_DIR = DEFAULT_CACHE_DIR

# StatsBomb Open Data is served as raw JSON files from GitHub.
SB_OPEN_DATA_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# --------------------------------------------------------------------------- #
# Pitch geometry  (StatsBomb coordinate system)
# --------------------------------------------------------------------------- #
# StatsBomb pitch is 120 (length) x 80 (width) units. The data is stored so that
# the shooting team always attacks toward x = PITCH_LENGTH; the attacked goal
# centre is therefore fixed at (120, 40) with posts at y = 36 and y = 44.
# (Verified empirically: shot end_location x-values cluster at 120.)
PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0
GOAL_X = 120.0
GOAL_CENTER_Y = 40.0
GOAL_WIDTH = 8.0                      # StatsBomb units (posts at 36 and 44)
GOAL_LEFT_POST_Y = GOAL_CENTER_Y - GOAL_WIDTH / 2.0   # 36.0
GOAL_RIGHT_POST_Y = GOAL_CENTER_Y + GOAL_WIDTH / 2.0  # 44.0

# StatsBomb units are nominally yards; convert to metres for human-readable
# distances. Angles are unit-less so this only affects reported distances.
YARDS_TO_METRES = 0.9144

# --------------------------------------------------------------------------- #
# Competition / season selection for the training dataset
# --------------------------------------------------------------------------- #
# (competition_id, season_id, human label). Chosen for a large, modern, mostly
# homogeneous men's-football sample with good set-piece and tournament variety.
# Reproducible: retraining on a different scope only requires editing this list.
COMPETITION_SELECTION: list[tuple[int, int, str]] = [
    (11, 27, "La Liga 2015/2016"),
    (2, 27, "Premier League 2015/2016"),
    (12, 27, "Serie A 2015/2016"),
    (7, 27, "Ligue 1 2015/2016"),
    (43, 3, "FIFA World Cup 2018"),
    (43, 106, "FIFA World Cup 2022"),
    (55, 43, "UEFA Euro 2020"),
    (55, 282, "UEFA Euro 2024"),
]

# Reproducibility
RANDOM_SEED = 42


def ensure_dirs() -> None:
    """Create the output directories that we own (not the external cache)."""
    for d in (DATA_DIR, PROCESSED_DIR, MODELS_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
