"""Player Evaluation Report — the professional squad-player dossier for the technical
director / head coach.

PURE and renderer-independent (mirrors :mod:`fap.scouting.premium_report`): it maps a
plain data dict assembled by ``TeamService`` from the EXISTING squad services
(profile / player_dashboard / progression / media / notes / evaluation) plus
PRE-RENDERED chart, heat-map and QR PNG bytes onto the canonical
``fap.reports.ReportDocument`` (Cover + flow Sections). It reuses the existing report
engine and exporter registry end to end — the SAME one the scouting and Open Play
reports use — so there is NO second report/PDF engine.

Hard rules: never fabricate a metric, a chart, a video link, a QR code or an
evaluation. The analyst's written evaluation is included verbatim (analyst-authored,
not generated). A section with no data is omitted or shown as a clean empty state; the
document always renders.
"""
from __future__ import annotations

import base64
from typing import Any

TEMPLATE_ID = "player_evaluation"
META_KIND = "team_player_evaluation"

# recommendation vocabulary (analyst picks one; shown verbatim)
RECOMMENDATIONS: dict[str, str] = {
    "continue": "Continue in current role",
    "develop": "Develop — targeted improvement plan",
    "loan": "Loan for game time",
    "promote": "Promote / step up",
    "monitor": "Monitor",
    "release": "Release / move on",
}


def _b64(png: bytes | None) -> str:
    return base64.b64encode(png).decode("ascii") if png else ""


def _present(v: Any) -> bool:
    return v not in (None, "", [], {}, 0)


def build_player_report_document(data: dict[str, Any], *,
                                 chart_images: dict[str, bytes] | None = None,
                                 saved_charts: list[dict[str, Any]] | None = None,
                                 brand: dict[str, str] | None = None,
                                 options: dict[str, Any] | None = None):
    """Build the Player Evaluation ``ReportDocument`` from a data dict + pre-rendered PNGs."""
    from fap.reports.models import Chart, Cover, Insight, KPI, ReportDocument, Section, Table

    chart_images = chart_images or {}
    saved_charts = saved_charts or []
    options = options or {}
    name = data.get("name") or "Player"
    team_name = data.get("team_name") or ""
    position = data.get("position") or ""
    ev = data.get("evaluation") or {}
    rating = str(ev.get("rating") or "").strip()

    # ---- cover ----
    subtitle = "  ·  ".join(x for x in (position, team_name) if x)
    cover = Cover(
        title=name, subtitle=subtitle, player=name, club=team_name,
        competition=data.get("competition") or "", analyst=data.get("analyst") or "",
        generated_at=data.get("generated_at") or "",
        version=(f"Evaluation {rating}" if rating else "Player Evaluation"),
        cover_image=data.get("profile_image_id") or "",
        club_logo=data.get("crest_image_id") or "", template_id=TEMPLATE_ID)

    sections: list[Section] = []
    dash = data.get("dashboard") or {}

    def _num(v: Any, dash_key: bool = False) -> str:
        return "—" if v in (None, "") else str(v)

    # ---- 1) Performance Summary (KPIs) ----
    pass_completion = dash.get("pass_completion")
    summary_kpis = [
        KPI(label="Appearances", value=_num(dash.get("appearances"))),
        KPI(label="Minutes", value=_num(dash.get("minutes")) if dash.get("appearances") else "—"),
        KPI(label="Goals", value=_num(dash.get("goals"))),
        KPI(label="Assists", value=_num(dash.get("assists"))),
        KPI(label="Pass %", value=(f"{pass_completion}%" if pass_completion is not None else "—")),
        KPI(label="Shots", value=_num(dash.get("shots"))),
    ]
    ctx = (f"{dash.get('team_matches', 0)} team match(es) · {dash.get('linked_matches', 0)} "
           f"with event data · {data.get('saved_chart_count', 0)} saved chart(s)")
    sections.append(Section(id="summary", title="Performance Summary", kpis=summary_kpis,
                            markdown=ctx))

    # ---- 2) Coach's Evaluation (analyst-authored; verbatim, never generated) ----
    if ev:
        blocks: list[str] = []
        rec_key = str(ev.get("recommendation") or "").strip().lower()
        rec = RECOMMENDATIONS.get(rec_key, ev.get("recommendation") or "")
        ev_kpis = [KPI(label="Overall rating", value=rating or "—"),
                   KPI(label="Recommendation", value=rec or "—")]
        if ev.get("summary"):
            blocks.append(str(ev["summary"]))
        if ev.get("strengths"):
            blocks.append("**Strengths**\n" + "\n".join(
                f"- {s}" for s in _as_list(ev["strengths"])))
        if ev.get("dev_areas"):
            blocks.append("**Areas to develop**\n" + "\n".join(
                f"- {s}" for s in _as_list(ev["dev_areas"])))
        meta = " — ".join(x for x in (ev.get("author"), ev.get("date")) if x)
        insights = [Insight(text=f"Assessment by {meta}." if meta else
                            "Analyst-authored assessment.", kind="neutral")]
        sections.append(Section(id="evaluation", title="Coach's Evaluation", kpis=ev_kpis,
                                markdown="\n\n".join(blocks) or "_No written assessment provided._",
                                insights=insights))

    # ---- 3) Player Profile (only fields that exist) ----
    rows: list[list[Any]] = []

    def field(label: str, value: Any) -> None:
        if _present(value):
            rows.append([label, str(value)])
    field("Name", name)
    field("Operational ID", data.get("operational_id"))
    field("Age", data.get("age"))
    field("Date of birth", data.get("date_of_birth"))
    field("Nationality", data.get("nationality"))
    field("Position", position)
    field("Secondary position", data.get("secondary_role"))
    field("Preferred foot", (data.get("foot") or "").title() if data.get("foot") else "")
    field("Height", f"{data['height_cm']} cm" if _present(data.get("height_cm")) else "")
    field("Weight", f"{data['weight_kg']} kg" if _present(data.get("weight_kg")) else "")
    field("Shirt", f"#{data['shirt']}" if _present(data.get("shirt")) else "")
    field("Joined", data.get("joined_date"))
    field("Contract until", data.get("contract"))
    field("Team", team_name)
    if rows:
        sections.append(Section(id="profile", title="Player Profile",
                                tables=[Table(columns=["Field", "Value"], rows=rows)]))

    # ---- 4) Development (trend chart + optional per-match table) ----
    dev_png = chart_images.get("development")
    dev_table = data.get("development_table") or []
    if dev_png or dev_table:
        charts = [Chart(viz_id="development", title="Development across matches",
                        image_b64=_b64(dev_png))] if dev_png else []
        tables = []
        if dev_table:
            cols = data.get("development_columns") or []
            tables = [Table(columns=cols, rows=dev_table)]
        sections.append(Section(id="development", title="Development",
                                subtitle="Per-match progression from the team's linked data",
                                charts=charts, tables=tables))

    # ---- 5) Form (last 5 vs season) ----
    form = data.get("form") or []
    if form:
        frows = [[f["label"], f["last5"], f["season"], f["trend"]] for f in form]
        sections.append(Section(
            id="form", title="Current Form",
            subtitle="Last 5 matches vs season average",
            tables=[Table(columns=["Metric", "Last 5", "Season", "Trend"], rows=frows)],
            insights=[Insight(text="Trend compares the last-5 average to the season average "
                      "for each metric.", kind="neutral")]))

    # ---- 6) Touch / Heat map ----
    heat_png = chart_images.get("heatmap")
    if heat_png:
        sections.append(Section(id="heatmap", title="Touch & Activity Map",
                                subtitle="Event positions aggregated across linked matches",
                                charts=[Chart(viz_id="heatmap", title="Touch & activity map",
                                              image_b64=_b64(heat_png))]))

    # ---- 7) Visual Analysis (all saved charts, grouped headings by match) ----
    if saved_charts:
        charts = []
        for i, ch in enumerate(saved_charts, 1):
            png = ch.get("png")
            if not png:
                continue
            title = ch.get("title") or "Visualization"
            if ch.get("match_label"):
                title = f"{title} — {ch['match_label']}"
            charts.append(Chart(viz_id=f"saved_{i}", title=title, image_b64=_b64(png)))
        if charts:
            sections.append(Section(id="visual", title="Visual Analysis",
                                    subtitle="Charts saved for this player", charts=charts))

    # ---- 8) Video Evidence (+ QR for external links) ----
    videos = data.get("videos") or []
    if videos:
        for i, v in enumerate(videos, 1):
            lines = [f"**Video {i:02d} — {v.get('title') or 'Video'}**"]
            if v.get("match_label"):
                lines.append(v["match_label"])
            charts = []
            if v.get("qr_b64"):
                lines.append(f"Scan to watch — {v.get('url')}")
                charts.append(Chart(viz_id=f"qr_{i}", title="Scan to watch", image_b64=v["qr_b64"]))
            elif v.get("url"):
                lines.append(f"Watch: {v['url']}")
            else:
                lines.append("_Uploaded video available in FAP._")
            sections.append(Section(id=f"video_{i}", title="Video Evidence" if i == 1 else "",
                                    markdown="\n\n".join(lines), charts=charts))

    # ---- 9) Notes (player + team) ----
    note_blocks: list[str] = []
    for n in (data.get("player_notes") or []):
        head = " — ".join(x for x in (n.get("date"), n.get("author")) if x)
        note_blocks.append((f"**{head}**\n\n" if head else "") + (n.get("text") or ""))
    for n in (data.get("team_notes") or []):
        head = " — ".join(x for x in ("Team note", n.get("date")) if x)
        note_blocks.append((f"**{head}**\n\n" if head else "") + (n.get("text") or ""))
    if note_blocks:
        sections.append(Section(id="notes", title="Notes", markdown="\n\n".join(note_blocks)))

    doc = ReportDocument(
        id=data.get("report_id") or "player_evaluation",
        title=f"Player Evaluation — {name}", template_id=TEMPLATE_ID,
        cover=cover, sections=sections,
        meta={"kind": META_KIND, "member_id": data.get("member_id", ""),
              "team_id": data.get("team_id", ""), "rating": rating})
    _apply_branding(doc, brand)
    return doc


def _as_list(v: Any) -> list[str]:
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    # split a free-text block on newlines / semicolons
    text = str(v or "")
    parts = [p.strip(" -•\t") for chunk in text.split("\n") for p in chunk.split(";")]
    return [p for p in parts if p]


def _apply_branding(document, brand: dict[str, str] | None) -> None:
    """Apply report-only brand colours to the cover via the EXISTING PublishSettings
    (professional preset). Never touches global app/chart themes."""
    try:
        from fap.reports.publishing import preset
        settings = preset("professional")
        b = {k: str(v).strip() for k, v in (brand or {}).items() if str(v or "").strip()}
        primary = b.get("primary")
        accent = b.get("accent") or primary
        if primary:
            settings.cover.overlay_color = primary
        if accent:
            settings.cover.accent_color = accent
        settings.write_to(document)
    except Exception:
        pass


__all__ = ["build_player_report_document", "TEMPLATE_ID", "META_KIND", "RECOMMENDATIONS"]
