"""Statistical safeguards for the Tactical Insight Engine.

Configurable thresholds in the project's frozen-dataclass style. They encode the
rules that stop tiny/weak samples from becoming confident tactical claims:
minimum denominators, minimum effect sizes (how far the leading category must
clear the rest), minimum player samples, and the data-quality floor below which
insights are suppressed. Every rule reads these — nothing is hard-coded inline.
"""
from __future__ import annotations

from dataclasses import dataclass

from fap.analytics.tactical.model import Confidence


@dataclass(frozen=True)
class InsightThresholds:
    # ---- minimum denominators (sample-size safeguards) ----
    min_progressive_actions: int = 20      # progression corridor/side rules
    min_final_third_entries: int = 15      # final-third concentration/corridor
    min_box_entries: int = 8               # penalty-box entry concentration
    min_recoveries: int = 15               # recovery-zone rules
    min_player_actions: int = 8            # a player rule needs this many player events
    min_events: int = 30                   # below this the whole context is too small

    # ---- effect sizes ----
    dominance_share: float = 0.45          # leading lane/channel share to be "dominant"
    strong_dominance_share: float = 0.55   # share for a strong statement
    min_effect_margin: float = 0.12        # leading category must beat 2nd by this
    strong_effect_margin: float = 0.25
    player_share: float = 0.20             # a player must carry at least this share
    strong_player_share: float = 0.30
    high_recovery_share: float = 0.28      # final-third recovery share to be notable
    strong_recovery_share: float = 0.40

    # ---- confidence scaling ----
    strong_sample_multiple: float = 3.0    # sample >= min * this => full sample credit
    min_quality: float = 40.0              # below this, insights are suppressed
    quality_full: float = 90.0             # quality at/above this => full quality credit

    # confidence-band cut points on the 0-1 blended score
    high_score: float = 0.66
    medium_score: float = 0.38

    # ---- P2: transitions ----
    min_transition_recoveries: int = 12    # recoveries needed to profile transitions
    transition_share: float = 0.35         # share of recoveries leading to an outcome to be notable
    strong_transition_share: float = 0.55
    rapid_transition_seconds: float = 6.0  # recovery -> first attacking action = "rapid"
    min_transition_shots: int = 3          # absolute floor for a recovery->shot claim

    # ---- P2: turnovers / vulnerabilities ----
    min_turnovers: int = 20                # turnovers needed for a zone/route vulnerability
    turnover_zone_share: float = 0.40      # share of turnovers in a zone to concentrate
    min_route_attempts: int = 25           # movement attempts through a corridor (denominator)
    high_turnover_rate: float = 0.45       # loss rate along a route to flag failed progression
    strong_turnover_rate: float = 0.60
    min_ft_for_efficiency: int = 20        # final-third entries needed to judge efficiency
    low_box_conversion: float = 0.20       # box entries / final-third entries below => inefficient
    low_shot_conversion: float = 0.12      # shots / final-third entries below => inefficient

    # ---- P2: multi-match ----
    min_matches: int = 3                   # matches needed for a trend/consistency claim
    min_events_per_match: int = 40         # a match below this is excluded (data quality)
    consistent_fraction: float = 0.6       # present in >= this fraction of usable matches
    trend_stable_band: float = 0.06        # |slope span| within this => "stable"
    trend_volatile_std: float = 0.16       # share stdev above this => "volatile"


DEFAULT_THRESHOLDS = InsightThresholds()


def _clip01(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def grade(sample: int, min_sample: int, effect: float, quality: float,
          th: InsightThresholds) -> tuple[Confidence, float, dict]:
    """Transparent confidence grading from sample size, effect size and data
    quality. Returns the band, a 0-1 blended score, and the component breakdown
    (so the UI can explain *why* an insight is High/Medium/Low).

    - ``effect`` is a 0-1 measure of how strong/clear the pattern is (e.g. the
      leading share, or the margin over the runner-up — the rule decides).
    - ``quality`` is the 0-100 data-quality score for the analysed frame.
    """
    strong_sample = max(min_sample * th.strong_sample_multiple, min_sample + 1)
    s_sample = _clip01((sample - min_sample) / (strong_sample - min_sample))
    s_effect = _clip01(effect)
    s_quality = _clip01((quality - th.min_quality) / max(1.0, th.quality_full - th.min_quality))

    score = 0.4 * s_sample + 0.4 * s_effect + 0.2 * s_quality

    if quality < th.min_quality:                 # hard floor: never confident on poor data
        level = Confidence.LOW
    elif score >= th.high_score and sample >= min_sample:
        level = Confidence.HIGH
    elif score >= th.medium_score:
        level = Confidence.MEDIUM
    else:
        level = Confidence.LOW
    breakdown = {"sample": round(s_sample, 3), "effect": round(s_effect, 3),
                 "quality": round(s_quality, 3), "score": round(score, 3)}
    return level, round(score, 3), breakdown
