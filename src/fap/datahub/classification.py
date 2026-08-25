"""Dataset classification intelligence — the Data Hub's front door.

Before the Data Hub runs any analyzer it must know *what a file represents*, so it
routes the raw table to the right analyzer instead of forcing every file through
the event pipeline. This module answers that question from the table's schema and
content — never from its filename — distinguishing:

    event            one row per on-ball event, carrying x/y coordinates
    tracking         positional/XY frames (many player x/y columns, frame ids)
    player_scouting  one row per player, carrying player-level metrics
    player_roster    a player identity table with no meaningful metrics
    set_piece        set-piece deliveries (corner/free-kick/throw-in tagging)
    team_match_stats a team-comparison stat table: rows are statistics, columns
                     are the teams being compared (no x/y, no player identity)
    unknown          nothing recognizable

The guiding principle is *classify what the rows represent, not how many rows
exist*: a one-player shortlist and a 500-player database classify identically.
Detection is deterministic and pure (pandas only, no Streamlit, no I/O).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# ---------------------------------------------------------------- dataset types
EVENT = "event"
TRACKING = "tracking"
PLAYER_SCOUTING = "player_scouting"
PLAYER_ROSTER = "player_roster"
SET_PIECE = "set_piece"
TEAM_MATCH_STATS = "team_match_stats"
UNKNOWN = "unknown"

DATASET_TYPES: tuple[str, ...] = (
    EVENT, TRACKING, PLAYER_SCOUTING, PLAYER_ROSTER, SET_PIECE,
    TEAM_MATCH_STATS, UNKNOWN,
)

# entity a row represents
ENTITY_EVENT = "event"
ENTITY_FRAME = "frame"
ENTITY_PLAYER = "player"
ENTITY_SET_PIECE = "set_piece"
ENTITY_TEAM_STAT = "team_stat"


# ---------------------------------------------------------------- identity aliases
# canonical dimension -> the header variations that name it. Matched against a
# normalized column key (lower-cased, punctuation/whitespace collapsed), so
# "Player Name", "player_name" and "PLAYER" all resolve to the same dimension.
IDENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "player": ("player", "player name", "playername", "name", "athlete",
               "full name", "fullname", "known as"),
    "team": ("team", "club", "squad", "current club", "team name"),
    "league": ("league", "competition", "comp", "division", "tournament"),
    "position": ("position", "pos", "role", "primary position", "positions"),
    "age": ("age",),
    "country": ("country", "nationality", "birth country", "nation", "birthplace",
                "citizenship", "passport country"),
}

# supporting dimensions that are demographic/contextual, never analytical metrics
_DEMOGRAPHIC_KEYS: frozenset[str] = frozenset({
    "age", "foot", "preferred foot", "height", "weight", "dob",
    "date of birth", "birth date", "birthday", "shirt number", "shirt no",
    "jersey", "jersey number", "number", "market value", "value",
    "contract until", "contract", "contract expires", "agent", "nickname",
    "on loan", "loan", "status", "matches played", "matches", "appearances",
    "apps", "games", "starts", "minutes played", "minutes", "min", "birth country",
})

# columns that are import/index artifacts, never analytical content
_INDEX_KEYS: frozenset[str] = frozenset({"", "index", "idx", "id", "no", "rank", "#", "row"})

# tokens that mark a numeric column as a genuine player performance metric. Used
# to lift confidence and to recognise a scouting table even when few metrics are
# present — never required in full (any combination is enough).
_METRIC_TOKENS: tuple[str, ...] = (
    "per 90", "per90", "/90", "p90", "%", "percent", "xg", "npxg", "xa", "xt",
    "goal", "assist", "shot", "pass", "dribble", "duel", "tackle", "intercept",
    "block", "clearance", "aerial", "cross", "touch", "recover", "pressure",
    "accelerat", "sprint", "progressive", "key pass", "smart pass", "conversion",
    "save rate", "prevented", "conceded", "foul", "card", "exit", "carry",
    "possession", "rating", "score", "index", "ratio", "rate", "won", "success",
)

# columns that betray on-ball event / positional data (never a scouting table)
_COORD_PAIRS: tuple[tuple[str, str], ...] = (
    ("x", "y"), ("start x", "start y"), ("startx", "starty"),
    ("end x", "end y"), ("endx", "endy"), ("location x", "location y"),
    ("pos x", "pos y"), ("x1", "y1"), ("x2", "y2"), ("ball x", "ball y"),
    ("coord x", "coord y"),
)
_EVENT_KEYS: frozenset[str] = frozenset({
    "event type", "eventtype", "event", "event name", "eventname", "type id",
    "typeid", "sub event", "subevent", "qualifier", "qualifiers",
})
_TRACKING_KEYS: frozenset[str] = frozenset({
    "frame", "frame id", "frameid", "frame count", "gameclock", "game clock",
    "period id", "timestamp ms", "tracking",
})
_SET_PIECE_KEYS: frozenset[str] = frozenset({
    "set piece", "setpiece", "set play", "dead ball", "restart",
})
_SET_PIECE_VALUES: frozenset[str] = frozenset({
    "corner", "free kick", "freekick", "free_kick", "throw in", "throw_in",
    "throwin", "penalty",
})

# team-comparison stat tables: one column names the statistic (its rows are stat
# labels, not entities), the remaining columns are the teams being compared.
_STAT_LABEL_KEYS: frozenset[str] = frozenset({
    "statistic", "statistics", "stat", "stats", "metric", "metrics", "kpi",
    "measure", "parameter", "indicator",
})
_STAT_CATEGORY_KEYS: frozenset[str] = frozenset({
    "category", "categories", "group", "grouping", "section", "phase",
})


def normalize_key(name: Any) -> str:
    """Collapse a raw header to a stable comparison key: lower-cased, punctuation
    and (possibly multi-line) whitespace flattened to single spaces."""
    s = str(name).strip().lower()
    s = s.replace("_", " ").replace("/", " ")
    s = re.sub(r"[^a-z0-9% ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _has_metric_token(key: str) -> bool:
    return any(tok in key for tok in _METRIC_TOKENS)


def is_index_artifact(name: Any) -> bool:
    """A pure import/index column (e.g. pandas' ``Unnamed: 0``) — never a metric."""
    key = normalize_key(name)
    if key in _INDEX_KEYS:
        return True
    return bool(re.match(r"^unnamed( \d+)?$", key))


def _identity_for(key: str) -> str | None:
    for canonical, aliases in IDENTITY_ALIASES.items():
        if key in aliases:
            return canonical
    return None


@dataclass(frozen=True, slots=True)
class DatasetClassification:
    """The verdict: what the rows represent, how sure we are, and why.

    ``entity_count`` is metadata (players/frames/events observed), deliberately
    kept *out* of ``dataset_type`` — a 1-row and a 500-row scouting table are the
    same type. ``signals`` carries the raw evidence for the UI and for tests.
    """
    dataset_type: str
    entity_type: str
    confidence: float
    entity_count: int = 0
    reasons: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def is_player_scouting(self) -> bool:
        return self.dataset_type in (PLAYER_SCOUTING, PLAYER_ROSTER)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_type": self.dataset_type,
            "entity_type": self.entity_type,
            "confidence": round(self.confidence, 3),
            "entity_count": self.entity_count,
            "reasons": list(self.reasons),
            "signals": dict(self.signals),
        }


def _column_keys(frame: pd.DataFrame) -> list[str]:
    return [normalize_key(c) for c in frame.columns]


def _numeric_fraction(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    coerced = pd.to_numeric(series, errors="coerce")
    return float(coerced.notna().mean())


def to_number(series: pd.Series) -> pd.Series:
    """Coerce a column to numbers, tolerating the display formatting common in
    team-stat tables — a trailing ``%`` and thousands separators (``"56%"`` -> 56,
    ``"1,024"`` -> 1024). Non-numeric cells become NaN. Never rescales (a percent
    is kept as its face value, not divided by 100)."""
    s = series.astype(str).str.strip()
    s = s.str.replace("%", "", regex=False).str.replace(",", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _numeric_or_percent_fraction(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(to_number(series).notna().mean())


def _has_coordinates(keys: set[str]) -> bool:
    for xk, yk in _COORD_PAIRS:
        if xk in keys and yk in keys:
            return True
    return False


def classify_frame(frame: pd.DataFrame) -> DatasetClassification:
    """Classify a raw provider frame. Deterministic; depends only on the schema
    and column content, never on row count or filename."""
    if frame is None or len(frame.columns) == 0:
        return DatasetClassification(UNKNOWN, "", 0.0, 0, ["empty table"], {})

    # meaningful rows (a trailing all-blank CSV row is not an entity)
    non_empty = frame.dropna(how="all")
    row_count = int(len(non_empty))

    keys = _column_keys(frame)
    key_set = set(keys)
    key_to_col = {normalize_key(c): c for c in frame.columns}

    # --- structural signals -------------------------------------------------
    has_coords = _has_coordinates(key_set)
    has_event_col = bool(key_set & _EVENT_KEYS)
    has_tracking = bool(key_set & _TRACKING_KEYS)
    # resolve identity columns, first winner per canonical dimension
    identity_cols: dict[str, str] = {}
    for k, orig in ((normalize_key(c), c) for c in frame.columns):
        canonical = _identity_for(k)
        if canonical and canonical not in identity_cols:
            identity_cols[canonical] = orig
    has_player = "player" in identity_cols

    # metrics: numeric, non-identity, non-demographic, non-index columns
    metric_cols: list[str] = []
    metric_named = 0
    for col in frame.columns:
        k = normalize_key(col)
        if is_index_artifact(col) or _identity_for(k) is not None or k in _DEMOGRAPHIC_KEYS:
            continue
        series = non_empty[col] if col in non_empty.columns else frame[col]
        if series.dropna().empty:
            continue                                   # all-null column: ignore
        if _numeric_fraction(series) >= 0.6:
            metric_cols.append(col)
            if _has_metric_token(k):
                metric_named += 1
    metric_count = len(metric_cols)

    signals: dict[str, Any] = {
        "columns": int(len(frame.columns)),
        "rows": row_count,
        "has_coordinates": has_coords,
        "has_event_column": has_event_col,
        "has_tracking_markers": has_tracking,
        "identity_columns": dict(identity_cols),
        "metric_count": metric_count,
        "named_metric_count": metric_named,
    }

    # --- event / tracking take priority when coordinates are present --------
    # Event and positional data always carry x/y (x,y are REQUIRED canonical
    # columns); a scouting table never does. This is the safe discriminator that
    # keeps existing event ingestion untouched.
    if has_coords or (has_event_col and has_tracking):
        if has_tracking:
            return DatasetClassification(
                TRACKING, ENTITY_FRAME, 0.9, row_count,
                ["positional/XY columns with frame markers"], signals)
        return DatasetClassification(
            EVENT, ENTITY_EVENT, 0.9 if has_event_col else 0.7, row_count,
            ["on-ball coordinate columns present"], signals)

    if has_event_col and not has_player and not metric_count:
        return DatasetClassification(
            EVENT, ENTITY_EVENT, 0.6, row_count,
            ["event-type column without player-level metrics"], signals)

    # --- set-piece table (no coordinates, dominated by set-piece tagging) ----
    sp_col = next((key_to_col[k] for k in _SET_PIECE_KEYS if k in key_set), None)
    if sp_col is not None and not has_player:
        return DatasetClassification(
            SET_PIECE, ENTITY_SET_PIECE, 0.7, row_count,
            ["set-piece tagging column present"], signals)

    # --- player-level tables -------------------------------------------------
    if has_player:
        # metrics decide scouting vs a bare roster/identity table.
        if metric_count >= 3 or (metric_count >= 1 and metric_named >= 1):
            conf = _scouting_confidence(metric_count, metric_named, identity_cols)
            reasons = [
                f"player identity column ({identity_cols['player']!r})",
                f"{metric_count} player-level metric column(s)"
                f" ({metric_named} named)",
            ]
            if len(identity_cols) > 1:
                reasons.append("supporting dimensions: "
                               + ", ".join(sorted(k for k in identity_cols if k != "player")))
            return DatasetClassification(
                PLAYER_SCOUTING, ENTITY_PLAYER, conf, row_count, reasons, signals)
        # identity but no analytical value → roster/identity table
        return DatasetClassification(
            PLAYER_ROSTER, ENTITY_PLAYER, 0.55, row_count,
            ["player identity column but no meaningful metrics"], signals)

    # --- team-comparison stat table -----------------------------------------
    # A stat-label column (its rows are statistic names, not entities) plus two or
    # more numeric/percent value columns (the teams being compared). Reached only
    # when there is no player identity, so it never collides with scouting.
    stat_col = next((key_to_col[k] for k in _STAT_LABEL_KEYS if k in key_set), None)
    if stat_col is not None:
        cat_col = next((key_to_col[k] for k in _STAT_CATEGORY_KEYS if k in key_set), None)
        skip = {stat_col, cat_col}
        team_cols = [
            c for c in frame.columns
            if c not in skip and not is_index_artifact(c)
            and _numeric_or_percent_fraction(
                non_empty[c] if c in non_empty.columns else frame[c]) >= 0.6
        ]
        if len(team_cols) >= 2:
            signals["stat_label_column"] = str(stat_col)
            signals["team_columns"] = [str(c) for c in team_cols]
            signals["category_column"] = str(cat_col) if cat_col is not None else ""
            conf = 0.86 if cat_col is not None else 0.76
            reasons = [
                f"statistic-label column ({stat_col!r})",
                f"{len(team_cols)} team value column(s): "
                + ", ".join(str(c) for c in team_cols),
            ]
            if cat_col is not None:
                reasons.append(f"category grouping column ({cat_col!r})")
            return DatasetClassification(
                TEAM_MATCH_STATS, ENTITY_TEAM_STAT, conf, row_count, reasons, signals)

    return DatasetClassification(
        UNKNOWN, "", 0.2, row_count,
        ["no coordinate, event, set-piece, player-identity or team-stat signals"],
        signals)


def _scouting_confidence(metric_count: int, metric_named: int,
                         identity_cols: dict[str, str]) -> float:
    """Confidence scales with metric breadth, how many are recognisable
    performance metrics, and how many supporting dimensions are present. Bounded
    so a thin-but-valid single-metric table still classifies (lower confidence),
    and a rich table saturates near-certain."""
    conf = 0.55
    conf += min(metric_count, 20) * 0.02          # up to +0.40 for breadth
    conf += min(metric_named, 10) * 0.02          # up to +0.20 for named metrics
    conf += min(len(identity_cols) - 1, 5) * 0.02  # up to +0.10 for dimensions
    return round(min(conf, 0.98), 3)


__all__ = [
    "DATASET_TYPES", "EVENT", "TRACKING", "PLAYER_SCOUTING", "PLAYER_ROSTER",
    "SET_PIECE", "TEAM_MATCH_STATS", "UNKNOWN", "ENTITY_PLAYER", "ENTITY_EVENT",
    "ENTITY_FRAME", "ENTITY_TEAM_STAT", "IDENTITY_ALIASES", "DatasetClassification",
    "classify_frame", "normalize_key", "is_index_artifact", "to_number",
]
