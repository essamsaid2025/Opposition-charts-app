"""Team match-stats semantic schema + analyzer.

When the classifier decides a file is a *team-comparison stat table* — rows are
statistics, columns are the teams being compared (e.g. a match "Team Stats"
export: Category, Statistic, FC MASAR, ABU QIR) — this module reads its meaning:
which column names the statistic, which optional column groups them into
categories, which columns are the teams, and each statistic's value per team and
its unit (percent vs count). It is the team-stats counterpart of the event
pipeline and the player-scouting analyzer — pure (pandas only), deterministic,
and it never runs the event pipeline or fabricates coordinates.

The output (``TeamStatsAnalysis``) is what the Data Hub renders and what it
persists as the dataset's semantic schema, so Open Play can later discover the
dataset and draw dedicated comparison charts without re-inferring anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fap.datahub.classification import (
    DatasetClassification, TEAM_MATCH_STATS, _STAT_CATEGORY_KEYS, _STAT_LABEL_KEYS,
    classify_frame, is_index_artifact, normalize_key, to_number,
)
from fap.datahub.scouting_schema import QualityCheck

# ---------------------------------------------------------------- stat units
PERCENT = "percent"
COUNT = "count"


def classify_stat_unit(raw_values: list[str]) -> str:
    """A statistic is a percentage when its displayed values carry a ``%`` sign;
    otherwise it is a plain count/number. Inferred from the cells the file shows,
    never from the statistic's name."""
    for v in raw_values:
        if "%" in str(v):
            return PERCENT
    return COUNT


@dataclass(frozen=True, slots=True)
class TeamStat:
    """One statistic row: its label, optional category, unit, and value per team.

    ``values`` holds the numeric value per team (percent kept at face value, e.g.
    56 for "56%"); ``raw`` keeps the original displayed cell so the UI can show
    "56%" verbatim."""
    name: str
    category: str
    unit: str
    values: dict[str, float]
    raw: dict[str, str]

    def value(self, team: str) -> float | None:
        return self.values.get(team)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "category": self.category, "unit": self.unit,
                "values": dict(self.values), "raw": dict(self.raw)}


@dataclass(frozen=True, slots=True)
class TeamStatsSchema:
    """The semantic contract of a team-comparison table. Serializable so it can
    live inside ``dataset.document`` and be read back by Open Play."""
    entity_type: str = "team_stat"
    stat_field: str = ""                       # source column holding stat labels
    category_field: str = ""                   # source column grouping stats ("")
    teams: list[str] = field(default_factory=list)     # team value columns
    stats: list[TeamStat] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "stat_field": self.stat_field,
            "category_field": self.category_field,
            "teams": list(self.teams),
            "stats": [s.to_dict() for s in self.stats],
            "categories": list(self.categories),
            "ignored": list(self.ignored),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TeamStatsSchema":
        stats = [
            TeamStat(
                name=str(s.get("name", "")), category=str(s.get("category", "")),
                unit=str(s.get("unit", COUNT)),
                values={str(k): float(v) for k, v in (s.get("values") or {}).items()
                        if v is not None},
                raw={str(k): str(v) for k, v in (s.get("raw") or {}).items()})
            for s in (data.get("stats") or [])
        ]
        return TeamStatsSchema(
            entity_type=str(data.get("entity_type", "team_stat")),
            stat_field=str(data.get("stat_field", "")),
            category_field=str(data.get("category_field", "")),
            teams=[str(t) for t in (data.get("teams") or [])],
            stats=stats,
            categories=[str(c) for c in (data.get("categories") or [])],
            ignored=[str(c) for c in (data.get("ignored") or [])])


@dataclass(frozen=True, slots=True)
class TeamStatsQuality:
    checks: list[QualityCheck] = field(default_factory=list)

    @property
    def grade(self) -> str:
        statuses = {c.status for c in self.checks}
        if "fail" in statuses:
            return "Poor"
        if "warn" in statuses:
            return "Fair"
        return "Good"

    def to_dict(self) -> dict[str, Any]:
        return {"grade": self.grade, "checks": [c.to_dict() for c in self.checks]}


@dataclass(frozen=True, slots=True)
class TeamStatsAnalysis:
    """The full result the wizard renders and the service persists."""
    classification: DatasetClassification
    schema: TeamStatsSchema
    quality: TeamStatsQuality
    competition: str = ""
    frame: pd.DataFrame | None = None

    @property
    def dataset_type(self) -> str:
        return self.classification.dataset_type

    @property
    def team_count(self) -> int:
        return len(self.schema.teams)

    @property
    def stat_count(self) -> int:
        return len(self.schema.stats)

    @property
    def category_count(self) -> int:
        return len(self.schema.categories)

    @property
    def teams(self) -> list[str]:
        return list(self.schema.teams)

    def summary(self) -> dict[str, Any]:
        return {
            "dataset_type": self.dataset_type,
            "entity_type": self.schema.entity_type,
            "teams": list(self.schema.teams),
            "team_count": self.team_count,
            "stat_count": self.stat_count,
            "category_count": self.category_count,
            "categories": list(self.schema.categories),
            "competition": self.competition,
            "confidence": round(self.classification.confidence, 3),
            "grade": self.quality.grade,
        }


# ---------------------------------------------------------------- analysis
def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop trailing all-empty rows and pure index/empty columns — the only
    structural cleanup; values are never altered."""
    df = frame.dropna(how="all").copy()
    drop = [c for c in df.columns if is_index_artifact(c) or df[c].dropna().empty]
    if drop:
        df = df.drop(columns=drop)
    return df


def _find(frame: pd.DataFrame, keys: frozenset[str]) -> str | None:
    for col in frame.columns:
        if normalize_key(col) in keys:
            return col
    return None


def _team_columns(frame: pd.DataFrame, skip: set) -> list[str]:
    cols: list[str] = []
    for c in frame.columns:
        if c in skip or is_index_artifact(c):
            continue
        if float(to_number(frame[c]).notna().mean()) >= 0.6:
            cols.append(c)
    return cols


def _build_stats(frame: pd.DataFrame, stat_col: str, cat_col: str | None,
                 teams: list[str]) -> tuple[list[TeamStat], list[str]]:
    numeric = {t: to_number(frame[t]) for t in teams}
    stats: list[TeamStat] = []
    categories: list[str] = []
    for i in range(len(frame)):
        name = str(frame.iloc[i][stat_col]).strip()
        if not name or name.lower() == "nan":
            continue
        category = ""
        if cat_col is not None:
            cv = str(frame.iloc[i][cat_col]).strip()
            category = "" if cv.lower() == "nan" else cv
        if category and category not in categories:
            categories.append(category)
        raw = {t: ("" if pd.isna(frame.iloc[i][t]) else str(frame.iloc[i][t]).strip())
               for t in teams}
        values = {t: float(numeric[t].iloc[i]) for t in teams
                  if not pd.isna(numeric[t].iloc[i])}
        unit = classify_stat_unit(list(raw.values()))
        stats.append(TeamStat(name=name, category=category, unit=unit,
                              values=values, raw=raw))
    return stats, categories


def _quality(schema: TeamStatsSchema) -> TeamStatsQuality:
    checks: list[QualityCheck] = []
    n_teams = len(schema.teams)
    checks.append(QualityCheck(
        "teams", "Teams compared", "pass" if n_teams >= 2 else "fail",
        ", ".join(schema.teams) if schema.teams else "no team value columns found"))
    checks.append(QualityCheck(
        "stats", "Statistics", "pass" if schema.stats else "fail",
        f"{len(schema.stats)} statistic(s) detected" if schema.stats
        else "no statistic rows detected"))
    # duplicate (category, statistic) rows
    seen: set[tuple[str, str]] = set()
    dupes = 0
    for s in schema.stats:
        key = (s.category, s.name)
        if key in seen:
            dupes += 1
        seen.add(key)
    checks.append(QualityCheck(
        "duplicates", "Unique statistics", "warn" if dupes else "pass",
        f"{dupes} duplicate statistic row(s)" if dupes else "all statistics unique"))
    # completeness: any team missing a value on a row
    missing = sum(1 for s in schema.stats if len(s.values) < n_teams)
    checks.append(QualityCheck(
        "missing", "Value completeness", "warn" if missing else "pass",
        f"{missing} statistic(s) missing a team value" if missing
        else "every statistic has a value for each team"))
    if schema.categories:
        checks.append(QualityCheck(
            "categories", "Categories", "pass",
            f"{len(schema.categories)} category group(s): "
            + ", ".join(schema.categories)))
    return TeamStatsQuality(checks=checks)


def analyze_team_stats(frame: pd.DataFrame,
                       classification: DatasetClassification | None = None
                       ) -> TeamStatsAnalysis:
    """Read a team-comparison stat table into a semantic schema + quality report.

    Team-count agnostic: a two-team match export and a multi-team league table go
    through the same path, differing only in how many team columns are found."""
    cls = classification or classify_frame(frame)
    original_cols = list(frame.columns)
    df = _clean_frame(frame)
    ignored = [str(c) for c in original_cols if c not in df.columns]

    stat_col = _find(df, _STAT_LABEL_KEYS)
    cat_col = _find(df, _STAT_CATEGORY_KEYS)
    teams: list[str] = []
    stats: list[TeamStat] = []
    categories: list[str] = []
    if stat_col is not None:
        teams = _team_columns(df, {stat_col, cat_col})
        if teams:
            stats, categories = _build_stats(df, stat_col, cat_col, teams)

    schema = TeamStatsSchema(
        entity_type="team_stat", stat_field=str(stat_col or ""),
        category_field=str(cat_col or ""), teams=teams, stats=stats,
        categories=categories, ignored=ignored)
    quality = _quality(schema)
    return TeamStatsAnalysis(classification=cls, schema=schema, quality=quality,
                             competition="", frame=df)


__all__ = [
    "PERCENT", "COUNT", "classify_stat_unit", "TeamStat", "TeamStatsSchema",
    "TeamStatsQuality", "TeamStatsAnalysis", "analyze_team_stats",
]
