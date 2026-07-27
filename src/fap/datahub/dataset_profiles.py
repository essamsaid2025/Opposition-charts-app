"""Import profiles — reusable, provider-specific import rules.

A profile remembers the choices a provider needs (column aliases, coordinate
system, cleaning/validation toggles) so the next import of the same shape is one
click. Profiles are persisted as platform presets (``kind='datahub_profile'``)
through the ``WorkspaceManager`` — no new storage, no duplicated repository. A set
of read-only built-in profiles ships for the common providers; user profiles are
saved/loaded per user.
"""
from __future__ import annotations

from typing import Any

from fap.datahub.models import ImportProfile
from fap.identity.models import User

PROFILE_KIND = "datahub_profile"

# Built-in starting points. Mapping/coord defaults are intentionally light: the
# providers already declare their own column_mapping + native coordinate system,
# so these mostly name the coordinate standard and leave detection to do the rest.
BUILTIN_PROFILES: tuple[ImportProfile, ...] = (
    ImportProfile("builtin_statsbomb", "StatsBomb", provider_id="statsbomb",
                  coord_system="statsbomb", builtin=True),
    ImportProfile("builtin_opta", "Opta", provider_id="opta_f24",
                  coord_system="opta", builtin=True),
    ImportProfile("builtin_wyscout", "WyScout", provider_id="wyscout",
                  coord_system="wyscout", builtin=True),
    ImportProfile("builtin_skillcorner", "SkillCorner", provider_id="skillcorner",
                  coord_system="skillcorner", builtin=True),
    ImportProfile("builtin_secondspectrum", "Second Spectrum", provider_id="second_spectrum",
                  coord_system="second_spectrum", builtin=True),
    ImportProfile("builtin_manual", "Manual", provider_id="manual",
                  coord_system="0-100", builtin=True),
    ImportProfile("builtin_gps", "GPS", provider_id="csv", coord_system="0-100",
                  builtin=True),
    ImportProfile("builtin_custom", "Custom", provider_id="", coord_system="",
                  builtin=True),
)


def _from_preset(preset: Any) -> ImportProfile:
    d = preset.document or {}
    return ImportProfile(
        id=preset.id, name=preset.name, provider_id=d.get("provider_id", ""),
        mapping=dict(d.get("mapping", {})), coord_system=d.get("coord_system", ""),
        validation=dict(d.get("validation", {})), cleaning=dict(d.get("cleaning", {})),
        normalization=dict(d.get("normalization", {})), builtin=False)


class ProfileStore:
    """Thin facade over WorkspaceManager presets — reuses existing persistence."""

    def __init__(self, workspaces: Any) -> None:
        self._wm = workspaces

    def list(self, user: User) -> list[ImportProfile]:
        saved: list[ImportProfile] = []
        try:
            saved = [_from_preset(p) for p in self._wm.list_presets(user, kind=PROFILE_KIND)]
        except Exception:
            saved = []
        return [*BUILTIN_PROFILES, *saved]

    def get(self, user: User, profile_id: str) -> ImportProfile | None:
        for p in self.list(user):
            if p.id == profile_id:
                return p
        return None

    def save(self, user: User, profile: ImportProfile) -> ImportProfile:
        preset = self._wm.save_preset(user, kind=PROFILE_KIND, name=profile.name,
                                      document=profile.to_dict())
        return _from_preset(preset)


__all__ = ["ImportProfile", "ProfileStore", "BUILTIN_PROFILES", "PROFILE_KIND"]
