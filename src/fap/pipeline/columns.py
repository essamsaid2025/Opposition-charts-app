"""Automatic football-column detection.

Every canonical field carries a list of known aliases across vendors and
manual-tagging conventions. Matching is done on normalized names (case,
spaces, punctuation stripped); exact alias hits score 1.0, fuzzy hits score
proportionally. The wizard shows the manual mapping UI when confidence is low.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

ALIASES: dict[str, tuple[str, ...]] = {
    "x": ("x", "start_x", "from_x", "origin_x", "pos_x", "location_x", "x_start", "x1", "startx"),
    "y": ("y", "start_y", "from_y", "origin_y", "pos_y", "location_y", "y_start", "y1", "starty"),
    "end_x": ("end_x", "x2", "target_x", "to_x", "dest_x", "pass_end_x", "x_end", "endx"),
    "end_y": ("end_y", "y2", "target_y", "to_y", "dest_y", "pass_end_y", "y_end", "endy"),
    "player": ("player", "player_name", "playername", "from", "athlete", "name"),
    "receiver": ("receiver", "pass_recipient", "to", "recipient", "target_player"),
    "team": ("team", "team_name", "teamname", "club", "squad"),
    "opponent": ("opponent", "opposition", "against", "opponent_team"),
    "event_type": ("event_type", "event", "type", "action", "event_name", "code", "type_name"),
    "sub_event": ("sub_event", "subtype", "sub_type", "subeventname", "detail", "secondary"),
    "outcome": ("outcome", "result", "success", "successful", "outcome_name", "accurate"),
    "minute": ("minute", "min", "time_min", "match_minute"),
    "second": ("second", "sec", "seconds"),
    "period": ("period", "half", "match_period", "period_id"),
    "timestamp": ("timestamp", "time", "event_sec", "start_time", "time_seconds", "start"),
    "match_id": ("match_id", "matchid", "game_id", "game", "fixture_id", "fixture"),
    "competition": ("competition", "league", "tournament", "comp"),
    "season": ("season", "season_name", "year"),
    "date": ("date", "match_date", "kickoff", "game_date"),
    "jersey_number": ("jersey_number", "shirt_number", "jersey", "number", "shirt", "kit_number"),
    "position": ("position", "pos", "role", "position_name"),
    "body_part": ("body_part", "bodypart", "foot", "body_part_name"),
    "play_pattern": ("play_pattern", "pattern", "phase_of_play", "play_pattern_name"),
    "set_piece": ("set_piece", "setpiece", "restart", "dead_ball"),
    "assist": ("assist", "is_assist", "assists"),
    "key_pass": ("key_pass", "keypass", "is_key_pass", "chance_created"),
    "shot_xg": ("shot_xg", "xg", "expected_goals", "statsbomb_xg", "shot_statsbomb_xg"),
    "pass_length": ("pass_length", "length", "distance_pass"),
    "pass_angle": ("pass_angle", "angle"),
    "pass_height": ("pass_height", "height", "pass_height_name"),
    "carry_distance": ("carry_distance", "carry_length", "dribble_distance"),
    "under_pressure": ("under_pressure", "pressured", "underpressure"),
    "pressure": ("pressure", "is_pressure"),
    "shot_result": ("shot_result", "shot_outcome", "shot_outcome_name", "goal_result"),
    "sequence_id": ("sequence_id", "possession", "possession_id", "sequence", "chain_id"),
    "phase": ("phase", "game_phase", "game_state"),
    "notes": ("notes", "comment", "description", "labels", "text"),
}

# canonical fields weighted for the overall confidence figure
_KEY_FIELDS = ("x", "y", "event_type", "player", "team")
CONFIDENCE_THRESHOLD = 0.85   # below this the wizard opens manual mapping


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


@dataclass(slots=True)
class ColumnMapping:
    """source column -> canonical field, with per-field confidence."""
    mapping: dict[str, str] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    unmapped_sources: list[str] = field(default_factory=list)

    @property
    def overall_confidence(self) -> float:
        scores = [self.confidence.get(f, 0.0) for f in _KEY_FIELDS]
        return sum(scores) / len(scores)

    @property
    def needs_review(self) -> bool:
        return self.overall_confidence < CONFIDENCE_THRESHOLD

    def rename_dict(self) -> dict[str, str]:
        return dict(self.mapping)


def detect_columns(df: pd.DataFrame) -> ColumnMapping:
    result = ColumnMapping()
    norm_alias = {canonical: [_norm(a) for a in aliases] for canonical, aliases in ALIASES.items()}
    taken: set[str] = set()
    sources = [str(c) for c in df.columns]

    # pass 1: exact alias matches
    for src in sources:
        n = _norm(src)
        for canonical, aliases in norm_alias.items():
            if canonical in taken:
                continue
            if n in aliases:
                result.mapping[src] = canonical
                result.confidence[canonical] = 1.0
                taken.add(canonical)
                break

    # pass 2: fuzzy matches for what's left
    for src in sources:
        if src in result.mapping:
            continue
        n = _norm(src)
        best_canonical, best_score = "", 0.0
        for canonical, aliases in norm_alias.items():
            if canonical in taken:
                continue
            score = max(SequenceMatcher(None, n, a).ratio() for a in aliases)
            if score > best_score:
                best_canonical, best_score = canonical, score
        if best_score >= 0.75:
            result.mapping[src] = best_canonical
            result.confidence[best_canonical] = round(best_score * 0.9, 3)
            taken.add(best_canonical)
        else:
            result.unmapped_sources.append(src)
    return result
