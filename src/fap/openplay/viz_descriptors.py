"""Per-visualization descriptors for the LOCKED Open Play engine.

The Open Play engine (``app.py``) exposes each visualization only as
``{name -> {"category", "render", "uses_pitch"}}`` — it does not declare which
canonical fields a chart consumes, nor which presentation toggles it supports. This
module adds that knowledge WITHOUT touching the engine: it derives, from the
visualization's category and name, (a) the canonical fields the visualization relies
on — for an honest Data & Methodology note — and (b) the display capabilities the
engine can actually honour through its existing ctx (legend, labels, player labels,
cell counts). Nothing here changes rendering; it is descriptive metadata + the
note assembly for the Open Play UI.

Pure: no Streamlit, no matplotlib, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass

from fap.visuals.display import VisualizationCapabilities
from fap.visuals.methodology import MethodologyNote, build_note

# keyword groups over the (name + category) text, lower-cased
_PASSING = ("pass", "cross", "switch", "throughball", "through ball", "assist",
            "delivery", "distribution", "launch")
_CARRY = ("carry", "dribble", "progress", "ball carr", "take on", "take-on")
_SHOT = ("shot", "xg", "goal", "finish", "chance", "conversion")
_DENSITY = ("heat", "density", "kde", "territory", "influence", "coverage")
_ZONE = ("zone", "third", "channel", "lane", "grid", "flank", "half-space", "halfspace")
_DEFENSIVE = ("tackle", "interception", "block", "clearance", "recovery", "duel",
              "pressure", "defensive action")
_GK = ("goalkeeper", "keeper", "save", "gk ")


def _text(name: str, category: str) -> str:
    return f"{name} {category}".lower()


@dataclass(frozen=True, slots=True)
class VizDescriptor:
    """What an Open Play visualization uses and can display."""
    name: str
    category: str
    pitch_based: bool
    fields: list[str]
    capabilities: VisualizationCapabilities
    metric: str

    def uses_end_coords(self) -> bool:
        return "end_x" in self.fields


def describe(name: str, category: str = "", uses_pitch: bool = True) -> VizDescriptor:
    """Derive a descriptor for one Open Play visualization from its name + category.

    Fields are the canonical columns the visualization's family relies on (honest
    at the family level); capabilities are limited to what the engine's ctx can
    actually toggle, so the UI never offers a control the locked engine can't honour.
    """
    text = _text(name, category)
    has = lambda group: any(k in text for k in group)  # noqa: E731

    if not uses_pitch:
        # non-spatial chart: the engine honours legend visibility (legend.show)
        fields = ["event_type", "outcome"]
        if has(_SHOT):
            fields = ["event_type", "outcome", "xg"]
        caps = VisualizationCapabilities(legend=True, annotations=False)
        return VizDescriptor(name, category, False, fields, caps, name)

    # spatial map: base canonical coordinates
    fields = ["event_type", "x", "y"]
    is_density = has(_DENSITY)
    is_zone = has(_ZONE)
    if has(_PASSING) or has(_CARRY):
        fields += ["end_x", "end_y", "outcome"]
    if has(_SHOT):
        for c in ("xg", "outcome"):
            if c not in fields:
                fields.append(c)
    if (has(_DEFENSIVE) or has(_GK)) and "outcome" not in fields:
        fields.append("outcome")

    # engine-honourable presentation toggles for a pitch map:
    #   legend.show, labels.show (event labels), labels.show_players (player names),
    #   and heat cell counts for density/zone maps.
    caps = VisualizationCapabilities(
        legend=True,
        labels=True,
        player_names=True,
        event_counts=is_density or is_zone,
        annotations=False,
    )
    return VizDescriptor(name, category, True, fields, caps, name)


def openplay_note(descriptor: VizDescriptor, *, dataset: str, filters: object = None,
                  scope: str = "", length: float | None = None,
                  width: float | None = None, spec_label: str = "") -> MethodologyNote:
    """Assemble the Data & Methodology note for an Open Play visualization from its
    descriptor + the live Studio state (filters/scope/pitch spec)."""
    return build_note(
        dataset=dataset or "events", fields=descriptor.fields, filters=filters,
        metric=descriptor.metric, pitch_based=descriptor.pitch_based,
        length=length, width=width, spec_label=spec_label, scope=scope)


def normalize_openplay_selections(selections: dict) -> dict:
    """Map Open Play filter selection ids (``match``/``only_success``/…) onto the
    canonical FilterSet keys the methodology note understands, so active Open Play
    filters render as chips without duplicating the summariser."""
    sel = selections or {}
    return {
        "team": sel.get("team"),
        "opponent": sel.get("opponent"),
        "match_id": sel.get("match"),
        "event_types": sel.get("event_types") or [],
        "phases": sel.get("phases") or [],
        "players": sel.get("players") or [],
        "minute_range": sel.get("minute_range", (0, 120)),
        "only_successful": bool(sel.get("only_success")),
    }


def scope_from_selections(selections: dict) -> str:
    """Human scope label from Open Play filter selections (player > match > team)."""
    sel = selections or {}
    players = [p for p in (sel.get("players") or []) if str(p).strip()]
    if len(players) == 1:
        return f"Player · {players[0]}"
    if players:
        return f"Players · {len(players)} selected"
    if sel.get("match") and sel["match"] != "All":
        return f"Match · {sel['match']}"
    if sel.get("team") and sel["team"] != "All":
        return f"Team · {sel['team']}"
    return "All events"


__all__ = ["VizDescriptor", "describe", "openplay_note", "scope_from_selections",
           "normalize_openplay_selections"]
