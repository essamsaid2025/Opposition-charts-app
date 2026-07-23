"""Match Preparation & Reporting Center (Phase 9.5) - the intelligent report
BUILDER. NOT a new editor and NOT a new report engine: it assembles a complete,
fully-editable document from the EXISTING modules and hands it to the existing
Report Studio / ReportsManager. Every visualization is embedded through the
existing Renderer via ``embed_visual`` (no screenshot hacks). Every statistic and
insight is reused from 9.1-9.4 (no duplicated computation).

The builder is profile-driven (Coach / Analyst / Executive / Opposition / Set
Piece / Penalty) and *smart*: it only emits sections and visualizations that have
data, so no empty pages are ever produced.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from fap.reports.models import Insight as RInsight, KPI, Section, Table
from fap.setpieces.intelligence import ROUTINE_LABELS
from fap.setpieces.models import SET_PIECE_TYPE_LABELS, SetPieceFilter

# ------------------------------------------------------------------ profiles
PROFILES: dict[str, dict[str, Any]] = {
    "coach": {"label": "Coach Report", "pages": "8-12", "density": "med",
              "kpi_overview": True, "exec": False, "findings": True, "dangerous": True,
              "routines": False, "intelligence": True, "recommendations": True,
              "training": True, "videos": True, "appendix": False, "gk": True,
              "categories": ("off_corners", "def_corners", "penalties")},
    "analyst": {"label": "Analyst Report", "pages": "30-60", "density": "high",
                "kpi_overview": True, "exec": True, "findings": True, "dangerous": True,
                "routines": True, "intelligence": True, "recommendations": True,
                "training": True, "videos": True, "appendix": True, "gk": True,
                "categories": ("off_corners", "def_corners", "off_fk", "def_fk",
                               "throwins", "penalties")},
    "executive": {"label": "Executive Report", "pages": "2-4", "density": "low",
                  "kpi_overview": True, "exec": True, "findings": True, "dangerous": False,
                  "routines": False, "intelligence": False, "recommendations": True,
                  "training": False, "videos": False, "appendix": False, "gk": False,
                  "categories": ()},
    "opposition": {"label": "Opposition Report", "pages": "20-40", "density": "high",
                   "kpi_overview": True, "exec": True, "findings": True, "dangerous": True,
                   "routines": True, "intelligence": True, "recommendations": True,
                   "training": True, "videos": True, "appendix": True, "gk": True,
                   "categories": ("off_corners", "def_corners", "off_fk", "def_fk", "throwins")},
    "setpiece": {"label": "Set Piece Report", "pages": "15-30", "density": "high",
                 "kpi_overview": True, "exec": False, "findings": True, "dangerous": True,
                 "routines": True, "intelligence": True, "recommendations": True,
                 "training": True, "videos": True, "appendix": True, "gk": True,
                 "categories": ("off_corners", "def_corners", "off_fk", "def_fk", "throwins")},
    "penalty": {"label": "Penalty Report", "pages": "8-16", "density": "high",
                "kpi_overview": False, "exec": False, "findings": False, "dangerous": False,
                "routines": False, "intelligence": True, "recommendations": True,
                "training": True, "videos": True, "appendix": True, "gk": False,
                "categories": ("penalties",)},
}

# category -> (label, filter overrides, viz ids by density)
CATEGORY_SPECS: dict[str, tuple[str, dict[str, Any], dict[str, list[str]]]] = {
    "off_corners": ("Offensive Corners", {"type": "corner", "phase": "offensive"},
                    {"low": ["sp_delivery_heatmap"],
                     "med": ["sp_delivery_heatmap", "sp_box_occupancy", "sp_first_contact"],
                     "high": ["sp_delivery_heatmap", "sp_box_occupancy", "sp_first_contact",
                              "sp_dangerous_zones", "sp_movement_vectors"]}),
    "def_corners": ("Defensive Corners", {"type": "corner", "phase": "defensive"},
                    {"low": ["sp_defensive_shape"],
                     "med": ["sp_defensive_shape", "sp_marking", "sp_gk_start"],
                     "high": ["sp_defensive_shape", "sp_marking", "sp_marking_assignment",
                              "sp_gk_start", "sp_second_ball"]}),
    "off_fk": ("Offensive Free Kicks", {"type": "free_kick", "phase": "offensive"},
               {"low": ["sp_delivery_heatmap"], "med": ["sp_delivery_heatmap", "sp_shot_location"],
                "high": ["sp_delivery_heatmap", "sp_shot_location", "sp_box_occupancy"]}),
    "def_fk": ("Defensive Free Kicks", {"type": "free_kick", "phase": "defensive"},
               {"low": ["sp_defensive_shape"], "med": ["sp_defensive_shape", "sp_wall"],
                "high": ["sp_defensive_shape", "sp_wall", "sp_gk_start"]}),
    "throwins": ("Throw-ins", {"type": "throw_in"},
                 {"low": ["sp_delivery_scatter"], "med": ["sp_delivery_scatter", "sp_first_contact"],
                  "high": ["sp_delivery_scatter", "sp_first_contact", "sp_box_occupancy"]}),
    "penalties": ("Penalties", {"type": "penalty"},
                  {"low": ["sp_pen_placement"],
                   "med": ["sp_pen_placement", "sp_gk_dive_heatmap", "sp_pen_success_zones"],
                   "high": ["sp_pen_placement", "sp_pen_goal_heatmap", "sp_gk_dive_heatmap",
                            "sp_pen_clusters", "sp_pen_success_zones", "sp_gk_reach"]}),
}
GK_VIZ = ["sp_gk_start", "sp_gk_movement", "sp_gk_claim"]

# recommendation -> training objective (keyword rules, deterministic)
TRAINING_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("second ball", "second-ball"), "Train second-ball reaction and edge-of-box recovery"),
    (("near post", "near-post"), "Train near-post defensive positioning"),
    (("far post", "far-post"), "Train far-post marking"),
    (("wall",), "Improve free-kick wall positioning"),
    (("screen", "block", "pick"), "Prepare defenders for screen / blocker routines"),
    (("press", "occupy the goalkeeper", "keeper"), "Prepare the goalkeeper for a crowded six-yard box"),
    (("delay", "early commitment"), "Rehearse delayed penalty run-ups"),
    (("weak side",), "Practice forcing shooters to their weak side"),
    (("placement", "expect", "low-right", "corner"), "Prepare goalkeeper against preferred penalty placement"),
    (("marking",), "Improve marking assignments and transitions"),
    (("vary", "delivery"), "Vary delivery type and target in training"),
    (("target",), "Rehearse attacking the identified danger zone"),
)


def training_objective(action: str, rationale: str = "") -> str:
    text = f"{action} {rationale}".lower()
    for keys, objective in TRAINING_RULES:
        if any(k in text for k in keys):
            return objective
    return f"Prepare for: {action.rstrip('.')}"


# ------------------------------------------------------------------ blueprint
@dataclass(slots=True)
class Embed:
    viz_id: str
    filt: SetPieceFilter
    title: str


@dataclass(slots=True)
class ReportBlueprint:
    profile: str
    cover: dict[str, Any]
    sections: list[Section] = field(default_factory=list)
    embeds: list[Embed] = field(default_factory=list)


# ------------------------------------------------------------------ orchestration
def build_plan(svc: Any, user: Any, profile: str, filt: SetPieceFilter | None,
               workspace_id: str | None = None, *, title: str = "") -> ReportBlueprint:
    """Assemble the full report blueprint by REUSING the service's own analytics,
    intelligence and penalty methods. Nothing is recomputed here beyond light
    ranking/formatting."""
    if profile not in PROFILES:
        raise ValueError(f"unknown report profile {profile!r}")
    plan = PROFILES[profile]
    base = filt or SetPieceFilter()
    bp = ReportBlueprint(profile=profile, cover=_cover(base, plan, title, user))

    overview = svc.analytics_overview(user, base, workspace_id=workspace_id)
    intel = svc.intelligence(user, base, workspace_id=workspace_id) \
        if (plan["intelligence"] or plan["findings"] or plan["exec"] or plan["routines"]
            or plan["recommendations"] or plan["training"]) else None
    pen_intel = svc.penalty_intelligence(user, base, workspace_id=workspace_id) \
        if (plan["intelligence"] or plan["recommendations"] or plan["training"]) else None

    all_recs = (list(intel.recommendations) if intel else []) + \
               (list(pen_intel.recommendations) if pen_intel else [])

    # -- executive summary -------------------------------------------------
    if plan["exec"] and overview["count"]:
        bp.sections.append(_exec_summary(overview, intel, all_recs))

    # -- key findings ------------------------------------------------------
    dangerous = svc._dangerous_players(user, base, workspace_id=workspace_id) \
        if (plan["findings"] or plan["dangerous"]) else []
    if plan["findings"] and overview["count"]:
        s = _key_findings(overview, intel, dangerous)
        if s:
            bp.sections.append(s)

    # -- opposition overview KPIs -----------------------------------------
    if plan["kpi_overview"] and overview["count"]:
        bp.sections.append(_overview_section(overview))

    # -- per-category sections (smart: only if data) ----------------------
    for key in plan["categories"]:
        label, overrides, viz_by_density = CATEGORY_SPECS[key]
        cat_filt = replace(base, **overrides)
        ov = svc.analytics_overview(user, cat_filt, workspace_id=workspace_id)
        if not ov["count"]:
            continue                                   # no data -> no section, no page
        bp.sections.append(_category_section(key, label, ov))
        for viz_id in viz_by_density.get(plan["density"], []):
            bp.embeds.append(Embed(viz_id, cat_filt, f"{label} — {viz_id}"))

    # -- goalkeeper page ---------------------------------------------------
    if plan["gk"] and overview["count"]:
        for viz_id in GK_VIZ:
            bp.embeds.append(Embed(viz_id, base, f"Goalkeeper — {viz_id}"))

    # -- dangerous players -------------------------------------------------
    if plan["dangerous"] and dangerous:
        bp.sections.append(_dangerous_players(dangerous))

    # -- routine library ---------------------------------------------------
    if plan["routines"] and intel and intel.clusters:
        bp.sections.append(_routine_library(intel))

    # -- intelligence (grouped) -------------------------------------------
    if plan["intelligence"] and intel:
        bp.sections.extend(_intelligence_groups(intel, pen_intel))

    # -- recommendations by priority --------------------------------------
    if plan["recommendations"] and all_recs:
        bp.sections.append(_recommendations(all_recs))

    # -- training focus ----------------------------------------------------
    if plan["training"] and all_recs:
        bp.sections.append(_training_focus(all_recs))

    # -- video library -----------------------------------------------------
    if plan["videos"]:
        videos = _collect_videos(svc, user, base, workspace_id)
        if videos:
            bp.sections.append(_video_library(videos))

    # -- appendix ----------------------------------------------------------
    if plan["appendix"] and bp.embeds:
        bp.sections.append(_appendix(bp.embeds))

    return bp


# ------------------------------------------------------------------ cover
def _cover(filt: SetPieceFilter, plan: dict, title: str, user: Any) -> dict[str, Any]:
    return {"title": title or f"Match Preparation — {plan['label']}",
            "subtitle": plan["label"], "club": filt.team, "opponent": filt.opponent,
            "competition": filt.competition, "season": filt.season,
            "analyst": getattr(user, "name", "") or getattr(user, "email", ""), "match_date": ""}


# ------------------------------------------------------------------ sections
def _exec_summary(overview: dict, intel: Any, recs: list) -> Section:
    ov = overview["overview"]
    md = []
    if intel and intel.narrative:
        md.extend(intel.narrative[:3])
    top = [r for r in recs if r.priority in ("critical", "high")][:3]
    if top:
        md.append("**Priority actions:** " + "; ".join(r.action for r in top))
    return Section(
        id="mp_exec", title="Executive Summary",
        kpis=[KPI("Set Pieces", str(ov["total"])), KPI("Goals", str(ov["goals"])),
              KPI("Shots", str(ov["shots"])), KPI("xG", str(ov["xg"])),
              KPI("Conversion", f"{ov['goal_pct']}%")],
        markdown="\n\n".join(md))


def _overview_section(overview: dict) -> Section:
    ov, dr = overview["overview"], overview["derived"]
    return Section(
        id="mp_overview", title="Opposition Overview",
        kpis=[KPI("Total", str(ov["total"])), KPI("Goals", str(ov["goals"])),
              KPI("Shots", str(ov["shots"])), KPI("Shot %", f"{ov['shot_pct']}%"),
              KPI("First Contact %", f"{ov['first_contact_pct']}%"),
              KPI("Second Ball %", f"{ov['second_ball_pct']}%"),
              KPI("Retention %", f"{ov['retention_pct']}%"),
              KPI("Success Rate", f"{dr['success_rate']}%")])


def _key_findings(overview: dict, intel: Any, dangerous: list) -> Section | None:
    idx = {}
    if intel:
        for i in (list(intel.offensive_tendencies) + list(intel.defensive_tendencies)
                  + list(intel.insights)):
            idx[i.id] = i
    rows: list[list[Any]] = []

    def add(label, insight_id):
        i = idx.get(insight_id)
        if i:
            rows.append([label, i.text, f"{int(i.confidence * 100)}%"])

    add("Top Threat", "ins_most_dangerous")
    add("Top Opportunity", "ins_highest_conversion")
    if dangerous:
        d = dangerous[0]
        rows.append(["Most Dangerous Player", f"{d['player']} — {d['goals']} goals, "
                     f"{d['first_contacts']} first contacts", "—"])
    add("Weakest Area", "def_vulnerable_zone")
    add("Most Repeated Routine", "ins_most_used")
    add("Most Successful Routine", "ins_highest_conversion")
    add("Most Dangerous Delivery", "off_delivery_type")
    add("Best Attacking Zone", "ins_best_zone")
    if overview["overview"].get("xg"):
        rows.append(["Total xG", str(overview["overview"]["xg"]), "—"])
    if not rows:
        return None
    return Section(id="mp_findings", title="Key Findings",
                   tables=[Table(title="Ranked findings",
                                 columns=["Finding", "Detail", "Confidence"], rows=rows)])


def _category_section(key: str, label: str, ov: dict) -> Section:
    o = ov["overview"]
    return Section(
        id=f"mp_{key}", title=label,
        kpis=[KPI("Count", str(o["total"])), KPI("Goals", str(o["goals"])),
              KPI("Shots", str(o["shots"])), KPI("Shot %", f"{o['shot_pct']}%"),
              KPI("First Contact %", f"{o['first_contact_pct']}%"), KPI("xG", str(o["xg"]))],
        subtitle="Charts and heatmaps follow in the report body / appendix.")


def _dangerous_players(dangerous: list[dict]) -> Section:
    rows = [[d["player"], d["goals"], d["shots"], d["first_contacts"]] for d in dangerous[:10]]
    return Section(id="mp_players", title="Dangerous Players",
                   tables=[Table(title="Threat ranking",
                                 columns=["Player", "Goals", "Shots", "First contacts"], rows=rows)])


def _routine_library(intel: Any) -> Section:
    rows = [[c.label, c.size, f"{c.conversion_pct}%", c.xg, f"{int(c.confidence * 100)}%"]
            for c in intel.clusters]
    routine_rows = [[ROUTINE_LABELS.get(r, r), n]
                    for r, n in sorted(intel.routines.items(), key=lambda kv: -kv[1])]
    return Section(id="mp_routines", title="Routine Library",
                   tables=[Table(title="Clusters",
                                 columns=["Routine", "Size", "Conversion", "xG", "Confidence"], rows=rows),
                           Table(title="Detected routines",
                                 columns=["Routine", "Count"], rows=routine_rows)])


def _intelligence_groups(intel: Any, pen_intel: Any) -> list[Section]:
    groups: list[tuple[str, str, list]] = [
        ("mp_intel_attack", "Intelligence — Attack",
         list(intel.offensive_tendencies) + list(intel.insights)),
        ("mp_intel_defence", "Intelligence — Defence", list(intel.defensive_tendencies)),
    ]
    if pen_intel:
        groups.append(("mp_intel_penalty", "Intelligence — Penalty",
                       list(pen_intel.shooter_insights) + list(pen_intel.team_insights)))
        groups.append(("mp_intel_gk", "Intelligence — Goalkeeper",
                       list(pen_intel.goalkeeper_insights)))
    out = []
    for sid, title, items in groups:
        if items:
            out.append(Section(id=sid, title=title,
                               insights=[RInsight(f"{i.title}: {i.text}", _kind(i.kind)) for i in items]))
    return out


def _recommendations(recs: list) -> Section:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    rows = [[r.priority.upper(), r.action, r.rationale, f"{int(r.confidence * 100)}%",
             "; ".join(r.evidence)[:80], ", ".join(r.visualization_references)]
            for r in sorted(recs, key=lambda r: order.get(r.priority, 9))]
    return Section(id="mp_recs", title="Recommendations",
                   tables=[Table(title="Coach recommendations (by priority)",
                                 columns=["Priority", "Action", "Why", "Confidence",
                                          "Evidence", "Visuals"], rows=rows)])


def _training_focus(recs: list) -> Section:
    seen, rows = set(), []
    for r in recs:
        obj = training_objective(r.action, r.rationale)
        if obj not in seen:
            seen.add(obj)
            rows.append([obj, r.action])
    return Section(id="mp_training", title="Training Focus",
                   tables=[Table(title="Coaching objectives",
                                 columns=["Objective", "Derived from"], rows=rows)])


def _video_library(videos: dict[str, list[str]]) -> Section:
    md = []
    for group, urls in videos.items():
        md.append(f"**{group}**")
        md.extend(f"- [{_provider(u)}]({u})" for u in urls)
    return Section(id="mp_videos", title="Video Library", markdown="\n".join(md))


def _appendix(embeds: list[Embed]) -> Section:
    rows = [[e.title, e.viz_id] for e in embeds]
    return Section(id="mp_appendix", title="Appendix — Visualizations",
                   subtitle="Every embedded visualization in this report.",
                   tables=[Table(title="Visualizations", columns=["Title", "Visualization"], rows=rows)])


# ------------------------------------------------------------------ helpers
def _kind(kind: str) -> str:
    return kind if kind in ("neutral", "success", "warning", "danger") else "neutral"


def _provider(url: str) -> str:
    u = url.lower()
    for name in ("youtube", "youtu.be", "hudl", "vimeo", "catapult", "wyscout", "veo"):
        if name in u:
            return name.replace("youtu.be", "youtube").title()
    return "Video"


def _collect_videos(svc: Any, user: Any, filt: SetPieceFilter,
                    workspace_id: str | None) -> dict[str, list[str]]:
    videos: dict[str, list[str]] = {}
    try:
        for sp in svc.search(user, filters=filt.to_repo_filters() or None,
                             workspace_id=workspace_id):
            if sp.video_url:
                group = SET_PIECE_TYPE_LABELS.get(sp.type, sp.type)
                videos.setdefault(group, [])
                if sp.video_url not in videos[group]:
                    videos[group].append(sp.video_url)
    except Exception:
        return {}
    return videos
