"""Professional player-profile data model (P4.3) - pure, no persistence, no UI.

The scouting ``Player`` already carries most profile columns (dob, nationality,
position, secondary_positions, foot, height, weight, shirt_number, contract_until,
agent, club, league, market_value). This module adds the *semantics* on top -
without a migration:

* Age is DERIVED from DOB (never a manually-entered source of truth).
* Preferred foot uses a controlled vocabulary (Right/Left/Both/Unknown).
* Secondary nationalities and external links live in ``document`` (multi-valued).
* A single ``player_snapshot`` gives the dashboard one normalized view.
* ``validate_profile`` returns honest warnings; it never silently "fixes" values.

Missing information stays genuinely missing (``None``) - nothing is fabricated.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any

# controlled vocabulary for preferred foot
FOOT_VALUES: tuple[str, ...] = ("right", "left", "both", "unknown")

# sensible football-player ranges for validation (empty always allowed)
_HEIGHT_RANGE = (140, 220)          # cm
_WEIGHT_RANGE = (40, 130)           # kg
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def normalize_foot(value: Any) -> str:
    v = str(value or "").strip().lower()
    if v in FOOT_VALUES:
        return v
    return {"r": "right", "l": "left", "rf": "right", "lf": "left",
            "right foot": "right", "left foot": "left", "either": "both",
            "two-footed": "both", "two footed": "both", "": "unknown"}.get(v, "unknown")


def foot_label(value: Any) -> str:
    return normalize_foot(value).title()


def _parse_date(value: Any) -> _dt.date | None:
    s = str(value or "").strip()
    if not _DATE_RE.match(s):
        return None
    try:
        return _dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def derived_age(dob: Any, today: _dt.date | None = None) -> int | None:
    """Age in whole years derived from a ``YYYY-MM-DD`` DOB, or ``None`` if the DOB
    is missing/invalid/in the future. This is the ONLY source of truth for age."""
    d = _parse_date(dob)
    if d is None:
        return None
    today = today or _dt.date.today()
    if d > today:
        return None
    years = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return years if years >= 0 else None


def secondary_nationalities_of(player: Any) -> list[str]:
    prof = _profile_doc(player)
    out: list[str] = []
    for n in prof.get("secondary_nationalities", []) or []:
        n = str(n).strip()
        if n and n not in out:
            out.append(n)
    return out


def _profile_doc(player: Any) -> dict[str, Any]:
    doc = getattr(player, "document", None) or {}
    prof = doc.get("profile")
    return dict(prof) if isinstance(prof, dict) else {}


def links_of(player: Any) -> list[dict[str, Any]]:
    doc = getattr(player, "document", None) or {}
    return list(doc.get("links", []) or [])


def positions_of(player: Any) -> list[str]:
    """Primary + secondary positions, de-duplicated, order-preserved."""
    out: list[str] = []
    for p in [getattr(player, "position", "")] + list(getattr(player, "secondary_positions", []) or []):
        for part in str(p or "").replace("/", ",").split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def player_snapshot(player: Any) -> dict[str, Any]:
    """One normalized profile view for the dashboard. Values are ``None`` when
    genuinely missing (the UI renders 'Not available'); age is always derived."""
    from fap.scouting import identity

    def _num(v):
        try:
            return None if v in (None, "", 0) else (int(v) if float(v) == int(float(v)) else float(v))
        except (TypeError, ValueError):
            return None

    dob = getattr(player, "dob", "") or ""
    age = derived_age(dob)
    if age is None and getattr(player, "age", None):        # legacy: fall back to stored age
        age = int(player.age)
    return {
        "player_id": getattr(player, "id", ""),
        "name": getattr(player, "name", ""),
        "display_name": identity.display_name_of(player),
        "operational_id": identity.operational_id_of(player),
        "player_type": identity.player_type_of(player),
        "type_label": identity.type_label(identity.player_type_of(player)),
        "dob": dob or None,
        "age": age,
        "age_derived": derived_age(dob) is not None,
        "nationality": (getattr(player, "nationality", "") or getattr(player, "country", "")) or None,
        "secondary_nationalities": secondary_nationalities_of(player),
        "height_cm": _num(getattr(player, "height", None)),
        "weight_kg": _num(getattr(player, "weight", None)),
        "preferred_foot": normalize_foot(getattr(player, "foot", "")),
        "positions": positions_of(player),
        "club": getattr(player, "club", "") or None,
        "league": getattr(player, "league", "") or None,
        "shirt_number": _num(getattr(player, "shirt_number", None)),
        "contract_expires": (getattr(player, "contract_until", "") or None),
        "agent": getattr(player, "agent", "") or None,
        "market_value": _num(getattr(player, "market_value", None)),
        "status": identity.normalize_status(getattr(player, "status", "")),
        "priority": identity.normalize_priority(getattr(player, "priority", "")),
        "recruitment_profile": identity.recruitment_profile_of(player),
        "age_group": identity.age_group_of(player),
        "tags": list(getattr(player, "tags", []) or []),
        "internal_rating": getattr(player, "internal_rating", None),
        "source": identity.source_of(player),
        "aliases": identity.aliases_of(player),
    }


def validate_profile(fields: dict[str, Any], today: _dt.date | None = None) -> list[str]:
    """Honest validation warnings for a profile edit - empty values are allowed,
    questionable values are flagged (never silently corrected)."""
    warnings: list[str] = []
    today = today or _dt.date.today()

    def _numeric(key, label, lo, hi, unit):
        v = fields.get(key)
        if v in (None, "", 0):
            return
        try:
            n = float(v)
        except (TypeError, ValueError):
            warnings.append(f"{label} must be a number.")
            return
        if not (lo <= n <= hi):
            warnings.append(f"{label} {n:g}{unit} is outside the typical range "
                            f"({lo}-{hi}{unit}).")

    _numeric("height_cm", "Height", *_HEIGHT_RANGE, "cm")
    _numeric("weight_kg", "Weight", *_WEIGHT_RANGE, "kg")

    dob = fields.get("dob")
    if dob:
        d = _parse_date(dob)
        if d is None:
            warnings.append("Date of birth is not a valid date (use YYYY-MM-DD).")
        elif d > today:
            warnings.append("Date of birth cannot be in the future.")

    contract = fields.get("contract_expires") or fields.get("contract_until")
    if contract and _parse_date(contract) is None:
        warnings.append("Contract expiry is not a valid date (use YYYY-MM-DD).")

    foot = fields.get("preferred_foot") or fields.get("foot")
    if foot and str(foot).strip().lower() not in FOOT_VALUES:
        warnings.append(f"Preferred foot must be one of {', '.join(v.title() for v in FOOT_VALUES)}.")
    return warnings


__all__ = [
    "FOOT_VALUES", "normalize_foot", "foot_label", "derived_age",
    "secondary_nationalities_of", "links_of", "positions_of", "player_snapshot",
    "validate_profile",
]
