"""Set Piece analysis primitives - PURE functions (no Streamlit, no matplotlib,
no DB). Phase 9.0 ships the foundation the later phases build on:

  * a provider-agnostic import normalizer (CSV / Excel / JSON -> canonical rows),
  * controlled-vocabulary canonicalizers (so "In-swinger", "inswing", "IN" all
    normalize to one token), and
  * box-occupancy zone geometry (canonical 0-100 pitch) used to auto-label a
    tagged position by its coordinates.

The heavy analytics (occupancy density, contact %, clustering, tendencies) arrive
in 9.1-9.3 and will import these helpers rather than re-derive them.
"""
from __future__ import annotations

import io
import json
from typing import Any

import pandas as pd

from fap.setpieces.models import (
    DELIVERY_HEIGHTS, DELIVERY_LENGTHS, DELIVERY_SPEEDS, DELIVERY_TYPES, PHASES,
    PERSPECTIVES, SET_PIECE_TYPES, SIDES,
)

# --------------------------------------------------------------- vocab mapping
_TYPE_ALIASES = {
    "corner": "corner", "corners": "corner", "ck": "corner", "corner_kick": "corner",
    "free_kick": "free_kick", "freekick": "free_kick", "fk": "free_kick",
    "free kick": "free_kick", "direct_free_kick": "free_kick", "indirect_free_kick": "free_kick",
    "throw_in": "throw_in", "throwin": "throw_in", "throw": "throw_in", "throw in": "throw_in",
    "long_throw": "throw_in", "penalty": "penalty", "pen": "penalty", "penalties": "penalty",
    "kick_off": "kick_off", "kickoff": "kick_off", "ko": "kick_off", "kick off": "kick_off",
}
_DELIVERY_ALIASES = {
    # keys are already in _norm_token form (lower-cased, spaces/hyphens -> "_")
    "in": "inswing", "inswing": "inswing", "inswinger": "inswing", "in_swinger": "inswing",
    "out": "outswing", "outswing": "outswing", "outswinger": "outswing", "out_swinger": "outswing",
    "straight": "straight", "driven": "driven", "drive": "driven", "lofted": "lofted",
    "loft": "lofted", "ground": "ground", "short": "short", "long": "long",
}
_PHASE_ALIASES = {
    "offensive": "offensive", "offence": "offensive", "offense": "offensive",
    "attacking": "offensive", "attack": "offensive", "for": "offensive",
    "defensive": "defensive", "defence": "defensive", "defense": "defensive",
    "defending": "defensive", "against": "defensive",
}
_PERSPECTIVE_ALIASES = {
    "own": "own", "own_team": "own", "us": "own", "team": "own", "self": "own",
    "opposition": "opposition", "opponent": "opposition", "opp": "opposition",
    "against": "opposition", "them": "opposition",
}


def _norm_token(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_") if value is not None else ""


def canonical_type(value: Any) -> str:
    t = _TYPE_ALIASES.get(_norm_token(value), _norm_token(value))
    return t if t in SET_PIECE_TYPES else "corner"


def canonical_phase(value: Any) -> str:
    p = _PHASE_ALIASES.get(_norm_token(value), _norm_token(value))
    return p if p in PHASES else "offensive"


def canonical_perspective(value: Any) -> str:
    p = _PERSPECTIVE_ALIASES.get(_norm_token(value), _norm_token(value))
    return p if p in PERSPECTIVES else "own"


def canonical_delivery(value: Any) -> str:
    d = _DELIVERY_ALIASES.get(_norm_token(value), _norm_token(value))
    return d if d in DELIVERY_TYPES else ""


def canonical_side(value: Any) -> str:
    s = _norm_token(value)
    if s in ("l", "left"):
        return "left"
    if s in ("r", "right"):
        return "right"
    if s in ("c", "central", "center", "centre", "middle"):
        return "central"
    return s if s in SIDES else ""


# ----------------------------------------------------------- box-zone geometry
# Canonical 0-100 attacking pitch: goal line at x=100, goal centred at y=50.
# Rectangles are (x0, y0, x1, y1). Order matters: first match wins (specific ->
# general), so the tightest zone (gk area) is checked before wider ones.
ZONE_RECTS: tuple[tuple[str, float, float, float, float], ...] = (
    ("gk_area",          94.2, 42.0, 100.0, 58.0),
    ("six_yard",         94.2, 36.8, 100.0, 63.2),
    ("penalty_spot",     85.0, 40.0,  92.0, 60.0),
    ("half_space_left",  83.0,  0.0, 100.0, 36.8),
    ("half_space_right", 83.0, 63.2, 100.0, 100.0),
    ("central",          83.0, 36.8,  94.2, 63.2),
    ("edge_box",         74.0,  0.0,  83.0, 100.0),
)

# Penalty area bounds (canonical) - used for players_in_box helpers later.
PENALTY_AREA = (83.0, 21.1, 100.0, 78.9)


def in_rect(x: float | None, y: float | None, rect: tuple[float, float, float, float]) -> bool:
    if x is None or y is None:
        return False
    x0, y0, x1, y1 = rect
    return x0 <= float(x) <= x1 and y0 <= float(y) <= y1


def zone_for(x: float | None, y: float | None) -> str:
    """Coarse occupancy zone for a coordinate (auto-label when a tagger gives a
    position but not an explicit role). Empty string if outside the tracked area."""
    for name, x0, y0, x1, y1 in ZONE_RECTS:
        if in_rect(x, y, (x0, y0, x1, y1)):
            return name
    return ""


def in_penalty_area(x: float | None, y: float | None) -> bool:
    return in_rect(x, y, PENALTY_AREA)


# --------------------------------------------------------------- file readers
def read_table(data: bytes, filename: str) -> pd.DataFrame:
    """Provider-agnostic reader: CSV, Excel (xls/xlsx) or JSON bytes -> DataFrame.
    JSON accepts either a list of records or an object with a top-level list."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls", ".xlsm")):
        return pd.read_excel(io.BytesIO(data))
    if name.endswith(".json"):
        payload = json.loads(data.decode("utf-8"))
        if isinstance(payload, dict):
            for value in payload.values():
                if isinstance(value, list):
                    payload = value
                    break
            else:
                payload = [payload]
        return pd.json_normalize(payload)
    # default: CSV (delimiter sniffed by pandas' python engine)
    return pd.read_csv(io.BytesIO(data), sep=None, engine="python")


# --------------------------------------------------------- column-alias mapping
# field -> candidate source column names (lower-cased, punctuation-insensitive).
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "type": ("type", "set_piece", "set_piece_type", "event", "event_type", "play_pattern", "situation"),
    "phase": ("phase", "direction", "for_against", "attack_defend"),
    "perspective": ("perspective", "own_opposition", "team_perspective", "side_of_analysis"),
    "team": ("team", "team_name", "attacking_team"),
    "opponent": ("opponent", "opposition", "against"),
    "season": ("season", "campaign"),
    "competition": ("competition", "league", "comp", "tournament"),
    "match_id": ("match_id", "game_id", "fixture_id", "matchid"),
    "match_label": ("match", "match_label", "fixture", "game"),
    "match_date": ("date", "match_date", "game_date", "kickoff_date"),
    "venue": ("venue", "home_away", "location"),
    "taker": ("taker", "player", "delivered_by", "taken_by", "kicker"),
    "foot": ("foot", "delivery_foot", "kicking_foot"),
    "side": ("side", "corner_side", "flank"),
    "subtype": ("subtype", "routine", "variation"),
    "minute": ("minute", "min", "time_min"),
    "period": ("period", "half"),
    "start_x": ("start_x", "x", "origin_x", "delivery_x"),
    "start_y": ("start_y", "y", "origin_y", "delivery_y"),
    "end_x": ("end_x", "target_x", "landing_x", "x2"),
    "end_y": ("end_y", "target_y", "landing_y", "y2"),
    "delivery_type": ("delivery", "delivery_type", "swing", "swing_type", "cross_type"),
    "delivery_height": ("delivery_height", "height"),
    "delivery_length": ("delivery_length", "length"),
    "delivery_speed": ("delivery_speed", "speed", "pace"),
    "players_in_box": ("players_in_box", "attackers_in_box", "box_players", "in_box"),
    "first_contact_team": ("first_contact_team", "first_contact", "first_touch_team"),
    "outcome": ("outcome", "result", "end_result"),
    "shot": ("shot", "is_shot", "shot_taken"),
    "goal": ("goal", "is_goal", "scored"),
    "xg": ("xg", "expected_goals", "xg_value"),
    "second_ball_team": ("second_ball_team", "second_ball", "second_ball_won_by"),
    "retained": ("retained", "retention", "kept_possession"),
    "time_to_first_contact": ("time_to_first_contact", "ttfc"),
    "time_to_shot": ("time_to_shot", "tts"),
    "marking": ("marking", "marking_scheme", "defensive_scheme"),
    "video_url": ("video", "video_url", "clip", "clip_url"),
}

_NUMERIC = {"minute", "period", "players_in_box", "start_x", "start_y", "end_x", "end_y",
            "xg", "time_to_first_contact", "time_to_shot"}
_BOOL = {"shot", "goal", "retained"}


def _clean_col(name: str) -> str:
    return str(name).strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")


def detect_mapping(columns: list[str]) -> dict[str, str]:
    """Best-effort field -> actual-column map from a source header."""
    lookup = {_clean_col(c): c for c in columns}
    mapping: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                mapping[field] = lookup[alias]
                break
    return mapping


def _to_bool(value: Any) -> bool:
    return _norm_token(value) in ("1", "true", "yes", "y", "goal", "shot", "won")


def _to_float(value: Any) -> float | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def normalize_rows(df: pd.DataFrame, mapping: dict[str, str], *,
                   defaults: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn a source DataFrame into canonical field dicts ready to build SetPiece
    records. Unmapped fields fall back to ``defaults`` (e.g. a page-wide
    perspective/phase). Returns (rows, errors)."""
    defaults = defaults or {}
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, raw in df.iterrows():
        try:
            rec: dict[str, Any] = {}
            for field, col in mapping.items():
                if col not in df.columns:
                    continue
                val = raw[col]
                if isinstance(val, float) and pd.isna(val):
                    continue
                if field in _NUMERIC:
                    rec[field] = _to_int(val) if field in ("minute", "period", "players_in_box") else _to_float(val)
                elif field in _BOOL:
                    rec[field] = _to_bool(val)
                else:
                    rec[field] = str(val).strip()
            # canonicalize controlled vocabularies
            rec["type"] = canonical_type(rec.get("type", defaults.get("type", "corner")))
            rec["phase"] = canonical_phase(rec.get("phase", defaults.get("phase", "offensive")))
            rec["perspective"] = canonical_perspective(
                rec.get("perspective", defaults.get("perspective", "own")))
            if rec.get("delivery_type"):
                rec["delivery_type"] = canonical_delivery(rec["delivery_type"])
            if rec.get("side"):
                rec["side"] = canonical_side(rec["side"])
            for k, v in defaults.items():
                rec.setdefault(k, v)
            rows.append(rec)
        except Exception as exc:                       # never let one bad row abort the import
            errors.append(f"row {i}: {exc}")
    return rows, errors
