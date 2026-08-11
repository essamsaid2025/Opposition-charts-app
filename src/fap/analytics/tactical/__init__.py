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
from fap.analytics.tactical.thresholds import DEFAULT_THRESHOLDS, InsightThresholds

__all__ = [
    "TacticalInsightEngine", "analyze", "InsightContext",
    "Insight", "InsightReport", "InsightCategory", "Confidence", "Priority",
    "Evidence", "SupportingViz", "InsightThresholds", "DEFAULT_THRESHOLDS",
]
