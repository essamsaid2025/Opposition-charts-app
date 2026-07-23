"""Set-piece -> Report Studio bridge (Phase 9.1) - PURE.

Turns an analytics bundle (from fap.setpieces.analytics) into a list of report
``Section`` objects using the EXISTING report models. The service injects these
into a report created through ReportsManager, so a set-piece report opens in the
existing Report Studio, fully editable - no second reporting engine, no second
editor. Richer auto-reports (heatmap images, recommendations, video links) are
Phase 9.5; this establishes the integration with statistics sections.
"""
from __future__ import annotations

from typing import Any

from fap.reports.models import Insight, KPI, Section, Table
from fap.setpieces.models import SET_PIECE_TYPE_LABELS


def _n(value: Any, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value}{suffix}"


def build_setpiece_sections(bundle: dict[str, Any]) -> list[Section]:
    """bundle = {overview, derived, by_type, delivery, outcome} (see
    SetPieceService.analytics_overview)."""
    ov = bundle.get("overview", {})
    dr = bundle.get("derived", {})
    bt = bundle.get("by_type", {})
    dl = bundle.get("delivery", {})
    oc = bundle.get("outcome", {})

    sections: list[Section] = []

    # -- overview -------------------------------------------------------------
    overview_kpis = [
        KPI("Total Set Pieces", _n(ov.get("total", 0))),
        KPI("Goals", _n(ov.get("goals", 0))),
        KPI("Shots", _n(ov.get("shots", 0))),
        KPI("xG", _n(ov.get("xg", 0.0))),
        KPI("Shot %", _n(ov.get("shot_pct", 0.0), "%")),
        KPI("Goal %", _n(ov.get("goal_pct", 0.0), "%")),
        KPI("First Contact %", _n(ov.get("first_contact_pct", 0.0), "%")),
        KPI("Second Ball %", _n(ov.get("second_ball_pct", 0.0), "%")),
        KPI("Retention %", _n(ov.get("retention_pct", 0.0), "%")),
        KPI("Avg Players in Box", _n(ov.get("avg_players_in_box"))),
        KPI("Avg Time to Shot", _n(ov.get("avg_time_to_shot"), "s")),
        KPI("Success Rate", _n(dr.get("success_rate", 0.0), "%")),
        KPI("Goal Contribution", _n(dr.get("goal_contribution", 0.0), "%")),
        KPI("Chance Creation", _n(dr.get("chance_creation", 0.0), "%")),
    ]
    sections.append(Section(id="sp_overview", title="Set Piece Overview",
                            subtitle="Headline KPIs", kpis=overview_kpis,
                            insights=_overview_insights(ov, dr, dl)))

    # -- by type --------------------------------------------------------------
    if bt:
        rows = [[SET_PIECE_TYPE_LABELS.get(t, t), s["count"], s["shots"], s["goals"],
                 f"{s['shot_pct']}%", f"{s['goal_pct']}%", f"{s['first_contact_pct']}%", s["xg"]]
                for t, s in sorted(bt.items(), key=lambda kv: -kv[1]["count"])]
        sections.append(Section(
            id="sp_by_type", title="By Set Piece Type",
            tables=[Table(title="Per-type breakdown",
                          columns=["Type", "Count", "Shots", "Goals", "Shot %",
                                   "Goal %", "1st Contact %", "xG"], rows=rows)]))

    # -- delivery & outcomes --------------------------------------------------
    tables: list[Table] = []
    if dl.get("delivery_type"):
        tables.append(Table(title="Delivery type",
                            columns=["Delivery", "Count"],
                            rows=[[k.title(), v] for k, v in dl["delivery_type"].items()]))
    if oc:
        tables.append(Table(title="Outcomes", columns=["Outcome", "Count"],
                            rows=[[k.title(), v] for k, v in oc.items()]))
    if tables:
        sections.append(Section(id="sp_delivery", title="Delivery & Outcomes", tables=tables))

    return sections


def _overview_insights(ov: dict, dr: dict, dl: dict) -> list[Insight]:
    out: list[Insight] = []
    top_delivery = next(iter(dl.get("delivery_type", {})), None)
    if top_delivery and top_delivery != "unknown":
        out.append(Insight(f"Most common delivery: {top_delivery.title()}.", "neutral"))
    sr = dr.get("success_rate", 0.0)
    if ov.get("total"):
        kind = "success" if sr >= 40 else ("warning" if sr >= 20 else "danger")
        out.append(Insight(f"Success rate {sr}% across {ov['total']} set pieces.", kind))
    if ov.get("goals"):
        out.append(Insight(f"{ov['goals']} goal(s) from set pieces "
                           f"({ov.get('goal_pct', 0.0)}%).", "success"))
    return out
