"""Premium Player Report — the recruitment-dossier document builder (P4.7).

PURE and renderer-independent: it maps a plain data dict (assembled by
``ScoutingService`` from the EXISTING profile/fit/notes/video/evidence/rating
services) plus PRE-RENDERED chart/QR PNG bytes onto the canonical
``fap.reports.ReportDocument`` (Cover + flow Sections). It reuses the existing
report engine end to end — the same exporter registry the Standard report and the
Open Play / Set Piece reports use — so there is NO second report/PDF engine.

Hard rules (mirrors the P4.7 data rules): never fabricate a metric, a chart, a
video link, a QR code, a rating, a note or a recommendation. A section with no data
is omitted or shown as a clean empty state; the document always renders.

    ScoutingService (existing data + pre-rendered PNGs)
        -> build_premium_document(data, chart_images=..., brand=...)
        -> ReportDocument  -> existing exporter registry -> PDF / HTML / MD
"""
from __future__ import annotations

import base64
from typing import Any

TEMPLATE_ID = "premium_scouting"
META_KIND = "premium_scouting"

# a fixed, professional order for the automatic charts (only those present render)
CHART_ORDER: tuple[str, ...] = ("pizza", "radar", "bar", "percentile", "scatter", "comparison")
CHART_TITLES: dict[str, str] = {
    "pizza": "Metric Pizza", "radar": "Attribute Radar", "bar": "Key Metrics",
    "percentile": "Population Percentiles", "scatter": "Metric Relationship",
    "comparison": "Profile Comparison"}


def _b64(png: bytes | None) -> str:
    return base64.b64encode(png).decode("ascii") if png else ""


def _present(v: Any) -> bool:
    return v not in (None, "", [], {}, 0)


def build_premium_document(data: dict[str, Any], *, chart_images: dict[str, bytes] | None = None,
                           brand: dict[str, str] | None = None,
                           options: dict[str, Any] | None = None):
    """Build the premium ``ReportDocument`` from a plain data dict + pre-rendered PNGs."""
    from fap.reports.models import Chart, Cover, Insight, KPI, ReportDocument, Section, Table

    chart_images = chart_images or {}
    options = options or {}
    include_charts = options.get("include_charts", True)
    rating = str(data.get("analyst_rating") or "").strip().upper()
    fit = data.get("fit")
    name = data.get("display_name") or data.get("name") or "Player"
    prof_name = data.get("recruitment_profile_name") or ""

    # ---- cover ----
    subtitle = "  ·  ".join(x for x in (data.get("position"), prof_name) if x)
    cover = Cover(
        title=name, subtitle=subtitle, player=name, club=data.get("club") or "",
        competition=data.get("league") or "", analyst=data.get("analyst") or "",
        generated_at=data.get("generated_at") or "",
        version=(f"Rating {rating}" if rating else ""),
        cover_image=data.get("profile_image_id") or "",
        club_logo=data.get("club_logo_id") or "", template_id=TEMPLATE_ID)

    sections: list[Section] = []

    def fit_value() -> str:
        if fit and fit.get("available"):
            return f"{float(fit['score']):.0f}%"
        return "Unavailable"

    # ---- 1) Recruitment Decision (KPIs) ----
    decision_kpis = [KPI(label="Analyst Rating", value=rating or "—"),
                     KPI(label="Profile Fit", value=fit_value()),
                     KPI(label="Status", value=data.get("status_label") or "—"),
                     KPI(label="Priority", value=data.get("priority_label") or "—")]
    dec_lines = []
    if data.get("operational_id"):
        dec_lines.append(f"- **Operational ID:** {data['operational_id']}")
    if data.get("type_label"):
        dec_lines.append(f"- **Pathway:** {data['type_label']}")
    if prof_name:
        dec_lines.append(f"- **Recruitment profile:** {prof_name}")
    if data.get("source_name"):
        dec_lines.append(f"- **Data source:** {data['source_name']}")
    sections.append(Section(id="decision", title="Recruitment Decision",
                            kpis=decision_kpis, markdown="\n".join(dec_lines)))

    # ---- 2) Player Profile (only fields that exist) ----
    rows: list[list[Any]] = []

    def field(label: str, value: Any) -> None:
        if _present(value):
            rows.append([label, str(value)])
    field("Name", data.get("name"))
    field("Operational ID", data.get("operational_id"))
    field("Age", data.get("age"))
    field("Nationality", data.get("nationality"))
    field("Position", ", ".join(data.get("positions") or []) or data.get("position"))
    field("Preferred Foot", (data.get("foot") or "").title() if data.get("foot") not in (None, "", "unknown") else "")
    field("Height", f"{data['height_cm']} cm" if _present(data.get("height_cm")) else "")
    field("Weight", f"{data['weight_kg']} kg" if _present(data.get("weight_kg")) else "")
    field("Contract Until", data.get("contract"))
    field("Shirt", f"#{data['shirt']}" if _present(data.get("shirt")) else "")
    field("Club", data.get("club"))
    field("League", data.get("league"))
    field("Recruitment Profile", prof_name)
    field("Status", data.get("status_label"))
    field("Priority", data.get("priority_label"))
    field("Analyst Rating", rating)
    if rows:
        sections.append(Section(id="profile", title="Player Profile",
                                tables=[Table(columns=["Field", "Value"], rows=rows)]))

    # ---- 3) Recruitment Profile & Fit ----
    if fit is not None:
        if fit.get("available"):
            md = (f"**{prof_name or 'Recruitment profile'}** — data-driven fit "
                  f"**{float(fit['score']):.0f}%** ({fit.get('mode', 'fit')}).")
            matched = list(fit.get("matched") or [])
            if matched:
                md += "\n\nMatched metric concepts:\n" + "\n".join(f"- {m}" for m in matched[:12])
            sections.append(Section(id="fit", title="Recruitment Profile & Fit", markdown=md,
                                    insights=[Insight(text="Recruitment fit is data-driven "
                                              "compatibility, distinct from the analyst rating.",
                                              kind="neutral")]))
        else:
            sections.append(Section(
                id="fit", title="Recruitment Profile & Fit",
                markdown=f"**Profile fit:** Unavailable.\n\n_Reason: "
                         f"{fit.get('reason') or 'insufficient compatible metrics'}._"))

    # ---- 4) Visual Analysis (automatic charts; never fabricated) ----
    if include_charts:
        charts = []
        for key in CHART_ORDER:
            png = chart_images.get(key)
            if png:
                charts.append(Chart(viz_id=f"scouting_{key}", title=CHART_TITLES.get(key, key),
                                    image_b64=_b64(png)))
        if charts:
            src = data.get("source_name")
            sub = f"Player-scoped from {src}" if src else "Player-scoped metrics"
            sections.append(Section(id="visual", title="Visual Analysis", subtitle=sub,
                                    charts=charts))
        else:
            sections.append(Section(id="visual", title="Visual Analysis",
                                    markdown="_No visualizations are available for this player._"))

    # ---- 5) Strengths / Areas to Monitor (observation only) ----
    strengths = data.get("strengths") or []
    dev = data.get("dev_areas") or []
    if strengths or dev:
        blocks = []
        if strengths:
            blocks.append("**Strengths**\n" + "\n".join(
                f"- {s['name']} — {s['percentile']}th percentile" for s in strengths))
        if dev:
            blocks.append("**Areas to Monitor**\n" + "\n".join(
                f"- {s['name']} — {s['percentile']}th percentile" for s in dev))
        sections.append(Section(
            id="strengths", title="Strengths & Areas to Monitor", markdown="\n\n".join(blocks),
            insights=[Insight(text="Percentile observations from the linked dataset — not a "
                      "tactical conclusion.", kind="neutral")]))

    # ---- 6) Scouting Notes (ALL notes) ----
    notes = data.get("notes") or []
    if notes:
        blocks = []
        for n in notes:
            head = " — ".join(x for x in (n.get("date"), n.get("author")) if x)
            cat = f"  _[{n['category']}]_" if n.get("category") else ""
            blocks.append((f"**{head}**{cat}\n\n" if head or cat else "") + (n.get("text") or ""))
        sections.append(Section(id="notes", title="Scouting Notes", markdown="\n\n".join(blocks)))
    else:
        sections.append(Section(id="notes", title="Scouting Notes",
                                markdown="_No scouting notes recorded._"))

    # ---- 7) Video Evidence (+ QR for valid external URLs) ----
    videos = data.get("videos") or []
    if videos:
        for i, v in enumerate(videos, 1):
            lines = [f"**Video {i:02d} — {v.get('title') or 'Video'}**"]
            meta = " · ".join(x for x in (v.get("match_id"), v.get("match_date"),
                                          v.get("dataset_name"), v.get("provider")) if x)
            if meta:
                lines.append(meta)
            charts = []
            qr_b64 = v.get("qr_b64")
            if qr_b64:
                lines.append(f"Scan to watch — {v.get('url')}")
                charts.append(Chart(viz_id=f"qr_{i}", title="Scan to watch", image_b64=qr_b64))
            elif v.get("url"):
                lines.append(f"Watch: {v['url']}")
            else:
                lines.append("_Video available in FAP._")
            actions = v.get("key_actions") or []
            if actions:
                lines.append("\nKey actions:\n" + "\n".join(
                    f"- {a.get('time', '')} — {a.get('event_type', 'event')}" for a in actions))
            sections.append(Section(id=f"video_{i}", title="Video Evidence" if i == 1 else "",
                                    markdown="\n\n".join(lines), charts=charts))
    else:
        sections.append(Section(id="video", title="Video Evidence",
                                markdown="_No linked videos recorded._"))

    # ---- 8) Match / Tagging Evidence ----
    matches = data.get("matches") or []
    if matches:
        blocks = []
        for m in matches:
            head = " · ".join(x for x in (m.get("opponent") or m.get("match_id"),
                                          m.get("match_date"), m.get("competition")) if x)
            line = f"**{head}** — {m.get('event_count', 0)} tagged action(s)"
            tags = m.get("tags") or []
            if tags:
                line += "\n" + "\n".join(f"- {t.get('time', '')} — {t.get('label', '')}" for t in tags)
            blocks.append(line)
        sections.append(Section(id="evidence", title="Match Evidence", markdown="\n\n".join(blocks)))

    # ---- 9) Recruitment Summary (factual only — no fabricated verdict) ----
    summary_kpis = [KPI(label="Analyst Rating", value=rating or "—"),
                    KPI(label="Profile Fit", value=fit_value()),
                    KPI(label="Status", value=data.get("status_label") or "—"),
                    KPI(label="Priority", value=data.get("priority_label") or "—"),
                    KPI(label="Pathway", value=data.get("type_label") or "—")]
    summary_md = (f"Recruitment assessment for **{name}**"
                  + (f" ({prof_name})" if prof_name else "") + ".")
    sections.append(Section(
        id="summary", title="Recruitment Summary", kpis=summary_kpis, markdown=summary_md,
        insights=[Insight(text="Factual recruitment data and analyst notes only; no automated "
                  "recommendation is generated.", kind="neutral")]))

    doc = ReportDocument(
        id=data.get("report_id") or "premium", title=f"Premium Player Report — {name}",
        template_id=TEMPLATE_ID, cover=cover, sections=sections,
        meta={"kind": META_KIND, "player_id": data.get("player_id", ""),
              "source_dataset_id": data.get("source_dataset_id", ""),
              "source_dataset_name": data.get("source_name", ""),
              "analyst_rating": rating})
    _apply_branding(doc, brand)
    return doc


def _apply_branding(document, brand: dict[str, str] | None) -> None:
    """Apply the report-only brand colours to the cover design via the EXISTING
    PublishSettings (professional preset). Never touches the global app/chart themes.
    Missing/invalid colours fall back to the professional preset (FAP-neutral)."""
    try:
        from fap.reports.publishing import PublishSettings, preset
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
        pass                                       # branding is optional; never block a report


__all__ = ["build_premium_document", "TEMPLATE_ID", "META_KIND", "CHART_ORDER"]
