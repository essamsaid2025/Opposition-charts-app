"""Derive advanced team metrics (Field Tilt, PPDA) from an aggregated team-stats
comparison table when the file does not already provide them.

These are normally event-level metrics, but a team-stats export only carries
aggregated numbers — so they are derived here from the columns the file DOES have,
using the standard analyst formulas, and only for a two-team match comparison:

* **Field Tilt** — a team's share of final-third possession, measured as its share
  of the two teams' final-third passes:
      field_tilt_A = A_final_third_passes / (A_final_third_passes + B_final_third_passes)
  This IS the standard definition, so the value is exact given the inputs.

* **PPDA** (passes per defensive action) — how many opponent passes a team allows
  per defensive action while pressing:
      ppda_A = B_passes_in_own_(def+mid)_third / (A_tackles + A_interceptions + A_fouls)
  Passes are the opponent's build-up passes (their defensive + middle third, i.e.
  the pressing team's 60%), excluding the final third, per the standard PPDA zone.
  Defensive actions use the team totals — an aggregated file has no zonal breakdown
  of tackles/interceptions/fouls — so PPDA is a close approximation, not a
  zone-exact figure. Lower PPDA = more intense pressing.

Only metrics that are ABSENT are derived (a file's own Field Tilt/PPDA is kept), and
only when every required input column is present. Pure (no I/O)."""
from __future__ import annotations

from fap.datahub.classification import normalize_key
from fap.datahub.team_stats_schema import COUNT, PERCENT, TeamStat

# derived rows are grouped here so the analyst can see they were computed, not imported
DERIVED_CATEGORY = "Advanced (derived)"


def _index(stats: list[TeamStat]) -> dict[str, TeamStat]:
    """Normalized-name -> stat (first wins), for tolerant column lookup."""
    out: dict[str, TeamStat] = {}
    for s in stats:
        out.setdefault(normalize_key(s.name), s)
    return out


def _find(index: dict[str, TeamStat], *aliases: str) -> TeamStat | None:
    for a in aliases:
        hit = index.get(normalize_key(a))
        if hit is not None:
            return hit
    return None


def _present(index: dict[str, TeamStat], *aliases: str) -> bool:
    return _find(index, *aliases) is not None


def _val(stat: TeamStat, team: str) -> float | None:
    v = stat.values.get(team)
    return None if v is None else float(v)


def _field_tilt(index: dict[str, TeamStat], teams: list[str]) -> TeamStat | None:
    fin = _find(index, "all passes in final third", "passes in final third",
                "successful passes in final third", "final third passes")
    if fin is None:
        return None
    a, b = teams
    va, vb = _val(fin, a), _val(fin, b)
    if va is None or vb is None or (va + vb) <= 0:
        return None
    ta = round(va / (va + vb) * 100)
    tb = 100 - ta
    return TeamStat(name="Field Tilt", category=DERIVED_CATEGORY, unit=PERCENT,
                    values={a: float(ta), b: float(tb)},
                    raw={a: f"{ta}%", b: f"{tb}%"})


def _ppda(index: dict[str, TeamStat], teams: list[str]) -> TeamStat | None:
    tackles = _find(index, "all tackles", "tackles")
    inter = _find(index, "interceptions", "interception")
    fouls = _find(index, "fouls", "conceded fouls")
    dthird = _find(index, "all passes in defensive third", "passes in defensive third",
                   "successful passes in defensive third")
    mthird = _find(index, "all passes in middle third", "passes in middle third",
                   "successful passes in middle third")
    if not all((tackles, inter, fouls, dthird, mthird)):
        return None
    a, b = teams
    values: dict[str, float] = {}
    raw: dict[str, str] = {}
    for team, opp in ((a, b), (b, a)):
        actions = sum(v for v in (_val(tackles, team), _val(inter, team),
                                  _val(fouls, team)) if v is not None)
        opp_passes = sum(v for v in (_val(dthird, opp), _val(mthird, opp))
                         if v is not None)
        if actions <= 0 or opp_passes <= 0:
            return None
        ppda = opp_passes / actions
        values[team] = round(ppda, 2)
        raw[team] = f"{ppda:.1f}"
    return TeamStat(name="PPDA", category=DERIVED_CATEGORY, unit=COUNT,
                    values=values, raw=raw)


def derive_team_stats(stats: list[TeamStat], teams: list[str]) -> list[TeamStat]:
    """Return the derived TeamStat rows (Field Tilt, PPDA) to append — only those the
    file lacks, only when their inputs exist, and only for a two-team comparison."""
    if len(teams) != 2:
        return []
    index = _index(stats)
    out: list[TeamStat] = []
    if not _present(index, "field tilt", "field tilt %"):
        ft = _field_tilt(index, teams)
        if ft is not None:
            out.append(ft)
    if not _present(index, "ppda", "passes per defensive action"):
        pp = _ppda(index, teams)
        if pp is not None:
            out.append(pp)
    return out


__all__ = ["derive_team_stats", "DERIVED_CATEGORY"]
