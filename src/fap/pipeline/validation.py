"""Validation engine. Each check is a ValidationRule plugin so club-specific
rules can be added by dropping in a module - the engine and report never change."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field

import pandas as pd

from fap.core.plugin import Plugin, PluginInfo, PluginRegistry
from fap.pipeline import schema

KNOWN_EVENTS: frozenset[str] = frozenset({
    "pass", "carry", "cross", "dribble", "shot", "duel", "recovery", "interception",
    "clearance", "tackle", "block", "save", "foul", "throw-in", "corner", "free_kick",
    "goal_kick", "offside", "pressure", "goalkeeper", "substitution", "own_goal",
})

KEY_COLUMNS = ("event_type", "x", "y", "team", "player", "minute", "match_id")


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    severity: str                 # "error" | "warning" | "info"
    message: str
    count: int = 0
    examples: tuple[str, ...] = ()


@dataclass(slots=True)
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    rows_checked: int = 0

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_markdown(self) -> str:
        if not self.issues:
            return f"**Validation passed** - {self.rows_checked:,} rows, no issues found."
        lines = [f"**Validation report** - {self.rows_checked:,} rows checked, "
                 f"{len(self.errors)} error(s), {len(self.warnings)} warning(s).", ""]
        icon = {"error": "🔴", "warning": "🟠", "info": "🔵"}
        for i in self.issues:
            suffix = f" (examples: {', '.join(i.examples)})" if i.examples else ""
            lines.append(f"- {icon.get(i.severity, '')} `{i.code}` - {i.message}{suffix}")
        return "\n".join(lines)


class ValidationRule(Plugin):
    @abstractmethod
    def check(self, df: pd.DataFrame) -> list[Issue]: ...


validation_registry: PluginRegistry[ValidationRule] = PluginRegistry("validation_rule")


class ValidationEngine:
    def __init__(self, registry: PluginRegistry[ValidationRule] = validation_registry) -> None:
        self._registry = registry

    def run(self, df: pd.DataFrame) -> ValidationReport:
        report = ValidationReport(rows_checked=len(df))
        for rule_cls in self._registry:
            report.issues.extend(rule_cls().check(df))
        report.issues.sort(key=lambda i: {"error": 0, "warning": 1, "info": 2}[i.severity])
        return report


# ------------------------------------------------------------------ rules
@validation_registry.register
class MissingRequiredColumns(ValidationRule):
    info = PluginInfo(id="missing_columns", name="Missing required columns", category="validation")

    def check(self, df: pd.DataFrame) -> list[Issue]:
        missing = [c for c in schema.REQUIRED if c not in df.columns]
        return [Issue("missing_columns", "error",
                      f"Missing required columns: {', '.join(missing)}")] if missing else []


@validation_registry.register
class DuplicateRows(ValidationRule):
    info = PluginInfo(id="duplicate_rows", name="Duplicate rows", category="validation")

    def check(self, df: pd.DataFrame) -> list[Issue]:
        n = int(df.duplicated().sum())
        return [Issue("duplicate_rows", "warning",
                      f"{n} exact duplicate rows detected (auto-removed by cleaning)", n)] if n else []


@validation_registry.register
class InvalidCoordinates(ValidationRule):
    info = PluginInfo(id="invalid_coordinates", name="Invalid coordinates", category="validation")

    def check(self, df: pd.DataFrame) -> list[Issue]:
        issues: list[Issue] = []
        miss = int(df["x"].isna().sum() + df["y"].isna().sum())
        if miss:
            issues.append(Issue("missing_coordinates", "warning",
                                f"{miss} missing start coordinate values", miss))
        out = int(((df["x"] < 0) | (df["x"] > 100) | (df["y"] < 0) | (df["y"] > 100)).sum())
        if out:
            issues.append(Issue("coordinates_out_of_range", "error",
                                f"{out} rows have coordinates outside the 0-100 canonical pitch", out))
        return issues


@validation_registry.register
class ImpossibleValues(ValidationRule):
    info = PluginInfo(id="impossible_values", name="Impossible values", category="validation")

    def check(self, df: pd.DataFrame) -> list[Issue]:
        issues: list[Issue] = []
        bad_min = int(((df["minute"] < 0) | (df["minute"] > 135)).sum())
        if bad_min:
            issues.append(Issue("impossible_minute", "error",
                                f"{bad_min} rows with minute outside 0-135", bad_min))
        bad_xg = int(((df["shot_xg"] < 0) | (df["shot_xg"] > 1)).sum())
        if bad_xg:
            issues.append(Issue("impossible_xg", "error",
                                f"{bad_xg} rows with xG outside 0-1", bad_xg))
        neg = int(((df["pass_length"] < 0) | (df["carry_distance"] < 0)).sum())
        if neg:
            issues.append(Issue("negative_distance", "error",
                                f"{neg} rows with negative pass/carry distance", neg))
        return issues


@validation_registry.register
class InvalidPeriods(ValidationRule):
    info = PluginInfo(id="invalid_periods", name="Invalid periods", category="validation")

    def check(self, df: pd.DataFrame) -> list[Issue]:
        bad = int((~df["period"].isin([1, 2, 3, 4, 5])).sum())
        return [Issue("invalid_period", "error",
                      f"{bad} rows with period outside 1-5", bad)] if bad else []


@validation_registry.register
class UnknownEventNames(ValidationRule):
    info = PluginInfo(id="unknown_events", name="Unknown event names", category="validation")

    def check(self, df: pd.DataFrame) -> list[Issue]:
        names = df["event_type"].str.lower().str.strip()
        unknown = sorted(set(names[names != ""]) - KNOWN_EVENTS)
        if not unknown:
            return []
        n = int(names.isin(unknown).sum())
        return [Issue("unknown_events", "info",
                      f"{len(unknown)} event names outside the known vocabulary "
                      f"({n} rows) - they are kept as-is", n, tuple(unknown[:6]))]


@validation_registry.register
class MissingTimestamps(ValidationRule):
    info = PluginInfo(id="missing_timestamps", name="Missing timestamps", category="validation")

    def check(self, df: pd.DataFrame) -> list[Issue]:
        no_time = int((df["minute"].isna() & df["timestamp"].isna()).sum())
        return [Issue("missing_timestamps", "warning",
                      f"{no_time} rows have neither minute nor timestamp", no_time)] if no_time else []


@validation_registry.register
class NullPercentages(ValidationRule):
    info = PluginInfo(id="null_percentages", name="High null percentages", category="validation")

    def check(self, df: pd.DataFrame) -> list[Issue]:
        if df.empty:
            return []
        issues: list[Issue] = []
        for col in KEY_COLUMNS:
            if col not in df.columns:
                continue
            series = df[col]
            empty = series.isna() if series.dtype.kind in "fiu" else series.astype(str).str.strip().eq("")
            pct = float(empty.mean()) * 100
            if pct >= 40:
                issues.append(Issue("high_null_pct", "warning",
                                    f"Column '{col}' is {pct:.0f}% empty", int(empty.sum())))
        return issues
