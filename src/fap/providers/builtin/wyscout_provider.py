"""Wyscout v2 event-feed provider.

The tag vocabulary is taken verbatim from public, authoritative sources rather
than memory:

* tag_id -> meaning : the Wyscout v2 tag table as implemented by
  PySport/kloppy (``WyscoutDeserializer``) and ML-KULeuven/socceraction
  ``socceraction/spadl/wyscout.py``. Ids below are quoted from those tables
  (accurate 1801, assist 301, key pass 302, body-part 401/402/403, cards
  1701/1702/1703, counter-attack 1901, interception 1401, clearance 1501,
  sliding tackle 1601, blocked 2101, through 901, ...).
* eventName / subEventName are already human-readable strings in the v2 feed,
  so they are used directly (only crosses are lifted to their own canonical
  ``event_type`` to match the app's cross analytics).

Events reference teams/players by numeric id only. ``load`` accepts an optional
``options={"lineup_data": ...}`` roster (Wyscout teams/players payloads or a
simple ``{id: name}`` map) to resolve those ids to names; without it the raw id
string is kept and the gap is flagged in ``RawDataset.meta`` and the log.
"""
from __future__ import annotations

import json
import logging
from typing import Any, BinaryIO

import pandas as pd

from fap.core.exceptions import ProviderError
from fap.core.plugin import PluginInfo
from fap.providers.base import DataProvider, RawDataset, provider_registry
from fap.providers.signature import ProviderSignature

logger = logging.getLogger(__name__)

_PERIODS = {"1H": 1, "2H": 2, "E1": 3, "E2": 4, "P": 5}

# --------------------------------------------------------------- tag ids
# Verbatim numeric tag ids per the sources in the module docstring.
T_ACCURATE, T_INACCURATE = 1801, 1802
T_GOAL, T_OWN_GOAL = 101, 102
T_ASSIST, T_KEY_PASS = 301, 302
T_LEFT_FOOT, T_RIGHT_FOOT, T_HEAD_BODY = 401, 402, 403
T_COUNTER_ATTACK = 1901
T_OPPORTUNITY = 201
T_THROUGH = 901
T_INTERCEPTION, T_CLEARANCE, T_SLIDING_TACKLE = 1401, 1501, 1601
T_DANGEROUS_BALL_LOST, T_BLOCKED = 2001, 2101
T_RED_CARD, T_YELLOW_CARD, T_SECOND_YELLOW = 1701, 1702, 1703
T_WON, T_LOST, T_NEUTRAL = 703, 701, 702

# roster keys recognised when resolving ids -> names (Wyscout teams/players
# payloads plus generic shapes)
_ID_KEYS = ("wyId", "id", "playerId", "teamId", "player_id", "team_id")
_NAME_KEYS = ("shortName", "short_name", "name", "officialName", "lastName",
              "last_name", "matchName", "known_name")


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------- tag helpers
def _body_part(tags: set[int]) -> str:
    if T_HEAD_BODY in tags:
        return "head"
    if T_LEFT_FOOT in tags:
        return "left foot"
    if T_RIGHT_FOOT in tags:
        return "right foot"
    return ""


def _card(tags: set[int]) -> str:
    if T_RED_CARD in tags or T_SECOND_YELLOW in tags:
        return "red card"
    if T_YELLOW_CARD in tags:
        return "yellow card"
    return ""


def _set_piece(sub_name: str) -> str:
    s = sub_name.lower()
    if "penalty" in s:
        return "Penalty"
    if "corner" in s:
        return "Corner"
    if "throw" in s:
        return "Throw-in"
    if "goal kick" in s:
        return "Goal kick"
    if "free kick" in s:
        return "Free kick"
    return ""


def _shot_result(event_name: str, tags: set[int]) -> str:
    if event_name.lower() != "shot":
        return ""
    if T_GOAL in tags:
        return "Goal"
    if T_OWN_GOAL in tags:
        return "Own goal"
    if T_BLOCKED in tags:
        return "Blocked"
    if T_ACCURATE in tags:            # for shots, accurate == on target
        return "On Target"
    if T_INACCURATE in tags:
        return "Off Target"
    return ""


# --------------------------------------------------------------- name resolution
def _person(d: Any) -> tuple[str, str] | None:
    if not isinstance(d, dict):
        return None
    pid = next((str(d[k]) for k in _ID_KEYS if d.get(k) not in (None, "")), "")
    name = next((str(d[k]) for k in _NAME_KEYS if d.get(k) not in (None, "")), "")
    if not name and d.get("firstName") and d.get("lastName"):
        name = f"{d['firstName']} {d['lastName']}".strip()
    return (pid, name) if pid and name else None


def _add_map(container: Any, target: dict[str, str]) -> None:
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

    Accepts ``{"teams": {id: name}, "players": {id: name}}``, Wyscout-style
    ``{"teams": [{"wyId", "name"}...], "players": [{"wyId", "shortName"}...]}``,
    or a flat ``{id: name}`` applied to both.
    """
    teams: dict[str, str] = {}
    players: dict[str, str] = {}
    data = (options or {}).get("lineup_data")
    if not data:
        return teams, players
    if isinstance(data, dict) and ("teams" in data or "players" in data):
        _add_map(data.get("teams"), teams)
        _add_map(data.get("players"), players)
    else:
        _add_map(data, teams)
        players.update(teams)
    return teams, players


@provider_registry.register
class WyscoutProvider(DataProvider):
    info = PluginInfo(id="wyscout", name="Wyscout events (JSON)", category="vendor",
                      description="Wyscout v2/v3 event exports.")

    signature = ProviderSignature(
        supported_extensions=(".json",),
        filename_patterns=("wyscout",),
        # deliberately NOT json_patterns=("events",): plenty of non-Wyscout
        # exports wrap their records in an "events" key. Wyscout is recognized
        # by its own field names and its positions[]/tags[] shape instead.
        nested_object_patterns=("positions.x", "tags.id"),
        provider_identifiers=("eventName", "matchPeriod", "eventSec", "subEventName"),
        optional_columns=("eventName", "teamId", "playerId", "matchPeriod", "positions"),
        schema_version="wyscout-v2",
    )

    def supports(self, filename: str) -> bool:
        return "wyscout" in filename.lower() and filename.lower().endswith(".json")

    def load(self, source: BinaryIO, filename: str,
             options: dict[str, Any] | None = None) -> RawDataset:
        try:
            payload = json.load(source)
        except Exception as exc:
            raise ProviderError(f"Invalid Wyscout JSON {filename!r}: {exc}") from exc
        events = payload.get("events", payload) if isinstance(payload, dict) else payload
        if not isinstance(events, list):
            raise ProviderError("Wyscout file must contain a list of events")

        # a roster embedded in the same payload is used automatically; an explicit
        # options["lineup_data"] wins over it.
        embedded = {k: payload[k] for k in ("teams", "players") if isinstance(payload, dict)
                    and k in payload} or None
        team_names, player_names = _name_index(options or ({"lineup_data": embedded}
                                                           if embedded else None))
        have_roster = bool(team_names or player_names)
        unresolved_players: set[str] = set()
        unresolved_teams: set[str] = set()

        rows: list[dict[str, Any]] = []
        for e in events:
            try:
                rows.append(self._event_row(e, team_names, player_names,
                                            unresolved_players, unresolved_teams))
            except Exception:  # noqa: BLE001 - one bad record must not sink the file
                logger.exception("Skipping malformed Wyscout event in %s", filename)

        if not have_roster and (unresolved_players or unresolved_teams):
            logger.warning(
                "Wyscout %s: no lineup_data supplied - %d player ids and %d team ids "
                "left unresolved (pass options={'lineup_data': ...} to resolve names)",
                filename, len(unresolved_players), len(unresolved_teams))

        meta = {
            "name_resolution": "resolved" if have_roster else "ids_only",
            "unresolved_players": sorted(unresolved_players),
            "unresolved_teams": sorted(unresolved_teams),
            # Lineups/formations/substitutions are NOT in the v2 events feed - they
            # live in the separate match/formations payload (teams[].formation with
            # lineup + substitutions). Not inferable from the events stream alone.
            "lineups_supported": bool(have_roster),
        }
        return RawDataset(frame=pd.DataFrame(rows), native_coord_system="wyscout", meta=meta)

    def _event_row(self, e: dict, team_names: dict[str, str], player_names: dict[str, str],
                   unresolved_players: set[str], unresolved_teams: set[str]) -> dict[str, Any]:
        positions = e.get("positions") or [{}]
        start = positions[0] if positions else {}
        end = positions[1] if len(positions) > 1 else {}
        tags = {t.get("id") for t in e.get("tags", []) if isinstance(t, dict)}

        event_name = str(e.get("eventName", ""))
        sub_name = str(e.get("subEventName", ""))
        event_type = event_name
        if "cross" in sub_name.lower():          # surface crosses as their own type
            event_type = "cross"

        outcome = ("successful" if T_ACCURATE in tags
                   else "unsuccessful" if T_INACCURATE in tags else "")

        # descriptive tag enrichment -> sub_event / notes
        descriptors: list[str] = []
        if T_THROUGH in tags:
            descriptors.append("through ball")
        if T_INTERCEPTION in tags:
            descriptors.append("interception")
        if T_CLEARANCE in tags:
            descriptors.append("clearance")
        if T_SLIDING_TACKLE in tags:
            descriptors.append("sliding tackle")
        if T_BLOCKED in tags:
            descriptors.append("blocked")
        if T_DANGEROUS_BALL_LOST in tags:
            descriptors.append("dangerous ball lost")
        if T_OPPORTUNITY in tags:
            descriptors.append("opportunity")

        card = _card(tags)
        notes: list[str] = []
        if card:
            notes.append(card)
        notes.extend(descriptors)
        if T_COUNTER_ATTACK in tags:
            notes.append("counter attack")

        sub_event = sub_name or card or (descriptors[0] if descriptors else "")

        assist = T_ASSIST in tags
        key_pass = assist or T_KEY_PASS in tags

        team_raw = str(e.get("teamId", "") or "")
        player_raw = str(e.get("playerId", "") or "")
        team = team_names.get(team_raw, team_raw)
        player = player_names.get(player_raw, player_raw)
        if team_raw and team_raw not in team_names:
            unresolved_teams.add(team_raw)
        if player_raw and player_raw not in player_names:
            unresolved_players.add(player_raw)

        sec = e.get("eventSec")
        return {
            "event_type": event_type,
            "sub_event": sub_event,
            "team": team,
            "player": player,
            "period": _PERIODS.get(str(e.get("matchPeriod", "1H")), 1),
            "timestamp": sec,
            "minute": int(sec // 60) if isinstance(sec, (int, float)) else None,
            "second": (sec % 60) if isinstance(sec, (int, float)) else None,
            "x": _num(start.get("x")), "y": _num(start.get("y")),
            "end_x": _num(end.get("x")), "end_y": _num(end.get("y")),
            "outcome": outcome,
            "shot_result": _shot_result(event_name, tags),
            "body_part": _body_part(tags),
            "set_piece": _set_piece(sub_name),
            "play_pattern": "Counter attack" if T_COUNTER_ATTACK in tags else "",
            "assist": assist,
            "key_pass": key_pass,
            "notes": "; ".join(notes),
            "match_id": str(e.get("matchId", "")),
            "sequence_id": str(e.get("possessionId", "")),
        }
