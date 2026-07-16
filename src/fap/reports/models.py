"""Report models - pure data, no rendering and no calculation.

A ReportDocument is an ordered set of Sections plus a Cover. Builders produce
these; renderers/exporters consume them. Everything is JSON-serializable so a
report round-trips through the database and survives schema upgrades.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class KPI:
    label: str
    value: str
    delta: str = ""
    direction: str = ""            # up | down | ""


@dataclass(slots=True)
class Table:
    title: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)


@dataclass(slots=True)
class Insight:
    text: str
    kind: str = "neutral"          # neutral | success | warning | danger


@dataclass(slots=True)
class Chart:
    """A reference to a registered visualization - NOT a drawn chart. The
    builder may attach a pre-rendered image (base64 PNG) so exporters embed
    without ever touching the visualization engine."""
    viz_id: str
    title: str = ""
    controls: dict[str, Any] = field(default_factory=dict)
    image_b64: str = ""            # optional pre-rendered PNG (data payload only)


@dataclass(slots=True)
class Section:
    id: str
    title: str
    subtitle: str = ""
    kpis: list[KPI] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    notes: str = ""
    markdown: str = ""


@dataclass(slots=True)
class Cover:
    title: str = "Report"
    subtitle: str = ""
    club: str = ""
    organization: str = ""
    competition: str = ""
    season: str = ""
    opponent: str = ""
    match_date: str = ""
    analyst: str = ""
    generated_at: str = ""
    version: str = "1.0"
    template_id: str = ""
    club_logo: str = ""
    organization_logo: str = ""


@dataclass(slots=True)
class ReportDocument:
    id: str
    title: str
    template_id: str = ""
    cover: Cover = field(default_factory=Cover)
    sections: list[Section] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    # -- serialization (JSON round-trip for persistence) --------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportDocument":
        cover = Cover(**data.get("cover", {}))
        sections = [
            Section(
                id=s["id"], title=s["title"], subtitle=s.get("subtitle", ""),
                kpis=[KPI(**k) for k in s.get("kpis", [])],
                tables=[Table(**t) for t in s.get("tables", [])],
                insights=[Insight(**i) for i in s.get("insights", [])],
                charts=[Chart(**c) for c in s.get("charts", [])],
                notes=s.get("notes", ""), markdown=s.get("markdown", ""))
            for s in data.get("sections", [])
        ]
        return cls(id=data["id"], title=data["title"],
                   template_id=data.get("template_id", ""), cover=cover,
                   sections=sections, meta=data.get("meta", {}))


@dataclass(slots=True)
class ReportRecord:
    """Persistence row: a stored report and its workspace/ownership metadata."""
    id: str
    title: str
    workspace_id: str | None = None
    project_id: str | None = None
    dataset_id: str | None = None
    template_id: str = ""
    owner: str = ""
    contributors: list[str] = field(default_factory=list)
    status: str = "active"                 # active | archived | draft
    favorite: bool = False
    version: int = 1
    document: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
