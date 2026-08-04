"""Opta / Stats Perform F24 event-feed provider.

Vocabulary (event ``type_id`` table + ``qualifier_id`` table) is taken verbatim
from public, authoritative sources rather than memory:

* event type_id -> name : the Opta F24 spec as published in
  tomh05/football-scores ``data/reference/opta-events.csv`` (ids 1-65) and
  mirrored by ML-KULeuven/socceraction ``socceraction/spadl/opta.py``. Ids 74
  (Blocked Pass) and 83 (Attempted Tackle) come from the same public F24 appendix.
* qualifier_id -> meaning : tomh05/football-scores ``opta-qualifiers.csv`` and
  the fluidpixel/RePlayed ``OPTA-Qualifiers`` wiki, cross-checked against
  socceraction ``spadl/opta.py`` (body-part / set-piece derivation).

The feed references teams and players by numeric id only. ``load`` accepts an
optional ``options={"lineup_data": ...}`` roster so those ids resolve to names
(see ``_name_index``); with no roster it falls back to the raw id string and
flags that in ``RawDataset.meta`` and the log.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.signature import ProviderSignature

logger = logging.getLogger(__name__)

# --------------------------------------------------------------- event types
# Opta F24 type_id -> canonical event name. Names are lower-cased so the
# analysis layer's str.lower() selectors match. Verbatim ids per the sources
# in the module docstring.
TYPE_NAMES: dict[int, str] = {
    1: "pass", 2: "offside pass", 3: "dribble", 4: "foul", 5: "ball out",
    6: "corner awarded", 7: "tackle", 8: "interception", 9: "turnover",
    10: "save", 11: "claim", 12: "clearance", 13: "shot", 14: "shot",
    15: "shot", 16: "shot", 17: "card", 18: "substitution", 19: "substitution",
    20: "player retired", 21: "player returns", 22: "player becomes goalkeeper",
    23: "goalkeeper becomes player", 24: "condition change", 25: "official change",
    27: "start delay", 28: "end delay", 30: "end", 32: "start", 34: "team set up",
    35: "player changed position", 36: "player changed jersey number",
    37: "collection end", 40: "formation change", 41: "punch", 43: "deleted event",
    44: "aerial duel", 45: "challenge", 47: "rescinded card", 49: "ball recovery",
    50: "dispossessed", 51: "error", 52: "keeper pick-up", 53: "cross not claimed",
    54: "smother", 55: "offside provoked", 56: "shield ball opp", 57: "foul throw-in",
    58: "penalty faced", 59: "keeper sweeper", 60: "chance missed", 61: "ball touch",
    64: "resume", 65: "contentious referee decision", 74: "blocked pass",
    83: "attempted tackle",
}

_SHOT_TYPES = {13, 14, 15, 16}          # miss, post, attempt saved, goal
_SHOT_ON_TARGET = {15, 16}
_GOAL_TYPE = 16
_SUB_OFF, _SUB_ON = 18, 19
_CARD_TYPE = 17
# type_id -> base shot outcome (before blocked/own-goal qualifiers refine it)
_SHOT_RESULT = {13: "Off Target", 14: "Woodwork", 15: "Saved", 16: "Goal"}

# --------------------------------------------------------------- qualifiers
# Numeric ids verbatim from the Opta F24 qualifier appendix (see docstring).
Q_LONG_BALL, Q_CROSS, Q_HEAD_PASS, Q_THROUGH_BALL = "1", "2", "3", "4"
Q_FREE_KICK_TAKEN, Q_CORNER_TAKEN, Q_PENALTY = "5", "6", "9"
Q_HEAD, Q_RIGHT_FOOT, Q_OTHER_BODY = "15", "20", "21"
Q_REGULAR_PLAY, Q_FAST_BREAK, Q_SET_PIECE = "22", "23", "24"
Q_FROM_CORNER, Q_FROM_FREE_KICK, Q_OWN_GOAL, Q_ASSISTED = "25", "26", "28", "29"
Q_YELLOW_CARD, Q_SECOND_YELLOW, Q_RED_CARD = "31", "32", "33"
Q_LEFT_FOOT, Q_BLOCKED = "72", "82"
Q_THROW_IN, Q_GOAL_KICK, Q_CHIPPED = "107", "124", "155"
Q_ASSIST, Q_BIG_CHANCE, Q_INDIVIDUAL_PLAY, Q_SECOND_ASSIST = "210", "214", "215", "218"
_END_X_Q, _END_Y_Q = "140", "141"

# roster dict keys we recognize when resolving ids -> names (Opta MA1/F9/F40
# and generic shapes all covered)
_ID_KEYS = ("id", "uID", "uId", "playerId", "player_id", "teamId", "team_id",
            "contestantId", "wyId")
_NAME_KEYS = ("name", "known_name", "matchName", "shortName", "short_name",
              "fullName", "last_name", "lastName")


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------- qualifier helpers
def _bodypart(q: dict) -> str:
    if Q_HEAD in q or Q_HEAD_PASS in q:
        return "head"
    if Q_LEFT_FOOT in q:
        return "left foot"
    if Q_RIGHT_FOOT in q:
        return "right foot"
    if Q_OTHER_BODY in q:
        return "other"
    return ""


def _set_piece(q: dict) -> str:
    if Q_PENALTY in q:
        return "Penalty"
    if Q_CORNER_TAKEN in q or Q_FROM_CORNER in q:
        return "Corner"
    if Q_FREE_KICK_TAKEN in q or Q_FROM_FREE_KICK in q:
        return "Free kick"
    if Q_THROW_IN in q:
        return "Throw-in"
    if Q_GOAL_KICK in q:
        return "Goal kick"
    return ""


def _play_pattern(q: dict) -> str:
    if Q_FAST_BREAK in q:
        return "Fast break"
    if Q_FROM_CORNER in q:
        return "From corner"
    if Q_FROM_FREE_KICK in q:
        return "From free kick"
    if Q_SET_PIECE in q:
        return "Set piece"
    if Q_REGULAR_PLAY in q:
        return "Regular play"
    return ""


def _pass_subtype(q: dict) -> str:
    if Q_CROSS in q:
        return "cross"
    if Q_THROUGH_BALL in q:
        return "through ball"
    if Q_LONG_BALL in q:
        return "long ball"
    if Q_CHIPPED in q:
        return "chipped"
    if Q_HEAD_PASS in q:
        return "head pass"
    return ""


def _card_name(q: dict) -> str:
    if Q_RED_CARD in q or Q_SECOND_YELLOW in q:
        return "red card"
    if Q_YELLOW_CARD in q:
        return "yellow card"
    return "card"


def _shot_result(type_id: int, q: dict) -> str:
    if Q_OWN_GOAL in q:
        return "Own goal"
    if type_id != _GOAL_TYPE and Q_BLOCKED in q:      # a goal is never "blocked"
        return "Blocked"
    return _SHOT_RESULT.get(type_id, "")


# --------------------------------------------------------------- name resolution
def _person(d: Any) -> tuple[str, str] | None:
    """Pull an (id, name) pair out of one roster entry, tolerating vendor shapes."""
    if not isinstance(d, dict):
        return None
    pid = next((str(d[k]) for k in _ID_KEYS if d.get(k) not in (None, "")), "")
    name = next((str(d[k]) for k in _NAME_KEYS if d.get(k) not in (None, "")), "")
    if not name and d.get("first_name") and d.get("last_name"):
        name = f"{d['first_name']} {d['last_name']}".strip()
    return (pid, name) if pid and name else None


def _add_map(container: Any, target: dict[str, str]) -> None:
    """Index a roster container (an ``{id: name}`` map or a list of entries)."""
    if isinstance(container, dict):
        for key, val in container.items():
            if isinstance(val, str):
                if val.strip():
                    target[str(key)] = val
            else:
                pair = _person(val)
                if pair:
                    target[pair[0]] = pair[1]
    elif isinstance(container, list):
        for item in container:
            pair = _person(item)
            if pair:
                target[pair[0]] = pair[1]


def _name_index(options: dict[str, Any] | None) -> tuple[dict[str, str], dict[str, str]]:
    """Return (team_names, player_names) from ``options['lineup_data']``.

    Accepted shapes (all tolerated, missing/odd keys ignored):
      * ``{"teams": {id: name}, "players": {id: name}}``  (simplest)
      * ``{"teams": [{"id", "name", "players": [{"id", "name"}, ...]}, ...]}``
      * a flat ``{id: name}`` applied to both teams and players.
    """
    teams: dict[str, str] = {}
    players: dict[str, str] = {}
    data = (options or {}).get("lineup_data")
    if not data:
        return teams, players
    if isinstance(data, dict) and ("teams" in data or "players" in data):
        _add_map(data.get("teams"), teams)
        _add_map(data.get("players"), players)
        if isinstance(data.get("teams"), list):        # players nested inside teams
            for team in data["teams"]:
                if isinstance(team, dict):
                    for key in ("players", "Player", "playerLineUp", "squad"):
                        if team.get(key):
                            _add_map(team[key], players)
    else:                                               # flat {id: name}
        _add_map(data, teams)
        players.update(teams)
    return teams, players


@provider_registry.register
class OptaF24Provider(DataProvider):
    info = PluginInfo(id="opta_f24", name="Opta F24 events (XML)", category="vendor",
                      description="Opta / Stats Perform F24 match event feeds.")

    signature = ProviderSignature(
        supported_extensions=(".xml",),
        filename_patterns=("opta", "f24"),
        json_patterns=("Games", "Game", "Event"),
        provider_identifiers=("qualifier_id", "type_id"),
        optional_columns=("period_id", "team_id", "player_id", "outcome"),
        schema_version="opta-f24",
    )

    def supports(self, filename: str) -> bool:
        low = filename.lower()
        return low.endswith(".xml") and ("opta" in low or "f24" in low)

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        try:
            root = ET.parse(source).getroot()
        except ET.ParseError as exc:
            raise ProviderError(f"Invalid Opta XML {filename!r}: {exc}") from exc

        game = root.find(".//Game") if root.tag != "Game" else root
        if game is None:
            raise ProviderError("No <Game> element found in Opta file")

        team_names, player_names = _name_index(options)
        have_roster = bool(team_names or player_names)
        unresolved_players: set[str] = set()
        unresolved_teams: set[str] = set()

        rows: list[dict[str, Any]] = []
        for e in game.findall("Event"):
            try:
                rows.append(self._event_row(e, game, team_names, player_names,
                                            unresolved_players, unresolved_teams))
            except Exception:  # noqa: BLE001 - one malformed event must not sink the file
                logger.exception("Skipping malformed Opta event in %s", filename)

        if not have_roster and (unresolved_players or unresolved_teams):
            logger.warning(
                "Opta %s: no lineup_data supplied - %d player ids and %d team ids "
                "left unresolved (pass options={'lineup_data': ...} to resolve names)",
                filename, len(unresolved_players), len(unresolved_teams))

        meta = {
            "name_resolution": "resolved" if have_roster else "ids_only",
            "unresolved_players": sorted(unresolved_players),
            "unresolved_teams": sorted(unresolved_teams),
            # Lineups/formations: substitution events (type 18/19) are emitted as
            # rows, but formation geometry (qualifiers 130 team formation / 131
            # player positions / 145) is not decoded here - it would need the F9/F40
            # squad feed. Not inferable safely from F24 alone.
            "lineups_supported": bool(have_roster),
        }
        return RawDataset(frame=pd.DataFrame(rows), native_coord_system="opta", meta=meta)

    def _event_row(self, e: ET.Element, game: ET.Element,
                   team_names: dict[str, str], player_names: dict[str, str],
                   unresolved_players: set[str], unresolved_teams: set[str]) -> dict[str, Any]:
        type_id = _int(e.get("type_id", 0))
        q = {qe.get("qualifier_id"): qe.get("value") for qe in e.findall("Q")}

        event_type = TYPE_NAMES.get(type_id, f"opta_type_{type_id}")
        if type_id == 1 and Q_CROSS in q:            # crosses are passes+cross qualifier;
            event_type = "cross"                     # surface as their own canonical type

        # sub-classification / enrichment
        if type_id == 1:
            sub_event = _pass_subtype(q)
        elif type_id in _SHOT_TYPES:
            sub_event = "penalty" if Q_PENALTY in q else _bodypart(q)
        elif type_id == _CARD_TYPE:
            sub_event = _card_name(q)
        else:
            sub_event = ""
        if not sub_event:
            sub_event = str(type_id)                 # keep the numeric id as a fallback

        notes: list[str] = []
        if Q_BIG_CHANCE in q:
            notes.append("big chance")
        if Q_INDIVIDUAL_PLAY in q:
            notes.append("individual play")
        if type_id == _SUB_OFF:
            notes.append("player off")
        elif type_id == _SUB_ON:
            notes.append("player on")

        is_pass_like = type_id in (1, 2)
        assist = Q_ASSIST in q
        # Opta has no dedicated "key pass" id; an assist (210) or a created big
        # chance (214) on a pass is the accepted proxy (see socceraction/kloppy).
        key_pass = is_pass_like and (assist or Q_BIG_CHANCE in q)

        team_raw = e.get("team_id", "") or ""
        player_raw = e.get("player_id", "") or ""
        team = team_names.get(team_raw, team_raw)
        player = player_names.get(player_raw, player_raw)
        if team_raw and team_raw not in team_names:
            unresolved_teams.add(team_raw)
        if player_raw and player_raw not in player_names:
            unresolved_players.add(player_raw)

        return {
            "event_type": event_type,
            "sub_event": sub_event,
            "team": team,
            "player": player,
            "minute": _int(e.get("min", 0)), "second": _int(e.get("sec", 0)),
            "period": _int(e.get("period_id", 1), 1),
            "x": _num(e.get("x")), "y": _num(e.get("y")),
            "end_x": _num(q.get(_END_X_Q)), "end_y": _num(q.get(_END_Y_Q)),
            "outcome": "successful" if e.get("outcome") == "1" else "unsuccessful",
            "shot_result": _shot_result(type_id, q) if type_id in _SHOT_TYPES else "",
            "body_part": _bodypart(q),
            "set_piece": _set_piece(q),
            "play_pattern": _play_pattern(q),
            "assist": assist,
            "key_pass": key_pass,
            "notes": "; ".join(notes),
            "match_id": game.get("id", ""),
            "competition": game.get("competition_name", ""),
            "season": game.get("season_name", ""),
            "date": game.get("game_date", ""),
        }
