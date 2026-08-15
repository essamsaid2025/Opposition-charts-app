"""Deterministic, explainable dataset identity resolution (P4.2.1).

The registered Player is the source of truth; a scouting dataset is a source of
evidence whose spelling ("S. Mamadu bah") must never become the player's identity
("Mamadu Bah"). This module resolves a player to a dataset row through a controlled,
explainable hierarchy - never a black-box fuzzy match, never modifying the dataset.

Match tiers (strongest first):
    exact            raw string equality
    normalized       equal after unicode/case/punctuation/whitespace normalization
    alias            a display-name/alias normalizes to the row
    initial_variant  same core (multi-letter) name tokens, initials aside
                     ("Mamadu Bah" ~ "S. Mamadu bah")
    surname_initial  one core-token set is a subset with an equal last token
                     ("John Smith" ~ "J. Smith") - weaker, needs confirmation

A single high-tier match auto-resolves; several plausible rows are reported as
AMBIGUOUS (the analyst chooses); none is NOT_FOUND. Dataset dimensions (team,
position, nationality) only *disambiguate* already name-matched candidates - they
never manufacture a match from weak name evidence.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

# tier -> (rank, confidence label, method label). Higher rank wins.
_TIERS: dict[str, tuple[int, str, str]] = {
    "exact": (5, "exact", "Exact name"),
    "normalized": (4, "high", "Normalized name"),
    "alias": (4, "high", "Alias / display name"),
    "initial_variant": (3, "high", "Initial + normalized name"),
    "surname_initial": (2, "medium", "Surname + initial"),
}
_AUTO_MIN_RANK = 3          # tiers at/above this auto-resolve when unique


def normalize_name(value: Any) -> str:
    """Canonical comparison form: unicode NFKD (accents stripped), lower-cased,
    apostrophes/hyphens/punctuation flattened to spaces, whitespace collapsed."""
    s = unicodedata.normalize("NFKD", str(value or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    out = []
    for ch in s:
        out.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    return " ".join("".join(out).split())


def _tokens(value: Any) -> list[str]:
    return normalize_name(value).split()


def _core(tokens: list[str]) -> list[str]:
    """Multi-letter tokens (drops single-letter initials)."""
    return [t for t in tokens if len(t) > 1]


def _name_tier(player_tokens: list[str], entity_tokens: list[str]) -> str | None:
    """Best structural tier between two already-normalized token lists (excluding
    exact/normalized equality, handled by the caller)."""
    pc, ec = _core(player_tokens), _core(entity_tokens)
    if not pc or not ec:
        return None
    if sorted(pc) == sorted(ec):
        return "initial_variant"
    ps, es = set(pc), set(ec)
    if (ps <= es or es <= ps) and pc[-1] == ec[-1]:
        return "surname_initial"
    return None


@dataclass(frozen=True, slots=True)
class DatasetEntity:
    key: str                              # the dataset id-field value (verbatim)
    dims: dict[str, Any] = field(default_factory=dict)   # team/position/country/...


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    key: str
    display_name: str
    method: str
    confidence: str
    rank: int
    dims: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "display_name": self.display_name, "method": self.method,
                "confidence": self.confidence, "rank": self.rank, "dims": dict(self.dims)}


@dataclass(frozen=True, slots=True)
class MatchResult:
    status: str                           # "matched" | "ambiguous" | "not_found"
    candidate: MatchCandidate | None = None
    candidates: list[MatchCandidate] = field(default_factory=list)
    auto: bool = False                    # safe to resolve without asking

    @property
    def method(self) -> str:
        return self.candidate.method if self.candidate else ""

    @property
    def confidence(self) -> str:
        return self.candidate.confidence if self.candidate else ""

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "auto": self.auto,
                "candidate": self.candidate.to_dict() if self.candidate else None,
                "candidates": [c.to_dict() for c in self.candidates]}


def _player_identity_strings(player: Any) -> list[tuple[str, str]]:
    """(string, source-label) for the player's name, display name and aliases."""
    from fap.scouting import identity
    out: list[tuple[str, str]] = [(getattr(player, "name", "") or "", "name")]
    dn = identity.display_name_of(player)
    if dn and dn != getattr(player, "name", ""):
        out.append((dn, "display"))
    for a in identity.aliases_of(player):
        out.append((a, "alias"))
    return [(s, lbl) for s, lbl in out if str(s).strip()]


def _best_tier_for_entity(player: Any, entity: DatasetEntity) -> tuple[str, str] | None:
    """The strongest (tier, source-label) between the player and one entity."""
    ent_norm = normalize_name(entity.key)
    ent_tokens = ent_norm.split()
    best: tuple[int, str, str] | None = None
    for raw, label in _player_identity_strings(player):
        if str(raw) == str(entity.key):
            tier = "exact"
        elif normalize_name(raw) == ent_norm:
            tier = "alias" if label != "name" else "normalized"
        else:
            struct = _name_tier(normalize_name(raw).split(), ent_tokens)
            if struct is None:
                continue
            tier = "alias" if (label != "name" and _TIERS[struct][0] < _TIERS["alias"][0]) else struct
        rank = _TIERS[tier][0]
        if best is None or rank > best[0]:
            best = (rank, tier, label)
    if best is None:
        return None
    return best[1], best[2]


def _dims_agree(player: Any, dims: dict[str, Any]) -> int:
    """How many player dimensions (club/position/nationality) match the entity's -
    used only to break ties among name-matched candidates."""
    checks = {
        "team": getattr(player, "club", "") or "",
        "position": getattr(player, "position", "") or "",
        "country": getattr(player, "nationality", "") or getattr(player, "country", "") or "",
        "league": getattr(player, "league", "") or "",
    }
    agree = 0
    for dim, pv in checks.items():
        ev = dims.get(dim)
        if pv and ev and normalize_name(pv) and normalize_name(pv) in normalize_name(ev):
            agree += 1
    return agree


def match_player(player: Any, entities: list[DatasetEntity]) -> MatchResult:
    """Resolve a player against dataset entities into an explainable result."""
    matches: list[MatchCandidate] = []
    for ent in entities:
        tier_info = _best_tier_for_entity(player, ent)
        if tier_info is None:
            continue
        tier, _src = tier_info
        rank, conf, method = _TIERS[tier]
        matches.append(MatchCandidate(key=ent.key, display_name=ent.key, method=method,
                                      confidence=conf, rank=rank, dims=dict(ent.dims)))
    if not matches:
        return MatchResult("not_found")

    top_rank = max(m.rank for m in matches)
    top = [m for m in matches if m.rank == top_rank]
    if len(top) == 1:
        cand = top[0]
        return MatchResult("matched", candidate=cand, candidates=matches,
                           auto=cand.rank >= _AUTO_MIN_RANK)

    # tie at the top tier: try to disambiguate by dimensions
    scored = sorted(((_dims_agree(player, m.dims), m) for m in top),
                    key=lambda t: t[0], reverse=True)
    if scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        cand = scored[0][1]
        return MatchResult("matched", candidate=cand, candidates=matches,
                           auto=cand.rank >= _AUTO_MIN_RANK)
    return MatchResult("ambiguous", candidate=None, candidates=top)


# ---------------------------------------------------------------- dataset entities
def dataset_entities(frame: Any, schema: dict[str, Any]) -> list[DatasetEntity]:
    """Build match entities (id value + dimension values) from a scouting frame and
    its persisted schema. Reads only the id field and declared dimension columns."""
    id_field = schema.get("id_field")
    if frame is None or not id_field or id_field not in getattr(frame, "columns", []):
        return []
    dim_cols = {k: v for k, v in (schema.get("dimensions") or {}).items()
                if k != "player" and v in frame.columns}
    out: list[DatasetEntity] = []
    seen: set[str] = set()
    for _, row in frame.iterrows():
        key = str(row[id_field]).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        dims = {k: (None if _isna(row[col]) else row[col]) for k, col in dim_cols.items()}
        out.append(DatasetEntity(key=key, dims=dims))
    return out


def _isna(v: Any) -> bool:
    try:
        import pandas as pd
        return bool(pd.isna(v))
    except Exception:
        return v is None


__all__ = [
    "normalize_name", "DatasetEntity", "MatchCandidate", "MatchResult",
    "match_player", "dataset_entities",
]
