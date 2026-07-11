"""Data quality scoring (0-100) with per-component breakdown."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from fap.pipeline.validation import KNOWN_EVENTS


@dataclass(frozen=True, slots=True)
class QualityScore:
    components: dict[str, float] = field(default_factory=dict)   # 0-100 each
    overall: float = 0.0

    @property
    def grade(self) -> str:
        return ("Excellent" if self.overall >= 90 else "Good" if self.overall >= 75
                else "Fair" if self.overall >= 55 else "Poor")


_WEIGHTS = {
    "completeness": 0.25,
    "coordinate_validity": 0.25,
    "player_information": 0.15,
    "event_consistency": 0.20,
    "timeline_consistency": 0.15,
}


def score(df: pd.DataFrame) -> QualityScore:
    if df.empty:
        return QualityScore(components={k: 0.0 for k in _WEIGHTS}, overall=0.0)

    def nonempty(col: str) -> float:
        s = df[col]
        filled = s.notna() if s.dtype.kind in "fiu" else s.astype(str).str.strip().ne("")
        return float(filled.mean())

    completeness = 100 * sum(nonempty(c) for c in ("event_type", "x", "y", "team", "minute")) / 5
    coords_ok = df["x"].between(0, 100) & df["y"].between(0, 100)
    coordinate_validity = 100 * float(coords_ok.mean())
    player_information = 100 * (nonempty("player") * 0.7 + nonempty("jersey_number") * 0.3)
    known = df["event_type"].str.lower().isin(KNOWN_EVENTS)
    event_consistency = 100 * float(known.mean())

    tl_scores: list[float] = []
    time = df["minute"].fillna(0) * 60 + df["second"].fillna(0)
    for _, g in pd.DataFrame({"t": time, "m": df["match_id"], "p": df["period"]}).groupby(["m", "p"]):
        if len(g) > 1:
            tl_scores.append(float((g["t"].diff().dropna() >= 0).mean()))
    timeline_consistency = 100 * (sum(tl_scores) / len(tl_scores) if tl_scores else 1.0)

    components = {
        "completeness": round(completeness, 1),
        "coordinate_validity": round(coordinate_validity, 1),
        "player_information": round(player_information, 1),
        "event_consistency": round(event_consistency, 1),
        "timeline_consistency": round(timeline_consistency, 1),
    }
    overall = round(sum(components[k] * w for k, w in _WEIGHTS.items()), 1)
    return QualityScore(components=components, overall=overall)
