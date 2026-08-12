"""Tactical Insight Engine (P0).

A Streamlit-free layer over the existing canonical dataset that identifies and
*explains* meaningful tactical patterns (progression, final-third, recoveries,
players) as structured, serializable insights — observation, interpretation and
recommended investigation kept strictly separate, each backed by evidence,
sample size and transparent confidence.

Reuses the existing football semantics (``fap.openplay.add_derived_columns``,
``fap.pipeline.quality``) and points supporting evidence back at the existing
visualization system; it introduces no new coordinate system, filters or charts.
"""
from fap.analytics.tactical.context import InsightContext
from fap.analytics.tactical.engine import TacticalInsightEngine, analyze
from fap.analytics.tactical.model import (
    Confidence, Evidence, Insight, InsightCategory, InsightReport, Priority, SupportingViz,
)
from fap.analytics.tactical.profile import (
    CoverageItem, KeyPlayer, ProfileItem, ProfileSection, SummaryLine, TacticalProfile,
    TacticalProfileBuilder, build_profile,
)
from fap.analytics.tactical.thresholds import DEFAULT_THRESHOLDS, InsightThresholds


def analyze_profile(frame, thresholds: InsightThresholds | None = None) -> TacticalProfile:
    """Convenience: run the P0 engine on ``frame`` then build the P1 profile — one
    P0 pass, no duplicated analytics."""
    return build_profile(TacticalInsightEngine(thresholds).analyze(frame))


__all__ = [
    "TacticalInsightEngine", "analyze", "analyze_profile", "InsightContext",
    "Insight", "InsightReport", "InsightCategory", "Confidence", "Priority",
    "Evidence", "SupportingViz", "InsightThresholds", "DEFAULT_THRESHOLDS",
    "TacticalProfile", "TacticalProfileBuilder", "build_profile",
    "ProfileSection", "KeyPlayer", "ProfileItem", "SummaryLine", "CoverageItem",
]
