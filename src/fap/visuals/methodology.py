"""Data & Methodology note — honest provenance for every visualization.

Answers one question for whatever is on screen right now: *exactly what data
produced what I am looking at?* The note is generated from the ACTUAL
visualization configuration — dataset, the fields the visualization consumes, the
active analytical filters, the metric/calculation, the coordinate system, the
scope and the missing-data behaviour — never a hardcoded generic blurb. When the
user changes a filter, the note changes.

Pure and system-agnostic: it takes primitives (strings/lists/a FilterSet-or-dict),
so both rendering systems feed it — ``fap.visuals`` plugins and the locked Open
Play engine. No Streamlit, no matplotlib, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --------------------------------------------------------- filter summarisation
# FilterSet field -> how to render an active value as a human chip. Only fields
# that are actually constraining show up; everything at its default reads as "None".
_MULTI_LABELS: tuple[tuple[str, str], ...] = (
    ("competitions", "Competition"), ("seasons", "Season"),
    ("event_types", "Event"), ("phases", "Phase"), ("players", "Player"),
    ("outcomes", "Outcome"), ("body_parts", "Body part"),
    ("play_patterns", "Play pattern"), ("set_pieces", "Set piece"),
    ("positions", "Position"), ("score_states", "Score state"),
    ("venues", "Venue"), ("periods", "Period"),
)


def _as_dict(filters: Any) -> dict[str, Any]:
    if filters is None:
        return {}
    if isinstance(filters, dict):
        return dict(filters)
    to_dict = getattr(filters, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return {}


def filter_labels(filters: Any) -> list[str]:
    """Human-readable chips for the *active* constraints in a FilterSet (or its
    dict form). Returns ``[]`` when nothing is constraining — the caller renders
    that as 'None'."""
    data = _as_dict(filters)
    if not data:
        return []
    out: list[str] = []
    for key, single in (("team", "Team"), ("opponent", "Opponent"), ("match_id", "Match")):
        val = data.get(key)
        if val and str(val) != "All":
            out.append(f"{single}: {val}")
    for key, label in _MULTI_LABELS:
        vals = data.get(key) or []
        vals = [str(v) for v in vals if str(v).strip()]
        if vals:
            out.append(f"{label}: " + ", ".join(vals))
    mr = data.get("minute_range")
    if mr and (float(mr[0]) > 0 or float(mr[1]) < 120):
        out.append(f"Minutes: {float(mr[0]):g}–{float(mr[1]):g}")
    ps = data.get("pressure_state")
    if ps and ps != "any":
        out.append("Under pressure" if ps == "under_pressure" else "No pressure")
    if data.get("only_successful"):
        out.append("Only successful")
    for col, op, value in (data.get("custom") or []):
        out.append(f"{col} {op} {value}")
    return out


# ---------------------------------------------------------------- coordinate note
def coordinate_note(pitch_based: bool, *, length: float | None = None,
                    width: float | None = None, spec_label: str = "") -> str:
    """Describe the coordinate system the *rendered* visualization uses. The platform
    normalizes every provider into a canonical 0–100 x 0–100 model, then maps it
    onto the selected pitch standard for display."""
    if not pitch_based:
        return "n/a (non-spatial chart)"
    base = "canonical 0–100 × 0–100 normalized model"
    if length and width:
        return f"{base} · rendered on {length:g} × {width:g}" + (
            f" ({spec_label})" if spec_label else "")
    if spec_label:
        return f"{base} · rendered on {spec_label}"
    return base


@dataclass(frozen=True, slots=True)
class MethodologyNote:
    """Structured provenance for one rendered visualization."""
    dataset: str
    fields: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)
    metric: str = ""
    coordinates: str = ""
    scope: str = ""
    missing: str = ""
    population: str = ""            # reference/benchmark population (percentile charts)

    def rows(self) -> list[tuple[str, str]]:
        """(label, value) rows for rendering, omitting empty sections but always
        stating dataset, fields and filters (the transparency core)."""
        out: list[tuple[str, str]] = [
            ("Dataset", self.dataset or "—"),
            ("Fields", ", ".join(self.fields) if self.fields else "—"),
            ("Filters", ", ".join(self.filters) if self.filters else "None"),
        ]
        if self.metric:
            out.append(("Metric", self.metric))
        if self.population:
            out.append(("Reference", self.population))
        if self.coordinates:
            out.append(("Coordinates", self.coordinates))
        if self.scope:
            out.append(("Scope", self.scope))
        if self.missing:
            out.append(("Missing data", self.missing))
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"dataset": self.dataset, "fields": list(self.fields),
                "filters": list(self.filters), "metric": self.metric,
                "coordinates": self.coordinates, "scope": self.scope,
                "missing": self.missing, "population": self.population}


def build_note(*, dataset: str, fields: list[str] | None = None, filters: Any = None,
               metric: str = "", pitch_based: bool = False,
               length: float | None = None, width: float | None = None,
               spec_label: str = "", scope: str = "", missing: str = "",
               population: str = "") -> MethodologyNote:
    """Assemble a note from primitives. ``filters`` may be a FilterSet, its dict, a
    list of already-computed chips, or None. Missing-data behaviour defaults to the
    honest spatial rule for pitch visualizations."""
    if isinstance(filters, list):
        chips = [str(c) for c in filters]
    else:
        chips = filter_labels(filters)
    if not missing and pitch_based:
        missing = "rows with missing/invalid x/y are excluded from spatial rendering"
    return MethodologyNote(
        dataset=dataset, fields=list(fields or []), filters=chips, metric=metric,
        coordinates=coordinate_note(pitch_based, length=length, width=width,
                                    spec_label=spec_label),
        scope=scope, missing=missing, population=population)


__all__ = ["MethodologyNote", "build_note", "filter_labels", "coordinate_note"]
