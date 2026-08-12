"""Structured tactical-insight model — the serializable output contract of the
Tactical Insight Engine (P0).

An :class:`Insight` is a small, JSON-round-trippable value object. It carries the
*measured* observation, the *interpretation*, and a *recommended investigation*
as three clearly separated fields (never conflated), plus transparent evidence,
sample size, confidence and priority. It stores NO DataFrames, figures or raw
event rows — only a bounded list of supporting event ids and a lightweight
``SupportingViz`` descriptor that points back at the existing visualization
system. This keeps insights reusable by Streamlit, reports, dashboards and future
export/AI layers without dragging heavy objects through state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class InsightCategory(str, Enum):
    PROGRESSION = "Progression"
    BUILD_UP = "Build-up"
    FINAL_THIRD = "Final Third"
    RECOVERIES = "Recoveries"
    PLAYERS = "Players"


class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Priority(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


@dataclass(frozen=True)
class Evidence:
    """One measured metric backing an insight (label + display value + optional
    raw numeric for downstream consumers)."""
    label: str
    value: str
    raw: float | None = None

    def to_dict(self) -> dict:
        return {"label": self.label, "value": self.value, "raw": self.raw}


@dataclass(frozen=True)
class SupportingViz:
    """A reference (not a figure) to the existing visualization that shows an
    insight's evidence. The UI maps ``viz_hint`` to a registry chart and applies
    ``event_types`` / ``players`` / ``zone`` through the EXISTING filter engine —
    no second chart or filter system is created.

    ``players`` carries the exact player identity a player-level insight was built
    from, so the supporting evidence is scoped to that player (and only that
    player). It is empty for team-level insights — the evidence then shows the whole
    team. The identity is the canonical ``player`` value (the field the Open Play
    ``players`` filter matches on); a stable player id would be used here instead if
    the canonical event schema carried one."""
    description: str
    viz_hint: str = ""                     # keyword mapped to an existing registry viz
    event_types: tuple[str, ...] = ()      # event-type filter to apply
    players: tuple[str, ...] = ()          # player-scope filter (empty => team-level)
    lane: str | None = None                # "Left Lane" / "Central Lane" / "Right Lane"
    third: str | None = None               # "Defensive Third" / "Middle Third" / "Final Third"

    def to_dict(self) -> dict:
        return {"description": self.description, "viz_hint": self.viz_hint,
                "event_types": list(self.event_types), "players": list(self.players),
                "lane": self.lane, "third": self.third}


@dataclass(frozen=True)
class Insight:
    """A single structured tactical insight. Serializable and free of heavy data."""
    id: str
    category: InsightCategory
    title: str
    short_explanation: str
    observation: str
    interpretation: str
    recommendation: str
    evidence: tuple[Evidence, ...] = ()
    sample_size: int = 0
    confidence: Confidence = Confidence.LOW
    confidence_score: float = 0.0
    priority: Priority = Priority.MEDIUM
    subject: str = ""                       # team / player the insight is about
    event_ids: tuple[str, ...] = ()         # bounded supporting event references
    supporting_viz: SupportingViz | None = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        d["confidence"] = self.confidence.value
        d["priority"] = self.priority.value
        d["evidence"] = [e.to_dict() for e in self.evidence]
        d["event_ids"] = list(self.event_ids)
        d["supporting_viz"] = self.supporting_viz.to_dict() if self.supporting_viz else None
        return d


@dataclass(frozen=True)
class InsightReport:
    """The engine's result: the insights plus a summary and any data-quality
    notices explaining why a family of analysis was unavailable."""
    insights: tuple[Insight, ...] = ()
    notices: tuple[str, ...] = ()           # e.g. "Recovery analysis unavailable: …"
    subject: str = ""
    quality: float = 0.0                    # overall data-quality score (0-100)
    n_events: int = 0
    coverage: dict = field(default_factory=dict)   # capability flags (coords/players/…)

    # ---- summary helpers (used by the UI header) ----
    @property
    def count(self) -> int:
        return len(self.insights)

    @property
    def high_confidence(self) -> int:
        return sum(1 for i in self.insights if i.confidence is Confidence.HIGH)

    @property
    def high_priority(self) -> int:
        return sum(1 for i in self.insights if i.priority is Priority.HIGH)

    def by_category(self) -> dict[str, list[Insight]]:
        out: dict[str, list[Insight]] = {}
        for ins in self.insights:
            out.setdefault(ins.category.value, []).append(ins)
        return out

    def categories(self) -> list[str]:
        # preserve the canonical category order, keeping only those present
        order = [c.value for c in InsightCategory]
        present = {i.category.value for i in self.insights}
        return [c for c in order if c in present]

    def to_dict(self) -> dict:
        return {
            "insights": [i.to_dict() for i in self.insights],
            "notices": list(self.notices),
            "subject": self.subject,
            "quality": self.quality,
            "n_events": self.n_events,
            "coverage": dict(self.coverage),
            "summary": {"count": self.count, "high_confidence": self.high_confidence,
                        "high_priority": self.high_priority, "categories": self.categories()},
        }
