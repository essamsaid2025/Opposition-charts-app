"""Aggregate a two-team canonical EVENT match into a team match-stats comparison.

An event file (e.g. StatsBomb) carries no ready-made "Team Stats" sheet, so this
builds one by counting the canonical events per team — reusing the platform's
existing football selectors (:mod:`fap.visuals.analysis`) and coordinate model, so
no metric definition is invented or duplicated. The result is a
:class:`fap.datahub.team_stats_schema.TeamStatsSchema` — exactly what the
``team_compare`` charts already consume — so an event match gets the same match-stats
comparison a real aggregated file would, PLUS the advanced metrics the sheet lacks:

* **Field Tilt** — a team's share of the two teams' final-third passes (x > 66.67).
* **PPDA** — opponent passes in their own two-thirds (x ≤ 66.67, their build-up)
  ÷ the pressing team's defensive actions (tackles/duels + interceptions + fouls)
  in the attacking two-thirds (x ≥ 33.33). Lower = more intense pressing.

Coordinates are the canonical per-team-normalized 0-100 model (each team attacks
+x). Two teams only. Pure (pandas), no Streamlit, no I/O.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from fap.visuals import analysis as A
from fap.datahub.team_stats_schema import (
    COUNT, PERCENT, TeamStat, TeamStatsSchema,
)

_FINAL_THIRD_X = 66.6667          # canonical final-third boundary (PitchDims.final_third_x)
_MID_START_X = 33.3333
# defensive actions counted for PPDA (standard: tackles/challenges + interceptions + fouls)
_PPDA_ACTIONS = ("duel", "tackle", "challenge", "interception", "foul", "50/50")


def _et(df: pd.DataFrame) -> pd.Series:
    return df["event_type"].astype(str).str.lower()


def _num_x(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df.get("x"), errors="coerce")


def _pct(part: int, whole: int) -> float:
    return round(part / whole * 100, 1) if whole else 0.0


def _share(a: float, b: float) -> tuple[int, int]:
    tot = a + b
    if tot <= 0:
        return 0, 0
    ta = round(a / tot * 100)
    return ta, 100 - ta


def build_match_stats(frame: pd.DataFrame) -> TeamStatsSchema | None:
    """Build a two-team match-stats comparison schema from a canonical event frame,
    or ``None`` when the frame is not a single two-team match."""
    if frame is None or frame.empty or "team" not in frame.columns:
        return None
    teams = [str(t) for t in frame["team"].astype(str).unique()
             if str(t).strip() and str(t).lower() != "nan"]
    if len(teams) != 2:
        return None
    a, b = teams
    fa = frame[frame["team"].astype(str) == a]
    fb = frame[frame["team"].astype(str) == b]

    stats: list[TeamStat] = []

    def count_stat(name: str, category: str, fn: Callable[[pd.DataFrame], int]) -> None:
        va, vb = fn(fa), fn(fb)
        if va == 0 and vb == 0:
            return                                   # nothing to compare -> skip (no fabrication)
        stats.append(TeamStat(name=name, category=category, unit=COUNT,
                              values={a: float(va), b: float(vb)},
                              raw={a: str(va), b: str(vb)}))

    def pct_stat(name: str, category: str, part: Callable[[pd.DataFrame], int],
                 whole: Callable[[pd.DataFrame], int]) -> None:
        wa, wb = whole(fa), whole(fb)
        if wa == 0 and wb == 0:
            return
        pa, pb = _pct(part(fa), wa), _pct(part(fb), wb)
        stats.append(TeamStat(name=name, category=category, unit=PERCENT,
                              values={a: pa, b: pb}, raw={a: f"{pa:g}%", b: f"{pb:g}%"}))

    def share_stat(name: str, category: str, fn: Callable[[pd.DataFrame], int]) -> None:
        pa, pb = _share(fn(fa), fn(fb))
        stats.append(TeamStat(name=name, category=category, unit=PERCENT,
                              values={a: float(pa), b: float(pb)},
                              raw={a: f"{pa}%", b: f"{pb}%"}))

    # ---- selectors (reuse fap.visuals.analysis definitions) ----
    shots = lambda d: A.shots(d)                                             # noqa: E731
    passes = lambda d: A.passes(d)                                          # noqa: E731
    def _shot_result(d, keep):
        s = A.shots(d)
        return int(s["shot_result"].astype(str).str.lower().isin(keep).sum()) \
            if "shot_result" in s.columns else 0
    def _final_third_passes(d) -> int:
        p = A.passes(d)
        return int((pd.to_numeric(p.get("x"), errors="coerce") > _FINAL_THIRD_X).sum())
    def _et_count(d, kinds) -> int:
        return int(_et(d).isin(kinds).sum())
    def _corners(d) -> int:
        if "set_piece" not in d.columns:
            return 0
        sp = d["set_piece"].astype(str).str.lower()
        return int((_et(d).eq("pass") & sp.str.contains("corner")).sum())

    # ---- Summary ----
    share_stat("Possession", "Summary", lambda d: len(A.movement(d)))
    count_stat("Goals", "Summary", lambda d: _shot_result(d, ("goal",)))
    count_stat("Shots", "Summary", lambda d: len(shots(d)))
    count_stat("Corners", "Summary", _corners)
    count_stat("Fouls", "Summary", lambda d: _et_count(d, ("foul", "foul committed")))

    # ---- Offensive ----
    count_stat("Shots on target", "Offensive", lambda d: _shot_result(d, ("goal", "saved")))
    count_stat("Successful take ons", "Offensive",
               lambda d: int((_et(d).eq("dribble") & d.get("outcome", pd.Series(dtype=str))
                              .astype(str).str.lower().isin(A._SUCCESS)).sum())
               if "outcome" in d.columns else 0)

    # ---- Defensive ----
    count_stat("Tackles", "Defensive", lambda d: _et_count(d, ("duel", "tackle", "challenge")))
    count_stat("Interceptions", "Defensive", lambda d: _et_count(d, ("interception",)))
    count_stat("Clearances", "Defensive", lambda d: _et_count(d, ("clearance",)))
    count_stat("Recoveries", "Defensive", lambda d: _et_count(d, ("recovery", "ball recovery")))
    count_stat("Blocks", "Defensive", lambda d: _et_count(d, ("block",)))

    # ---- Distribution ----
    count_stat("Passes", "Distribution", lambda d: len(passes(d)))
    pct_stat("Pass accuracy", "Distribution",
             lambda d: len(A.successful(A.passes(d))), lambda d: len(A.passes(d)))
    count_stat("Passes in final third", "Distribution", _final_third_passes)

    # ---- Advanced (derived): Field Tilt + PPDA ----
    share_stat("Field Tilt", "Advanced (derived)", _final_third_passes)
    ppda = _ppda(fa, fb, a, b)
    if ppda is not None:
        stats.append(ppda)

    if not stats:
        return None
    categories: list[str] = []
    for s in stats:
        if s.category not in categories:
            categories.append(s.category)
    return TeamStatsSchema(entity_type="team_stat", stat_field="", category_field="",
                           teams=[a, b], stats=stats, categories=categories, ignored=[])


def _ppda(fa: pd.DataFrame, fb: pd.DataFrame, a: str, b: str) -> TeamStat | None:
    """Standard zone PPDA for each team (see module docstring)."""
    values: dict[str, float] = {}
    raw: dict[str, str] = {}
    for team, own, opp in ((a, fa, fb), (b, fb, fa)):
        opp_passes = A.passes(opp)
        num = int((pd.to_numeric(opp_passes.get("x"), errors="coerce") <= _FINAL_THIRD_X).sum())
        acts = own[_et(own).isin(_PPDA_ACTIONS)]
        den = int((pd.to_numeric(acts.get("x"), errors="coerce") >= _MID_START_X).sum())
        if den <= 0 or num <= 0:
            return None
        val = round(num / den, 2)
        values[team] = val
        raw[team] = f"{val:.1f}"
    return TeamStat(name="PPDA", category="Advanced (derived)", unit=COUNT,
                    values=values, raw=raw)


__all__ = ["build_match_stats"]
