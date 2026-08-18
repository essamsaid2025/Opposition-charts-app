"""Teams — first-class club/academy squads (U19, U17, First Team, …).

A ``Team`` GROUPS players (its roster references existing scouting/first-team players by their
unique operational id — ACD-/CLB-/SCT-) and will own team matches, media, charts and notes in
later phases. It reuses the shared infrastructure (the relational engine, ImageStorage for the
crest, the operational-id scheme) rather than duplicating any of it. Persisted in its own tables
(migration 14), so a team's data is stored permanently, independent of the active dataset.
"""
from fap.teams.models import Team, TeamMatch, TeamMedia, TeamMember
from fap.teams.service import TeamService

__all__ = ["Team", "TeamMatch", "TeamMedia", "TeamMember", "TeamService"]
