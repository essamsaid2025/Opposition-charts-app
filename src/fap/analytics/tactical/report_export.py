"""P3 export adapter — renders an :class:`OppositionReport` through the EXISTING
reports engine (``fap.reports``). It maps the report onto a ``ReportDocument``
(Cover + flow Sections) and hands it to the existing exporter registry
(HTML / Markdown / PDF / DOCX / PPTX). No second export engine, no second layout
engine: the report model stays renderer-independent and reuses all current
infrastructure.

Charts are references by default (the tactical question + the registry viz hint).
A caller that already has the running visualization engine may pass pre-rendered
PNGs in ``chart_images`` (hint -> bytes); they are embedded as real chart images.
"""
from __future__ import annotations

import base64

from fap.analytics.tactical.report import OppositionReport


def _md_lines(title_level: str, lines) -> str:
    return "\n".join(str(x) for x in lines)


def to_report_document(report: OppositionReport, *, chart_images: dict[str, bytes] | None = None):
    """Convert an OppositionReport into the existing ``fap.reports.ReportDocument``."""
    from fap.reports.models import Chart, Cover, Insight, ReportDocument, Section

    m = report.metadata
    cover = Cover(title=m.title, subtitle=(f"Opponent: {report.subject}" if report.subject else ""),
                  opponent=m.opponent or report.subject, competition=m.competition, match_date=m.date,
                  analyst=m.analyst, organization=m.team, generated_at=m.generated_at,
                  template_id="opposition_scouting")
    sections: list[Section] = []
    chart_images = chart_images or {}

    inc = set(report.included)

    def add(sid: str, title: str, markdown: str = "", insights=None, chart_hint: str = "",
            chart_q: str = "") -> None:
        charts = []
        if chart_hint and chart_hint in chart_images:
            charts.append(Chart(viz_id=chart_hint, title=chart_q,
                                image_b64=base64.b64encode(chart_images[chart_hint]).decode("ascii")))
        sections.append(Section(id=sid, title=title, markdown=markdown.strip(),
                                insights=list(insights or []), charts=charts))

    # ---- Executive Summary ----
    if "executive_summary" in inc and report.executive_summary:
        md = "\n".join(f"- **{s.heading}:** {s.text}" for s in report.executive_summary)
        add("executive_summary", "Executive Summary", md)
    if "key_takeaways" in inc and report.key_takeaways:
        md = "\n\n".join(f"### {i+1}. {t.title}  _({t.confidence})_\n{t.observation}\n\n"
                         f"_Why it matters:_ {t.why_it_matters}"
                         for i, t in enumerate(report.key_takeaways))
        add("key_takeaways", "Key Takeaways", md)

    # ---- Tactical DNA sections ----
    for s in report.sections:
        if s.id not in inc and "tactical_dna" not in inc:
            continue
        if s.available:
            md = f"**{s.headline}**\n\n" + "\n".join(f"- {ln}" for ln in s.lines)
            if s.chart_question:
                md += f"\n\n_Supporting visual — {s.chart_question}_"
            add(s.id, s.title, md, chart_hint=s.chart_hint, chart_q=s.chart_question)
        else:
            add(s.id, s.title, f"_{s.reason}_")

    # ---- Vulnerabilities (observation vs implication kept separate) ----
    if "vulnerabilities" in inc:
        if report.vulnerabilities:
            blocks = []
            for v in report.vulnerabilities:
                b = f"### {v.heading}  _({v.confidence})_\n**Observation:** {v.observation}"
                if v.implication:
                    b += f"\n\n**Tactical implication:** {v.implication}"
                blocks.append(b)
            add("vulnerabilities", "Potential Vulnerabilities", "\n\n".join(blocks))
        else:
            add("vulnerabilities", "Potential Vulnerabilities",
                "_No high-confidence vulnerability identified from the available evidence._")

    # ---- Tactical Evolution ----
    if "tactical_evolution" in inc and report.evolution:
        rows = []
        for t in report.evolution:
            bit = f"- **{t.label}** — {t.classification}, {t.recurrence} observed matches"
            if t.trend != "—":
                bit += f", trend {t.trend}"
            if t.delta_pp is not None:
                bit += f"; current {t.current_display} vs baseline {t.baseline_display} ({t.delta_pp:+g} pp)"
            rows.append(bit)
        add("tactical_evolution", "Tactical Evolution", "\n".join(rows))

    # ---- Key Players ----
    if "key_players" in inc and report.key_players:
        rows = [f"- **{p.name}** — {p.role} _({p.confidence})_"
                + (f"  \n  {' · '.join(p.metrics)}" if p.metrics else "") for p in report.key_players]
        add("key_players", "Key Players", "\n".join(rows))

    # ---- Strengths ----
    if "strengths" in inc and report.strengths:
        rows = [f"- **{s.heading}** — {s.observation} _({s.confidence})_" for s in report.strengths]
        add("strengths", "Key Strengths", "\n".join(rows))

    # ---- Focus Points ----
    if "focus_points" in inc and report.focus_points:
        blocks = []
        for i, f in enumerate(report.focus_points):
            b = f"### Focus Point {i+1:02d}: {f.title}\n_Evidence:_ {f.evidence_text}"
            if f.consistency:
                b += f"\n\n_Consistency:_ {f.consistency}"
            if f.implication:
                b += f"\n\n_Implication:_ {f.implication}"
            blocks.append(b)
        add("focus_points", "Match-specific Focus Points", "\n\n".join(blocks))

    # ---- Set Pieces ----
    if "set_pieces" in inc and report.set_pieces is not None:
        sp = report.set_pieces
        add("set_pieces", "Set Pieces",
            (f"**{sp.headline}**\n\n" + "\n".join(f"- {ln}" for ln in sp.lines)) if sp.available
            else f"_{sp.reason}_")

    # ---- Data Quality ----
    if "data_quality" in inc and report.data_quality:
        cov = "\n".join(f"- {c.label}: **{c.status}**" for c in report.data_quality)
        if report.excluded_matches:
            cov += "\n\n_Excluded matches:_ " + "; ".join(
                f"{mid} ({reason})" for mid, reason in report.excluded_matches)
        ins = [Insight(text="Insufficient/unavailable matches are excluded from trends, never counted "
                            "as zero.", kind="neutral")]
        add("data_quality", "Data Quality & Coverage", cov, insights=ins)

    return ReportDocument(id=f"opp_{_slug(m.title)}", title=m.title, template_id="opposition_scouting",
                          cover=cover, sections=sections,
                          meta={"kind": "opposition_scouting", "subject": report.subject})


def render_report(report: OppositionReport, fmt: str = "html", *,
                  chart_images: dict[str, bytes] | None = None, branding=None):
    """Render via the EXISTING exporter registry. Returns the engine's ``RenderedReport``
    (content bytes + mime + filename + text). Raises the engine's own error if a format's
    optional dependency is unavailable — we never fake output."""
    from fap.reports.exporters import exporter_registry

    doc = to_report_document(report, chart_images=chart_images)
    exporter = next((e() for e in exporter_registry if getattr(e, "fmt", "") == fmt), None)
    if exporter is None:
        raise ValueError(f"No report exporter registered for format '{fmt}'.")
    return exporter.render(doc, branding)


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (s or "").strip().lower()).strip("_") or "report"
