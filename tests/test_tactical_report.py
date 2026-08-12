"""P3 — Opposition Scouting Report tests.

Covers report generation (complete / limited / missing transitions / missing players /
no vulnerabilities / multi-match / current-vs-baseline), evidence traceability to valid
P0 ids, player-scoped evidence, P2.1 insufficient≠zero in the report narrative, honest
missing-data states, determinism, serialization, section selection, no unsupported
claims, and export through the EXISTING report engine (Markdown/HTML/PDF).
"""
import json

import pandas as pd

from fap.analytics.tactical import (
    ReportMetadata, TacticalInsightEngine, analyze, build_evolution, build_profile,
    build_report, build_report_from_frame, render_report, to_report_document,
)
from fap.openplay import add_derived_columns
from fap.pipeline.schema import coerce_schema

FIXED = ReportMetadata(title="Opp Report", opponent="Opp", team="Us", competition="League",
                       generated_at="2026-01-01 00:00")


# ------------------------------------------------------------------ builders
def _derive(rows):
    return add_derived_columns(coerce_schema(pd.DataFrame(rows)))


def _ev(kind, x, y, ex, ey, *, player="P", team="Opp", match="m1", outcome="successful",
        minute=0, second=0, seq=None):
    r = {"event_type": kind, "x": x, "y": y, "end_x": ex, "end_y": ey, "player": player,
         "team": team, "opponent": "Us", "minute": minute, "second": second, "period": 1,
         "match_id": match, "outcome": outcome}
    if seq is not None:
        r["sequence_id"] = str(seq)
    return r


def rich_rows(mid="m1", seq=True):
    rows, s = [], 0
    for k in range(30):
        s += 1
        sq = s if seq else None
        rows.append(_ev("recovery", 40, 15, 40, 15, player="D", match=mid, minute=k, second=0, seq=sq))
        rows.append(_ev("pass", 42, 15, 78, 15, player="Star", match=mid, minute=k, second=5, seq=sq))
    for i in range(40):                                   # right-side turnovers
        s += 1
        rows.append(_ev("pass", 50, 85, 62, 85, player="P5", match=mid, minute=i,
                        outcome=("unsuccessful" if i % 2 == 0 else "successful"),
                        seq=(s if seq else None)))
    if not seq:
        for r in rows:
            r.pop("sequence_id", None)
            r.pop("minute", None)
            r.pop("second", None)
    return rows


def balanced_rows(mid="m1"):
    rows = []
    for lane, c, y in [("left", 30, 15.0), ("central", 26, 50.0), ("right", 24, 85.0)]:
        for i in range(c):
            rows.append(_ev("pass", 30, y, 58, y, player=f"P{i%6}", match=mid, minute=i))
    return rows


def multi_rows(shares):
    rows = []
    for k, sh in enumerate(shares):
        nl = int(80 * sh); nc = (80 - nl) // 2; nr = 80 - nl - nc
        for lane, c, y in [("left", nl, 15.0), ("central", nc, 50.0), ("right", nr, 85.0)]:
            for i in range(c):
                rows.append(_ev("pass", 30, y, 58, y, player=("Star" if i < c // 2 and lane == "left"
                                                              else f"P{i%6}"), match=f"m{k+1}", minute=i))
    return rows


def _report(frame, **kw):
    rep = analyze(frame)
    return build_report(rep, build_profile(rep), kw.pop("evo", None), metadata=FIXED, **kw), rep


# ================================================================ generation
def test_report_complete_data():
    report, rep = _report(_derive(rich_rows()))
    assert report.subject == "Opp"
    assert report.executive_summary and report.key_takeaways
    assert 3 <= len(report.key_takeaways) <= 6
    assert report.section("transitions").available
    assert report.vulnerabilities and report.key_players
    assert report.focus_points


def test_report_limited_evidence():
    report, _ = _report(_derive(balanced_rows()[:12]))       # tiny
    assert report.limited_evidence
    assert report.overall_confidence in ("Low", "Medium")


def test_missing_transitions_section_is_honest():
    report, _ = _report(_derive(rich_rows(seq=False)))
    t = report.section("transitions")
    assert not t.available
    assert "sequence" in t.reason.lower() or "timestamp" in t.reason.lower()


def test_missing_players_no_player_section():
    frame = _derive(rich_rows()).drop(columns=["player"])
    report, _ = _report(frame)
    assert report.key_players == ()


def test_no_vulnerabilities_is_valid_conclusion():
    report, _ = _report(_derive(balanced_rows()))
    assert report.vulnerabilities == ()


def test_multi_match_evolution_in_report():
    frame = _derive(multi_rows([0.60, 0.62, 0.61, 0.63]))
    report = build_report_from_frame(frame, metadata=FIXED, current_match="m4")
    assert report.evolution
    labels = {t.label for t in report.evolution}
    assert "Left-sided progression" in labels


# ================================================================ traceability
def test_every_report_claim_traces_to_valid_p0_ids():
    frame = _derive(rich_rows())
    rep = analyze(frame)
    valid = {i.id for i in rep.insights}
    report = build_report(rep, build_profile(rep), build_evolution(frame), metadata=FIXED)
    refs = set()
    for t in report.key_takeaways:
        refs |= set(t.evidence.insight_ids)
    for s in report.sections:
        refs |= set(s.evidence.insight_ids)
    for v in report.vulnerabilities:
        refs |= set(v.evidence.insight_ids)
    for p in report.key_players:
        refs |= set(p.evidence.insight_ids)
    for f in report.focus_points:
        refs |= set(f.evidence.insight_ids)
    for e in report.evolution:
        refs |= set(e.evidence.insight_ids)
    assert refs and refs <= valid


# ================================================================ player scope
def test_player_evidence_preserves_player_scope():
    # multi-match so the evolution surfaces player patterns with match-scoped evidence
    frame = _derive(multi_rows([0.60, 0.62, 0.61, 0.63]))
    rep = analyze(frame)
    by_id = {i.id: i for i in rep.insights}
    report = build_report(rep, build_profile(rep), build_evolution(frame), metadata=FIXED)
    kp = next(p for p in report.key_players if p.name == "Star")
    iid = kp.evidence.insight_ids[0]
    # the underlying P0 insight carries the player scope used by _open_evidence
    assert "Star" in by_id[iid].supporting_viz.players
    # evolution player pattern carries a scoped evidence ref (match evidence pathway)
    player_trend = next((t for t in report.evolution if t.evidence.ref
                         and t.evidence.ref.players), None)
    assert player_trend is not None
    assert player_trend.evidence.ref.players == ("Star",)


# ================================================================ P2.1 semantics
def test_report_preserves_insufficient_not_zero():
    # 4 strong-left matches + 1 insufficient (short lateral passes)
    rows = multi_rows([0.60, 0.62, 0.61, 0.63])
    for i in range(45):
        rows.append(_ev("pass", 30, 15, 33, 15, player="P0", match="m5", minute=i))
    report = build_report_from_frame(_derive(rows), metadata=FIXED, current_match="m5")
    lp = next(t for t in report.evolution if t.label == "Left-sided progression")
    assert lp.recurrence == "4 / 4"                       # NOT 4 / 5
    assert lp.current_display == "insufficient"           # current match insufficient, never "0%"
    assert lp.delta_pp is None


# ================================================================ determinism / serialization
def test_report_is_deterministic():
    frame = _derive(rich_rows())
    rep = analyze(frame)
    prof = build_profile(rep)
    evo = build_evolution(frame)
    a = build_report(rep, prof, evo, metadata=FIXED).to_dict()
    b = build_report(rep, prof, evo, metadata=FIXED).to_dict()
    assert a == b


def test_report_serializable():
    report, _ = _report(_derive(rich_rows()), evo=None)
    s = json.dumps(report.to_dict())
    assert '"key_takeaways"' in s and "DataFrame" not in s


# ================================================================ section selection
def test_section_selection_filters_report():
    report, _ = _report(_derive(rich_rows()), include=("executive_summary", "key_players"))
    assert set(report.included) == {"executive_summary", "key_players"}
    doc = to_report_document(report)
    titles = {sec.title for sec in doc.sections}
    assert "Key Players" in titles
    assert "Potential Vulnerabilities" not in titles


# ================================================================ no unsupported claims
def test_report_has_no_unsupported_claims():
    report, _ = _report(_derive(rich_rows()), evo=None)
    blob = json.dumps(report.to_dict()).lower()
    for banned in ("4-3-3", "4-4-2", "3-5-2", "high press", "presses high",
                   "playmaker", "false nine", "press them here"):
        assert banned not in blob
    # "formation" may appear ONLY inside the explicit no-inference disclaimer
    assert "formation" not in blob or "formation and role assignments are not inferred" in blob


# ================================================================ export (existing engine)
def test_export_markdown_html_pdf_nonempty():
    report, _ = _report(_derive(rich_rows()), evo=None)
    for fmt, mime in [("markdown", "text/markdown"), ("html", "text/html"), ("pdf", "application/pdf")]:
        out = render_report(report, fmt)
        assert out.content and len(out.content) > 200
        assert out.mime == mime
        assert out.filename


def test_export_document_maps_sections():
    report, _ = _report(_derive(rich_rows()), evo=None)
    doc = to_report_document(report)
    assert doc.title == "Opp Report"
    assert doc.cover.opponent == "Opp"
    assert any(s.id == "executive_summary" for s in doc.sections)


# ================================================================ UI wiring
def test_report_panel_registered():
    from fap.ui.builtin import openplay_studio as S
    ids = [p[0] for p in S.PANELS["bottom"]]
    assert "report" in ids
