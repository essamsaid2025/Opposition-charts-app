"""Tactical Insight Engine (P0) — the Streamlit-free core.

``TacticalInsightEngine().analyze(frame)`` turns an already-filtered canonical
event frame into a serializable :class:`InsightReport`. It builds ONE shared
:class:`InsightContext`, runs the P0 rules over it, orders the surviving insights
by priority/confidence, and reports data-quality *notices* explaining any family
of analysis that could not run (missing end coordinates, no recovery events,
missing players …) rather than fabricating results.

No Streamlit, no matplotlib, no rendering — the engine only computes insights.
Filters are the caller's responsibility: pass the frame you are already analysing
and the insights correspond exactly to it.
"""
from __future__ import annotations

import pandas as pd

from fap.analytics.tactical.context import InsightContext
from fap.analytics.tactical.model import Confidence, Insight, InsightReport, Priority
from fap.analytics.tactical.rules import RULES
from fap.analytics.tactical.thresholds import DEFAULT_THRESHOLDS, InsightThresholds

_PRIORITY_RANK = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
_CONFIDENCE_RANK = {Confidence.HIGH: 0, Confidence.MEDIUM: 1, Confidence.LOW: 2}


class TacticalInsightEngine:
    def __init__(self, thresholds: InsightThresholds | None = None) -> None:
        self.th = thresholds or DEFAULT_THRESHOLDS

    # -- public API ----------------------------------------------------------
    def analyze(self, frame: pd.DataFrame | None) -> InsightReport:
        if frame is None or getattr(frame, "empty", True):
            return InsightReport(notices=("No events match the current filters.",),
                                 subject="the selected events")
        ctx = InsightContext.build(frame)
        if ctx.n_events == 0:
            return InsightReport(notices=("No events match the current filters.",),
                                 subject=ctx.subject)

        insights: list[Insight] = []
        for rule in RULES:
            try:
                out = rule(ctx, self.th)
            except Exception:
                out = None            # a faulty rule is skipped, never fatal
            if out is not None:
                insights.append(out)

        insights = self._order(insights)
        return InsightReport(
            insights=tuple(insights),
            notices=tuple(self._notices(ctx)),
            subject=ctx.subject, quality=round(ctx.quality, 1), n_events=ctx.n_events)

    # -- internals -----------------------------------------------------------
    @staticmethod
    def _order(insights: list[Insight]) -> list[Insight]:
        return sorted(insights, key=lambda i: (
            _PRIORITY_RANK[i.priority], _CONFIDENCE_RANK[i.confidence], -i.confidence_score))

    def _notices(self, ctx: InsightContext) -> list[str]:
        """Honest 'analysis unavailable' messages — one per missing capability,
        so the analyst knows *why* a family produced nothing."""
        out: list[str] = []
        th = self.th
        if not ctx.caps["end_coords"]:
            out.append("Progression, final-third and box analysis unavailable: pass/carry end "
                       "coordinates (end_x/end_y) are missing.")
        else:
            if len(ctx.progressive) < th.min_progressive_actions:
                out.append(f"Progression analysis inconclusive: only {len(ctx.progressive)} progressive "
                           f"actions (need {th.min_progressive_actions}).")
            if len(ctx.final_third_entries) < th.min_final_third_entries:
                out.append(f"Final-third analysis inconclusive: only {len(ctx.final_third_entries)} "
                           f"final-third entries (need {th.min_final_third_entries}).")
        if not ctx.caps["recovery_events"]:
            out.append("Recovery analysis unavailable: no ball-recovery events "
                       "(recovery / interception / tackle) are present.")
        elif len(ctx.recoveries) < th.min_recoveries:
            out.append(f"Recovery analysis inconclusive: only {len(ctx.recoveries)} recoveries "
                       f"(need {th.min_recoveries}).")
        if not ctx.caps["players"]:
            out.append("Player insights unavailable: player names are missing from the data.")
        if ctx.quality < th.min_quality:
            out.append(f"Data quality is low ({ctx.quality:.0f}/100); insights are suppressed or shown at "
                       f"low confidence until the data improves.")
        return out


# module-level convenience
def analyze(frame: pd.DataFrame | None, thresholds: InsightThresholds | None = None) -> InsightReport:
    return TacticalInsightEngine(thresholds).analyze(frame)
