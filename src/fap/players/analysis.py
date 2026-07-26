"""First Team Players analysis - PURE helpers (no DB, no UI). Derivations the
service and page reuse: age, current contract/injury, availability, workload
windows and career totals. No new football analytics engine - match statistics
still come from the event datasets via the visualization engine.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from fap.players.models import PlayerCareer, PlayerContract, PlayerMedical, PlayerTraining


def age_from_dob(dob: str) -> int | None:
    if not dob:
        return None
    try:
        d = _dt.date.fromisoformat(dob[:10])
    except ValueError:
        return None
    today = _dt.date.today()
    return today.year - d.year - ((today.month, today.day) < (d.month, d.day))


def current_contract(contracts: list[PlayerContract]) -> PlayerContract | None:
    active = [c for c in contracts if c.status == "active"] or contracts
    return max(active, key=lambda c: c.contract_end or "", default=None)


def contract_expiring(contracts: list[PlayerContract], *, within_days: int = 180) -> bool:
    c = current_contract(contracts)
    if not c or not c.contract_end:
        return False
    try:
        end = _dt.date.fromisoformat(c.contract_end[:10])
    except ValueError:
        return False
    return 0 <= (end - _dt.date.today()).days <= within_days


def current_injury(medical: list[PlayerMedical]) -> PlayerMedical | None:
    open_inj = [m for m in medical if m.status in ("open", "recovering")]
    return max(open_inj, key=lambda m: m.date or "", default=None)


def availability_label(status: str, availability: str, medical: list[PlayerMedical]) -> str:
    if current_injury(medical):
        return "Injured"
    return {"suspended": "Suspended", "loan": "On loan"}.get(status, availability.title() or "Available")


def _sum_window(training: list[PlayerTraining], field: str, days: int) -> float:
    cutoff = _dt.date.today() - _dt.timedelta(days=days)
    total = 0.0
    for t in training:
        try:
            d = _dt.date.fromisoformat(t.date[:10]) if t.date else None
        except ValueError:
            d = None
        if d and d >= cutoff:
            v = getattr(t, field, None)
            if v is not None:
                total += float(v)
    return round(total, 1)


def workload(training: list[PlayerTraining]) -> dict[str, Any]:
    """Acute/chronic-style windows for the Overview page (Last 7 / 28 days)."""
    return {
        "load_7d": _sum_window(training, "load", 7),
        "load_28d": _sum_window(training, "load", 28),
        "sprint_7d": _sum_window(training, "sprint_distance", 7),
        "hsr_7d": _sum_window(training, "hsr", 7),
        "sessions_7d": sum(1 for t in training if _within(t.date, 7)),
        "sessions_28d": sum(1 for t in training if _within(t.date, 28)),
    }


def _within(date: str, days: int) -> bool:
    try:
        d = _dt.date.fromisoformat(date[:10]) if date else None
    except ValueError:
        return False
    return bool(d and d >= _dt.date.today() - _dt.timedelta(days=days))


def career_totals(career: list[PlayerCareer]) -> dict[str, int]:
    return {
        "appearances": sum(c.appearances for c in career),
        "starts": sum(int((c.document or {}).get("starts", 0)) for c in career),
        "goals": sum(c.goals for c in career),
        "assists": sum(c.assists for c in career),
        "minutes": sum(c.minutes for c in career),
        "yellow": sum(c.yellow for c in career),
        "red": sum(c.red for c in career),
    }
