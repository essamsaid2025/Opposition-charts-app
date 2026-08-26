"""Style-of-Play metrics for OUR teams (club / academy).

This turns a team's linked match EVENT data into the numbers that describe *our*
identity — building play, possession, high pressing and fast ball recovery — one
match at a time, then across the last match / last five / all matches.

Nothing here is invented: every metric reuses a definition that already lives in
the platform.

* Possession, Pass accuracy, Field Tilt and PPDA come from
  :func:`fap.openplay.match_stats.build_match_stats` (the same two-team match-stats
  engine the opponent comparison uses) — we simply read *our* team's value.
* Progressive passes, final-third passes, turnovers, counter-press regains and
  recoveries come from the shared football selectors in :mod:`fap.visuals.analysis`.
* xG comes from the frozen Internal xG Model v1.0
  (:func:`fap.xg.enrichment.compute_internal_xg_series`) — no formula lives here.

A metric that cannot be computed from the available columns is ``None`` (unavailable),
never a fabricated number. Pure pandas — no Streamlit, no I/O — so it is fully testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from fap.visuals import analysis as A
from fap.openplay.match_stats import build_match_stats
from fap.analytics.tactical.transitions import RECOVERY_EVENTS

_FINAL_THIRD_X = 66.6667          # canonical final-third boundary (each team attacks +x)

# ---------------------------------------------------------------- metric catalogue
# Pillars = the four tenets of our style of play.
PILLAR_POSSESSION = "Build-up & Possession"
PILLAR_PRESS = "High Press"
PILLAR_RECOVERY = "Fast Recovery"
PILLAR_ATTACK = "Attacking Output"

PILLARS: tuple[str, ...] = (PILLAR_POSSESSION, PILLAR_PRESS, PILLAR_RECOVERY, PILLAR_ATTACK)


@dataclass(frozen=True)
class MetricDef:
    """One style metric: how it is labelled, which pillar it belongs to, its unit
    and whether a higher value is better (drives the trend arrow / colouring)."""
    key: str
    name: str
    pillar: str
    unit: str                     # "count" | "percent" | "ratio" | "xg"
    higher_is_better: bool
    help: str = ""


METRICS: tuple[MetricDef, ...] = (
    # --- Build-up & Possession ---
    MetricDef("possession", "Possession", PILLAR_POSSESSION, "percent", True,
              "Our share of the two teams' on-ball actions."),
    MetricDef("pass_accuracy", "Pass accuracy", PILLAR_POSSESSION, "percent", True,
              "Share of our passes that were successful."),
    MetricDef("final_third_passes", "Passes in final third", PILLAR_POSSESSION, "count", True,
              "Our passes played in the attacking third (x > 66.7)."),
    MetricDef("progressive_passes", "Progressive passes", PILLAR_POSSESSION, "count", True,
              "Passes that move the ball meaningfully closer to goal."),
    MetricDef("field_tilt", "Field Tilt", PILLAR_POSSESSION, "percent", True,
              "Our share of both teams' final-third passes — territorial dominance."),
    # --- High Press ---
    MetricDef("ppda", "PPDA", PILLAR_PRESS, "ratio", False,
              "Opponent passes allowed per our defensive action. Lower = more intense press."),
    MetricDef("opp_passes_allowed", "Opponent passes allowed", PILLAR_PRESS, "count", False,
              "Total passes the opponent completed against us. Lower = more disruption."),
    MetricDef("high_recoveries", "High recoveries", PILLAR_PRESS, "count", True,
              "Ball recoveries won in the attacking third (x > 66.7)."),
    # --- Fast Recovery ---
    MetricDef("ball_recoveries", "Ball recoveries", PILLAR_RECOVERY, "count", True,
              "Recoveries / interceptions / tackles that regained the ball."),
    MetricDef("counterpress_regains", "Counter-press regains", PILLAR_RECOVERY, "count", True,
              "Defensive actions within 6s of losing the ball (event-data counter-press proxy)."),
    MetricDef("turnovers_lost", "Turnovers lost", PILLAR_RECOVERY, "count", False,
              "Our possession-ending failures (bad passes/carries + dispossessions). Lower = better."),
    # --- Attacking Output ---
    MetricDef("xg", "xG", PILLAR_ATTACK, "xg", True,
              "Expected goals — Internal xG Model v1.0, summed over our shots."),
    MetricDef("shots", "Shots", PILLAR_ATTACK, "count", True, "Our total shots."),
    MetricDef("shots_on_target", "Shots on target", PILLAR_ATTACK, "count", True,
              "Our shots on target (saved + goals)."),
    MetricDef("goals", "Goals", PILLAR_ATTACK, "count", True, "Our goals scored."),
)

METRIC_KEYS: tuple[str, ...] = tuple(m.key for m in METRICS)
_BY_KEY: dict[str, MetricDef] = {m.key: m for m in METRICS}


def metric(key: str) -> MetricDef:
    return _BY_KEY[key]


def metrics_in(pillar: str) -> list[MetricDef]:
    return [m for m in METRICS if m.pillar == pillar]


# ---------------------------------------------------------------- per-match records
@dataclass
class MatchMetrics:
    """Our team's style metrics for a single match (plus its context)."""
    match_id: str = ""
    label: str = ""
    date: str = ""
    opponent: str = ""
    venue: str = ""
    scoreline: str = ""
    resolved: bool = False        # was our team identified inside the match data?
    values: dict[str, float | None] = field(default_factory=dict)

    def get(self, key: str) -> float | None:
        return self.values.get(key)


# ---------------------------------------------------------------- team-name resolution
def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _frame_teams(frame: pd.DataFrame) -> list[str]:
    if frame is None or getattr(frame, "empty", True) or "team" not in frame.columns:
        return []
    return [str(t) for t in frame["team"].astype(str).unique()
            if str(t).strip() and str(t).lower() != "nan"]


def resolve_team_names(frame: pd.DataFrame, our_name: str,
                       opponent_name: str = "") -> tuple[str | None, str | None]:
    """Return ``(our_team_string, opponent_string)`` as they appear in the match data.

    A match frame holds exactly two team strings. We identify ours by: matching the
    known opponent name (ours is then the *other* team), else matching our own name,
    else — when there are exactly two teams and only one is unmatched — inference.
    Returns ``(None, None)`` when it cannot be resolved unambiguously.
    """
    teams = _frame_teams(frame)
    if len(teams) != 2:
        return (None, None)
    a, b = teams
    na, nb = _norm(a), _norm(b)
    opp, our = _norm(opponent_name), _norm(our_name)

    def _match(target: str) -> str | None:
        if not target:
            return None
        if na == target:
            return a
        if nb == target:
            return b
        # loose containment either direction (e.g. "Ahly" vs "Al Ahly U19")
        if target in na or na in target:
            return a
        if target in nb or nb in target:
            return b
        return None

    opp_team = _match(opp)
    if opp_team is not None:
        return (b if opp_team == a else a, opp_team)
    our_team = _match(our)
    if our_team is not None:
        return (our_team, b if our_team == a else a)
    return (None, None)


# ---------------------------------------------------------------- xG enrichment
def _with_internal_xg(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the frozen Internal xG column if it is not already present. Never
    raises — xG staying unavailable is acceptable, a broken frame is not."""
    if frame is None or getattr(frame, "empty", True):
        return frame
    if "internal_xg" in frame.columns:
        return frame
    try:
        from fap.xg.enrichment import compute_internal_xg_series
        frame = frame.copy()
        frame["internal_xg"] = compute_internal_xg_series(frame)
    except Exception:  # noqa: BLE001 - xG is optional; never break the frame
        pass
    return frame


def _schema_value(schema: Any, stat_name: str, team: str) -> float | None:
    if schema is None:
        return None
    for s in schema.stats:
        if s.name == stat_name:
            v = s.values.get(team)
            return float(v) if v is not None else None
    return None


def _has_cols(frame: pd.DataFrame, *cols: str) -> bool:
    return all(c in frame.columns for c in cols)


# ---------------------------------------------------------------- the metric engine
def match_style_metrics(frame: pd.DataFrame, our_name: str,
                        opponent_name: str = "") -> tuple[dict[str, float | None], bool]:
    """Compute our team's style metrics for one match frame.

    Returns ``(values, resolved)`` where ``resolved`` is False (and every value
    ``None``) when our team could not be identified inside the two-team data.
    """
    values: dict[str, float | None] = {k: None for k in METRIC_KEYS}
    frame = _with_internal_xg(frame)
    our, opp = resolve_team_names(frame, our_name, opponent_name)
    if our is None:
        return values, False

    df = frame
    our_df = df[df["team"].astype(str) == our]
    opp_df = df[df["team"].astype(str) == opp] if opp is not None else df[df["team"].astype(str) != our]

    # Shared two-team engine — Possession / Pass accuracy / Field Tilt / PPDA are read
    # from here so their (both-team) definitions are never re-implemented.
    try:
        schema = build_match_stats(df)
    except Exception:  # noqa: BLE001
        schema = None
    values["possession"] = _schema_value(schema, "Possession", our)
    values["pass_accuracy"] = _schema_value(schema, "Pass accuracy", our)
    values["field_tilt"] = _schema_value(schema, "Field Tilt", our)
    values["ppda"] = _schema_value(schema, "PPDA", our)

    # --- Build-up & Possession (counts from our subframe) ---
    our_passes = A.passes(our_df)
    values["final_third_passes"] = _final_third(our_passes)
    values["progressive_passes"] = int(len(A.progressive(our_passes)))

    # --- High Press ---
    values["opp_passes_allowed"] = int(len(A.passes(opp_df)))
    recoveries = _recoveries(our_df)
    values["ball_recoveries"] = int(len(recoveries))
    values["high_recoveries"] = _final_third(recoveries)

    # --- Fast Recovery ---
    values["turnovers_lost"] = _safe_count(lambda: len(A.turnovers(our_df)))
    if _has_cols(our_df, "time_min", "match_id"):
        values["counterpress_regains"] = _safe_count(lambda: len(A.counterpress_window(our_df)))

    # --- Attacking Output ---
    shots = A.shots(our_df)
    values["shots"] = int(len(shots))
    values["goals"] = _shot_result_count(shots, ("goal",))
    values["shots_on_target"] = _shot_result_count(shots, ("goal", "saved"))
    values["xg"] = _team_xg(shots)

    return values, True


def _final_third(df: pd.DataFrame) -> int:
    if df is None or getattr(df, "empty", True):
        return 0
    return int((pd.to_numeric(df.get("x"), errors="coerce") > _FINAL_THIRD_X).sum())


def _recoveries(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or getattr(df, "empty", True) or "event_type" not in df.columns:
        return df.iloc[0:0] if df is not None else pd.DataFrame()
    return df[df["event_type"].astype(str).str.lower().isin(RECOVERY_EVENTS)]


def _shot_result_count(shots: pd.DataFrame, keep: tuple[str, ...]) -> int:
    if shots is None or getattr(shots, "empty", True) or "shot_result" not in shots.columns:
        return 0
    return int(shots["shot_result"].astype(str).str.lower().isin(keep).sum())


def _team_xg(shots: pd.DataFrame) -> float | None:
    """Summed Internal xG over our shots, or None when no xG value is present."""
    if shots is None or getattr(shots, "empty", True) or "internal_xg" not in shots.columns:
        return None
    xg = pd.to_numeric(shots["internal_xg"], errors="coerce")
    if not bool(xg.notna().any()):
        return None
    try:
        from fap.xg.enrichment import sum_xg
        return round(float(sum_xg(shots)), 2)
    except Exception:  # noqa: BLE001
        return round(float(xg.fillna(0.0).sum()), 2)


def _safe_count(fn) -> int | None:
    try:
        return int(fn())
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- the series
@dataclass
class StyleSeries:
    """Our team's style metrics across matches (oldest first) with the aggregates
    the dashboard shows: raw per match, last-N average and a rolling trend."""
    per_match: list[MatchMetrics] = field(default_factory=list)

    @property
    def played(self) -> list[MatchMetrics]:
        """Matches where our team was resolved (i.e. carry real values)."""
        return [m for m in self.per_match if m.resolved]

    @property
    def latest(self) -> MatchMetrics | None:
        played = self.played
        return played[-1] if played else None

    def window(self, n: int) -> list[MatchMetrics]:
        """The most recent ``n`` resolved matches (newest last)."""
        played = self.played
        return played[-n:] if n and n > 0 else played

    def averages(self, subset: list[MatchMetrics] | None = None) -> dict[str, float | None]:
        """Mean of each metric over ``subset`` (default: all resolved matches),
        ignoring matches where that metric was unavailable."""
        rows = self.played if subset is None else subset
        out: dict[str, float | None] = {}
        for key in METRIC_KEYS:
            vals = [m.values.get(key) for m in rows]
            vals = [float(v) for v in vals if v is not None]
            out[key] = round(sum(vals) / len(vals), 2) if vals else None
        return out

    def trend(self, key: str, window: int = 3) -> list[dict[str, Any]]:
        """Per-match points for one metric with a trailing rolling average, oldest
        first — the data behind a trend line. Only resolved matches are included."""
        points: list[dict[str, Any]] = []
        history: list[float] = []
        for m in self.played:
            raw = m.values.get(key)
            if raw is not None:
                history.append(float(raw))
            roll = round(sum(history[-window:]) / len(history[-window:]), 2) if history else None
            points.append({"label": m.label or m.opponent or m.match_id,
                           "opponent": m.opponent, "date": m.date,
                           "raw": (float(raw) if raw is not None else None),
                           "rolling": roll})
        return points


__all__ = [
    "MetricDef", "MatchMetrics", "StyleSeries",
    "METRICS", "METRIC_KEYS", "PILLARS",
    "PILLAR_POSSESSION", "PILLAR_PRESS", "PILLAR_RECOVERY", "PILLAR_ATTACK",
    "metric", "metrics_in", "resolve_team_names", "match_style_metrics",
]
