"""Player-scouting semantic schema + analyzer.

When the classifier decides a file is a player-scouting table, this module reads
its *meaning*: which columns are the player identity and supporting dimensions,
which are analytical metrics (and in what unit), how many players it holds, and
how healthy the data is. It is the scouting counterpart of the event pipeline —
pure (pandas only), deterministic, and it does not run the event pipeline or
duplicate any analytics engine.

The output (``ScoutingAnalysis``) is what the Data Hub shows the user and what it
persists as the dataset's semantic schema, so the Scouting module can later
discover the dataset and read its dimensions/metrics without re-inferring them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fap.datahub.classification import (
    DatasetClassification, IDENTITY_ALIASES, classify_frame, is_index_artifact,
    normalize_key,
)

# ---------------------------------------------------------------- metric units
PER_90 = "per_90"
PERCENT = "percent"
RATE = "rate"
RATIO = "ratio"
COUNT = "count"
NORMALIZED = "normalized"
UNKNOWN_UNIT = "unknown"

# dataset-level value scale: are the numbers real measurements or rank/percentile
# normalized values (0..1 / 0..100)? Detected from distribution, never converted.
SCALE_RAW = "raw"
SCALE_NORMALIZED = "normalized"


def classify_metric_unit(name: str) -> str:
    """Infer a metric's unit from its column *semantics* (name), independent of
    its value distribution — deliberately NOT "0..1 means percentile". A value
    scale (raw vs normalized) is a separate, dataset-level signal."""
    key = normalize_key(name)
    tokens = key.split()
    if "%" in key or "percent" in key:
        return PERCENT
    # per-90 (normalize_key turns "/90" into " 90", "per 90" stays as-is)
    if "per 90" in key or "per90" in key or key.endswith(" 90") or "p90" in tokens:
        return PER_90
    # "npxg per shot", "xa per shot assist" — a per-something ratio
    if " per " in key:
        return RATIO
    if "ratio" in key:
        return RATIO
    if "rate" in key:
        return RATE
    return COUNT


@dataclass(frozen=True, slots=True)
class MetricField:
    source: str                 # original column header (as in the file)
    name: str                   # normalized display key
    unit: str                   # PER_90 / PERCENT / RATE / RATIO / COUNT / ...
    missing_pct: float = 0.0    # fraction of rows with no value
    min: float | None = None
    max: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "name": self.name, "unit": self.unit,
                "missing_pct": round(self.missing_pct, 4),
                "min": self.min, "max": self.max}


@dataclass(frozen=True, slots=True)
class ScoutingSchema:
    """The semantic contract of a player-scouting dataset. Serializable so it can
    live inside ``dataset.document`` and be read back by the Scouting module."""
    entity_type: str = "player"
    id_field: str = ""                                    # source col = player id
    dimensions: dict[str, str] = field(default_factory=dict)   # canonical -> source
    metrics: list[MetricField] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)      # index/empty columns
    value_scale: str = SCALE_RAW

    def metric_sources(self) -> list[str]:
        return [m.source for m in self.metrics]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "id_field": self.id_field,
            "dimensions": dict(self.dimensions),
            "metrics": [m.to_dict() for m in self.metrics],
            "ignored": list(self.ignored),
            "value_scale": self.value_scale,
        }


@dataclass(frozen=True, slots=True)
class QualityCheck:
    key: str
    label: str
    status: str            # "pass" | "warn" | "fail"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "status": self.status,
                "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ScoutingQuality:
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
class ScoutingAnalysis:
    """The full result the wizard renders and the service persists."""
    classification: DatasetClassification
    schema: ScoutingSchema
    quality: ScoutingQuality
    entity_count: int = 0
    teams: int = 0
    leagues: int = 0
    positions: list[str] = field(default_factory=list)
    competition: str = ""
    frame: pd.DataFrame | None = None

    @property
    def dataset_type(self) -> str:
        return self.classification.dataset_type

    @property
    def metric_count(self) -> int:
        return len(self.schema.metrics)

    @property
    def dimension_count(self) -> int:
        return len(self.schema.dimensions)

    def summary(self) -> dict[str, Any]:
        """Compact, serializable summary for the dataset document + tests."""
        return {
            "dataset_type": self.dataset_type,
            "entity_type": self.schema.entity_type,
            "entity_count": self.entity_count,
            "players": self.entity_count,
            "teams": self.teams,
            "leagues": self.leagues,
            "competition": self.competition,
            "positions": list(self.positions),
            "metric_count": self.metric_count,
            "dimension_count": self.dimension_count,
            "value_scale": self.schema.value_scale,
            "confidence": round(self.classification.confidence, 3),
            "grade": self.quality.grade,
        }


# ---------------------------------------------------------------- analysis
def _clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop trailing all-empty rows and pure index/empty columns — the only
    structural cleanup; metric values are never altered."""
    df = frame.dropna(how="all").copy()
    drop = [c for c in df.columns if is_index_artifact(c) or df[c].dropna().empty]
    if drop:
        df = df.drop(columns=drop)
    return df


def _dimensions(frame: pd.DataFrame) -> dict[str, str]:
    dims: dict[str, str] = {}
    for col in frame.columns:
        key = normalize_key(col)
        for canonical, aliases in IDENTITY_ALIASES.items():
            if key in aliases and canonical not in dims:
                dims[canonical] = col
    return dims


def _detect_value_scale(frame: pd.DataFrame, metrics: list[MetricField]) -> str:
    """Are the metric values normalized (percentile/rank in 0..1) rather than raw?

    Evidence: columns whose unit would normally exceed 1 (per-90 counts, percents)
    that nonetheless never exceed ~1.0. Requires several such columns to agree, so
    a single genuinely-small ratio does not flip the whole dataset. Non-destructive
    — we only *label* the scale, never rescale the numbers."""
    candidates = [m for m in metrics if m.unit in (PER_90, PERCENT, COUNT)
                  and m.max is not None]
    if len(candidates) < 3:
        return SCALE_RAW
    bounded = sum(1 for m in candidates if m.max is not None and m.max <= 1.0001)
    return SCALE_NORMALIZED if bounded / len(candidates) >= 0.8 else SCALE_RAW


def _build_metrics(frame: pd.DataFrame, dims: dict[str, str]) -> list[MetricField]:
    from fap.datahub.classification import _DEMOGRAPHIC_KEYS  # local: internal set
    dim_cols = set(dims.values())
    metrics: list[MetricField] = []
    rows = max(len(frame), 1)
    for col in frame.columns:
        key = normalize_key(col)
        if col in dim_cols or key in _DEMOGRAPHIC_KEYS:
            continue
        coerced = pd.to_numeric(frame[col], errors="coerce")
        if coerced.notna().mean() < 0.6:
            continue                                    # not a numeric metric
        present = coerced.dropna()
        missing = 1.0 - (len(present) / rows)
        metrics.append(MetricField(
            source=str(col), name=key, unit=classify_metric_unit(str(col)),
            missing_pct=float(missing),
            min=float(present.min()) if not present.empty else None,
            max=float(present.max()) if not present.empty else None))
    return metrics


def _distinct(frame: pd.DataFrame, col: str | None) -> int:
    if not col or col not in frame.columns:
        return 0
    return int(frame[col].astype(str).str.strip().replace("", pd.NA).dropna().nunique())


def _quality(frame: pd.DataFrame, schema: ScoutingSchema,
             ignored: list[str]) -> ScoutingQuality:
    checks: list[QualityCheck] = []
    # identity present
    checks.append(QualityCheck(
        "identity", "Player identity",
        "pass" if schema.id_field else "fail",
        f"column {schema.id_field!r}" if schema.id_field else "no player column found"))
    # at least one metric
    checks.append(QualityCheck(
        "metrics", "Analytical metrics",
        "pass" if schema.metrics else "fail",
        f"{len(schema.metrics)} metric(s) detected" if schema.metrics
        else "no numeric scouting metrics"))
    # duplicate players
    if schema.id_field and schema.id_field in frame.columns:
        ids = frame[schema.id_field].astype(str).str.strip()
        ids = ids[ids.ne("")]
        dupes = int(ids.duplicated().sum())
        checks.append(QualityCheck(
            "duplicates", "Unique players", "warn" if dupes else "pass",
            f"{dupes} duplicate player row(s)" if dupes else "all players unique"))
    # missingness across metrics
    partial = [m for m in schema.metrics if m.missing_pct > 0]
    if partial:
        heavy = [m for m in partial if m.missing_pct >= 0.5]
        checks.append(QualityCheck(
            "missing", "Metric completeness", "warn",
            f"{len(partial)} metric(s) contain missing values"
            + (f", {len(heavy)} over half-empty" if heavy else "")))
    else:
        checks.append(QualityCheck("missing", "Metric completeness", "pass",
                                   "no missing metric values"))
    # index/empty artifacts (informational)
    if ignored:
        checks.append(QualityCheck(
            "artifacts", "Ignored columns", "pass",
            f"ignored {len(ignored)} index/empty column(s)"))
    return ScoutingQuality(checks=checks)


def analyze_player_scouting(frame: pd.DataFrame,
                            classification: DatasetClassification | None = None
                            ) -> ScoutingAnalysis:
    """Read a player-scouting table into a semantic schema + quality report.

    Row-count agnostic: a one-player file and a 500-player database go through the
    exact same path, differing only in ``entity_count``/coverage metadata."""
    cls = classification or classify_frame(frame)
    original_cols = list(frame.columns)
    df = _clean_frame(frame)
    ignored = [str(c) for c in original_cols if c not in df.columns]

    dims = _dimensions(df)
    metrics = _build_metrics(df, dims)
    value_scale = _detect_value_scale(df, metrics)
    schema = ScoutingSchema(
        entity_type="player", id_field=dims.get("player", ""),
        dimensions=dims, metrics=metrics, ignored=ignored, value_scale=value_scale)

    quality = _quality(df, schema, ignored)

    id_col = schema.id_field
    entity_count = _distinct(df, id_col) if id_col else int(len(df))
    positions: list[str] = []
    if dims.get("position") and dims["position"] in df.columns:
        vals = df[dims["position"]].astype(str).str.strip()
        # a "CF, LW" cell lists several positions — split and de-duplicate
        seen: list[str] = []
        for cell in vals:
            for part in str(cell).replace("/", ",").split(","):
                p = part.strip()
                if p and p.lower() != "nan" and p not in seen:
                    seen.append(p)
        positions = seen
    competition = ""
    if dims.get("league") and dims["league"] in df.columns:
        league_vals = df[dims["league"]].astype(str).str.strip()
        league_vals = league_vals[league_vals.ne("")]
        if not league_vals.empty:
            competition = str(league_vals.mode().iloc[0])

    return ScoutingAnalysis(
        classification=cls, schema=schema, quality=quality,
        entity_count=entity_count,
        teams=_distinct(df, dims.get("team")),
        leagues=_distinct(df, dims.get("league")),
        positions=positions, competition=competition, frame=df)


__all__ = [
    "PER_90", "PERCENT", "RATE", "RATIO", "COUNT", "NORMALIZED", "UNKNOWN_UNIT",
    "SCALE_RAW", "SCALE_NORMALIZED", "classify_metric_unit",
    "MetricField", "ScoutingSchema", "QualityCheck", "ScoutingQuality",
    "ScoutingAnalysis", "analyze_player_scouting",
]
