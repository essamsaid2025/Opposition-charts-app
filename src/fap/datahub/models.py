"""Data Hub domain models — the concepts the Data Hub *adds* on top of the
existing platform (source catalog, lineage, versioning, import profiles, health,
compatibility). It deliberately does NOT redefine ``Dataset`` — that lives in
``fap.workspaces.models`` and is reused unchanged; the Data Hub stores all of its
extra metadata inside the dataset's existing ``document`` JSON namespace.

Pure data only — no Streamlit, no pandas logic, no duplication of pipeline code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# ---------------------------------------------------------------- source catalog
@dataclass(frozen=True, slots=True)
class SourceKind:
    """A supported import source shown in the wizard's upload step. ``provider_id``
    links to an existing provider plugin when one applies (detection still runs
    automatically); ``available`` is False for roadmap sources with no wired
    provider yet, so the UI never claims a format works when it does not."""
    id: str
    label: str
    formats: tuple[str, ...]
    provider_id: str = ""
    available: bool = True
    note: str = ""


# The catalog is display metadata; the actual provider is resolved by the
# ImportService's content detection, never hard-coded here.
SUPPORTED_SOURCES: tuple[SourceKind, ...] = (
    SourceKind("auto", "Auto-detect", ("csv", "xlsx", "xls", "json", "xml", "parquet"),
               note="Recommended — detects the provider from the file's content."),
    SourceKind("csv", "CSV", ("csv",), provider_id="csv"),
    SourceKind("excel", "Excel", ("xlsx", "xls"), provider_id="excel"),
    SourceKind("json", "JSON", ("json",), provider_id="json"),
    SourceKind("xml", "XML (Opta F24 / Sportscode)", ("xml",)),
    SourceKind("statsbomb", "StatsBomb", ("json",), provider_id="statsbomb"),
    SourceKind("opta", "Opta", ("xml", "json"), provider_id="opta_f24"),
    SourceKind("wyscout", "WyScout", ("json",), provider_id="wyscout"),
    SourceKind("skillcorner", "SkillCorner", ("json",), provider_id="skillcorner"),
    SourceKind("secondspectrum", "Second Spectrum", ("json", "jsonl"), provider_id="second_spectrum"),
    SourceKind("metrica", "Metrica", ("csv",), provider_id="metrica"),
    SourceKind("tracab", "Tracab", ("csv",), provider_id="tracab"),
    SourceKind("manual", "Manual CSV", ("csv",), provider_id="manual"),
    SourceKind("parquet", "Parquet", ("parquet",), available=False,
               note="Native re-import of a stored dataset frame — roadmap."),
    SourceKind("gps", "GPS", ("csv",), available=False,
               note="GPS/physical feeds — roadmap; import as CSV with a GPS profile for now."),
    SourceKind("api", "API import", (), available=False, note="Future provider APIs — roadmap."),
)


# ---------------------------------------------------------------- lineage
# The ordered stages every dataset passes through; tracked as append-only events
# in document["datahub"]["lineage"].
LINEAGE_STAGES: tuple[str, ...] = (
    "imported", "validated", "cleaned", "mapped", "normalized", "saved",
    "edited", "used_by",
)


@dataclass(frozen=True, slots=True)
class LineageEvent:
    stage: str
    at: str = ""
    by: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- versioning
@dataclass(frozen=True, slots=True)
class DatasetVersion:
    version: int
    at: str = ""
    by: str = ""
    note: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)   # snapshot of row + document

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- import profiles
@dataclass(frozen=True, slots=True)
class ImportProfile:
    """A reusable set of import rules for a provider/source. Persisted as a
    platform preset (kind='datahub_profile') via the WorkspaceManager — no new
    storage. Rules delegate to the existing pipeline; a profile only *remembers*
    choices (column aliases, coordinate system, cleaning toggles)."""
    id: str
    name: str
    provider_id: str = ""
    mapping: dict[str, str] = field(default_factory=dict)          # source -> canonical
    coord_system: str = ""
    validation: dict[str, Any] = field(default_factory=dict)
    cleaning: dict[str, Any] = field(default_factory=dict)
    normalization: dict[str, Any] = field(default_factory=dict)
    builtin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- health
@dataclass(frozen=True, slots=True)
class HealthAxis:
    key: str
    label: str
    status: str            # "green" | "yellow" | "red"
    coverage: float = 0.0  # 0..1 where meaningful
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DatasetHealth:
    axes: list[HealthAxis] = field(default_factory=list)

    @property
    def overall(self) -> str:
        statuses = {a.status for a in self.axes}
        if "red" in statuses and any(a.status == "red" and a.key in ("coordinates", "events")
                                     for a in self.axes):
            return "red"
        if "red" in statuses or "yellow" in statuses:
            return "yellow"
        return "green"

    def to_dict(self) -> dict[str, Any]:
        return {"overall": self.overall, "axes": [a.to_dict() for a in self.axes]}


# ---------------------------------------------------------------- compatibility
@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    module: str
    ready: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# modules the Data Hub feeds; the compatibility scanner reports READY per module
TARGET_MODULES: tuple[str, ...] = (
    "Open Play", "Set Pieces", "Players", "Scouting", "Reports", "Tracking",
)
