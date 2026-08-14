"""Set Piece report export adapter (P3.1 refactor).

Maps a :class:`SetPieceReport` onto the EXISTING ``fap.reports.ReportDocument`` and
renders it through the shared exporter path (``report_export.render_document``) — the
same export infrastructure as the Open Play report, but a SEPARATE document with a
distinct filename. No second export engine.

Set-piece charts are kept text-based here: the set-piece visualizations live in the
``SetPieceService`` (``render_visual``), not the Open Play registry, so they are not
forced through it. A future pass can attach service-rendered PNGs via ``chart_images``.
"""
from __future__ import annotations

from fap.analytics.tactical.report_export import render_document
from fap.analytics.tactical.setpiece_report import SetPieceReport


def to_setpiece_document(report: SetPieceReport):
    from fap.reports.models import Cover, Insight, ReportDocument, Section, Table

    m = report.metadata
    cover = Cover(title=m.title, subtitle=(f"Opponent: {report.subject}" if report.subject else ""),
                  opponent=m.opponent or report.subject, competition=m.competition, match_date=m.match,
                  analyst=m.analyst, organization=m.team, generated_at=m.generated_at,
                  template_id="setpiece_scouting")
    sections: list[Section] = []
    inc = set(report.included)

    def add(sid, title, markdown="", insights=None, table=None):
        tables = []
        if table is not None:
            cols, rows = table
            tables.append(Table(title="", columns=list(cols), rows=[list(r) for r in rows]))
        sections.append(Section(id=sid, title=title, markdown=markdown.strip(),
                                insights=list(insights or []), tables=tables))

    if not report.available:
        add("unavailable", "Set Pieces",
            "\n".join(f"_{n}_" for n in report.notices) or "_Set-piece analysis unavailable._")
        return ReportDocument(id=f"sp_{_slug(m.title)}", title=m.title, template_id="setpiece_scouting",
                              cover=cover, sections=sections,
                              meta={"kind": "setpiece_scouting", "subject": report.subject})

    # ---- structured sections (overview + categories) ----
    for s in report.sections:
        if s.id not in inc:
            continue
        if s.available:
            md = (f"**{s.headline}**\n\n" if s.headline else "") + "\n".join(f"- {ln}" for ln in s.lines)
            add(s.id, s.title, md, table=((s.table_columns, s.table_rows) if s.table_rows else None))
        else:
            add(s.id, s.title, f"_{s.reason}_")

    if "key_takers" in inc and report.key_takers:
        add("key_takers", "Key Takers", "\n".join(f"- {t}" for t in report.key_takers))
    if "routines" in inc and report.routines:
        add("routines", "Repeated Routines", "\n".join(f"- {r}" for r in report.routines))

    if "strengths" in inc:
        if report.strengths:
            add("strengths", "Set-Piece Strengths",
                "\n\n".join(f"### {s.heading}\n{s.observation}" for s in report.strengths))
    if "weaknesses" in inc:
        if report.weaknesses:
            blocks = []
            for w in report.weaknesses:
                b = f"### {w.heading}\n**Observation:** {w.observation}"
                if w.implication:
                    b += f"\n\n**Implication:** {w.implication}"
                blocks.append(b)
            add("weaknesses", "Potential Weaknesses", "\n\n".join(blocks))
        else:
            add("weaknesses", "Potential Weaknesses",
                "_No high-confidence set-piece weakness identified from the available data._")
    if "match_prep" in inc and report.match_prep:
        blocks = [f"### {i+1}. {p.heading}\n{p.observation}"
                  + (f"\n\n_{p.implication}_" if p.implication else "")
                  for i, p in enumerate(report.match_prep)]
        add("match_prep", "Match Preparation Points", "\n\n".join(blocks))

    if "data_quality" in inc and report.data_quality:
        cov = "\n".join(f"- {c.label}: **{c.status}**" for c in report.data_quality)
        add("data_quality", "Set-Piece Data Coverage", cov)

    return ReportDocument(id=f"sp_{_slug(m.title)}", title=m.title, template_id="setpiece_scouting",
                          cover=cover, sections=sections,
                          meta={"kind": "setpiece_scouting", "subject": report.subject})


def render_setpiece_report(report: SetPieceReport, fmt: str = "html", *, branding=None):
    """Render the set-piece report through the shared exporter path."""
    return render_document(to_setpiece_document(report), fmt, branding)


def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in (s or "").strip().lower()).strip("_") or "report"
