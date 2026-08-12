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
from fap.analytics.tactical.multimatch import (
    EvidenceRef, MatchInsights, MultiMatchContext, PatternTrend, TacticalEvolution,
    analyze_evolution, build_evolution, build_multimatch,
)
from fap.analytics.tactical.profile import (
    CoverageItem, KeyPlayer, ProfileItem, ProfileSection, SummaryLine, TacticalProfile,
    TacticalProfileBuilder, build_profile,
)
from fap.analytics.tactical.report import (
    DEFAULT_SECTIONS, EvidenceLink, FocusPoint, OppositionReport, OppositionReportBuilder,
    ReportItem, ReportMetadata, ReportPlayer, ReportSection, ReportTrend, Takeaway,
    build_report, build_report_from_frame,
)
from fap.analytics.tactical.report_export import render_report, to_report_document
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
    "MultiMatchContext", "MatchInsights", "EvidenceRef", "PatternTrend", "TacticalEvolution",
    "build_multimatch", "analyze_evolution", "build_evolution",
    "OppositionReport", "OppositionReportBuilder", "ReportMetadata", "ReportSection",
    "ReportItem", "ReportPlayer", "ReportTrend", "Takeaway", "FocusPoint", "EvidenceLink",
    "DEFAULT_SECTIONS", "build_report", "build_report_from_frame",
    "to_report_document", "render_report",
]
