"""Report templates - an ordered list of section ids plus cover defaults.

A template is a plugin, so adding one is a class + a registration; custom
templates can also be built at runtime from a mapping (editable templates).
The builder resolves the section ids against the section-builder registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from fap.core.plugin import Plugin, PluginInfo, PluginRegistry


class ReportTemplate(Plugin):
    """Base template. Subclasses set ``info`` and ``section_ids``."""
    section_ids: tuple[str, ...] = ()
    subtitle: str = ""

    def cover_defaults(self) -> dict[str, Any]:
        return {}


template_registry: PluginRegistry[ReportTemplate] = PluginRegistry("report_template")


@dataclass(slots=True)
class CustomTemplate:
    """A runtime, editable template (not a plugin) - e.g. loaded from the DB or
    built in the UI. Duck-compatible with ReportTemplate where the builder needs
    ``info.id``/``section_ids``/``subtitle``."""
    id: str
    name: str
    section_ids: tuple[str, ...]
    subtitle: str = ""
    cover: dict[str, Any] = field(default_factory=dict)

    class _Info:
        def __init__(self, id: str, name: str) -> None:
            self.id, self.name = id, name

    @property
    def info(self):
        return CustomTemplate._Info(self.id, self.name)

    def cover_defaults(self) -> dict[str, Any]:
        return dict(self.cover)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "CustomTemplate":
        return cls(id=str(data["id"]), name=str(data.get("name", data["id"])),
                   section_ids=tuple(data.get("section_ids", [])),
                   subtitle=str(data.get("subtitle", "")), cover=dict(data.get("cover", {})))


# ---------------------------------------------------------------- built-in templates
_FULL = ("executive_summary", "tactical_summary", "open_play", "possession",
         "passing", "build_up", "final_third", "chance_creation", "shooting",
         "defensive", "pressing", "set_pieces", "key_players", "team_statistics",
         "notes", "appendix")


@template_registry.register
class OpponentReport(ReportTemplate):
    info = PluginInfo(id="opponent_report", name="Opponent Report", category="template")
    subtitle = "Pre-match opposition analysis"
    section_ids = _FULL


@template_registry.register
class MatchReport(ReportTemplate):
    info = PluginInfo(id="match_report", name="Match Report", category="template")
    subtitle = "Post-match review"
    section_ids = ("executive_summary", "open_play", "possession", "passing",
                   "final_third", "chance_creation", "shooting", "defensive",
                   "set_pieces", "team_statistics", "notes")


@template_registry.register
class ScoutReport(ReportTemplate):
    info = PluginInfo(id="scout_report", name="Scout Report", category="template")
    subtitle = "Opposition scouting"
    section_ids = ("executive_summary", "tactical_summary", "build_up",
                   "final_third", "chance_creation", "set_pieces", "key_players",
                   "notes", "appendix")


@template_registry.register
class PlayerReport(ReportTemplate):
    info = PluginInfo(id="player_report", name="Player Report", category="template")
    subtitle = "Individual player analysis"
    section_ids = ("executive_summary", "key_players", "passing", "chance_creation",
                   "shooting", "team_statistics", "notes")


@template_registry.register
class TournamentReport(ReportTemplate):
    info = PluginInfo(id="tournament_report", name="Tournament Report", category="template")
    subtitle = "Competition-wide overview"
    section_ids = ("executive_summary", "team_statistics", "open_play", "shooting",
                   "defensive", "set_pieces", "appendix")


@template_registry.register
class WeeklyReport(ReportTemplate):
    info = PluginInfo(id="weekly_report", name="Weekly Report", category="template")
    subtitle = "Weekly performance digest"
    section_ids = ("executive_summary", "open_play", "chance_creation", "defensive",
                   "team_statistics", "notes")


@template_registry.register
class AcademyReport(ReportTemplate):
    info = PluginInfo(id="academy_report", name="Academy Report", category="template")
    subtitle = "Academy development analysis"
    section_ids = ("executive_summary", "build_up", "passing", "key_players",
                   "team_statistics", "notes", "appendix")


@template_registry.register
class TrainingReport(ReportTemplate):
    info = PluginInfo(id="training_report", name="Training Report", category="template")
    subtitle = "Training session analysis"
    section_ids = ("executive_summary", "possession", "passing", "pressing",
                   "team_statistics", "notes")
