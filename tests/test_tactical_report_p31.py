"""P3.1 tests (refactored) — Open Play and Set Piece are two SEPARATE reports.

Covers: the Open Play report contains no set-piece content; the dedicated SetPieceReport
generates from the existing set-piece analytics (complete / partial / none) with evidence
that traces to set-piece record ids and never to fake P0 insight ids; separate exports;
and the (unchanged) Open Play embedded-visual bridge with player/match scope + render-once.
"""
import json

import pandas as pd

from fap.analytics.tactical import (
    ReportMetadata, SetPieceReportMetadata, VisualPlan, analyze, build_evolution, build_profile,
    build_report, build_setpiece_report, plan_report_visuals, render_report, render_report_visuals,
    render_setpiece_report, to_report_document, to_setpiece_document,
)
from fap.openplay import add_derived_columns
from fap.pipeline.schema import coerce_schema
from fap.setpieces.models import SetPiece

FIXED = ReportMetadata(title="Opp Report", opponent="Opp", team="Us", generated_at="2026-01-01 00:00")
SP_FIXED = SetPieceReportMetadata(title="Opp Set Piece Report", opponent="Opp", generated_at="2026-01-01")


# ------------------------------------------------------------------ builders
def _derive(rows):
    return add_derived_columns(coerce_schema(pd.DataFrame(rows)))


def _ev(kind, x, y, ex, ey, *, player="P", match="m1", outcome="successful", minute=0):
    return {"event_type": kind, "x": x, "y": y, "end_x": ex, "end_y": ey, "player": player,
            "team": "Opp", "opponent": "Us", "minute": minute, "second": 0, "period": 1,
            "match_id": match, "outcome": outcome}


def multi_rows(shares):
    rows = []
    for k, sh in enumerate(shares):
        nl = int(80 * sh); nc = (80 - nl) // 2; nr = 80 - nl - nc
        for lane, c, y in [("left", nl, 15.0), ("central", nc, 50.0), ("right", nr, 85.0)]:
            for i in range(c):
                rows.append(_ev("pass", 30, y, 58, y,
                                player=("Star" if i < c // 2 and lane == "left" else f"P{i%6}"),
                                match=f"m{k+1}", minute=i))
    return rows


def att_corners(n, taker="Star"):
    return [SetPiece(id=f"ac{i}", phase="offensive", type="corner", side="left", taker=taker,
                     delivery_type="inswing", delivery_height="high",
                     outcome=("shot" if i % 3 == 0 else "cleared"), shot=(i % 3 == 0),
                     goal=(i == 0), retained=(i % 3 == 1), routine="near-post flick") for i in range(n)]


def def_corners(n, attack_first=0.8):
    return [SetPiece(id=f"dc{i}", phase="defensive", type="corner",
                     first_contact_team=("attack" if i < int(n * attack_first) else "defence"),
                     outcome="cleared") for i in range(n)]


def free_kicks(n, phase="offensive"):
    return [SetPiece(id=f"{phase}fk{i}", phase=phase, type="free_kick", taker="P5", outcome="cleared")
            for i in range(n)]


# ================================================================ Open Play: set pieces removed
def test_open_play_report_has_no_set_pieces():
    frame = _derive(multi_rows([0.6, 0.62]))
    rep = analyze(frame)
    report = build_report(rep, build_profile(rep), None, metadata=FIXED)
    d = report.to_dict()
    assert "set_pieces" not in d                        # the field is gone entirely
    assert "set_pieces" not in d["included"]
    assert "set piece" not in json.dumps(d).lower()     # no residual set-piece text/section


def test_open_play_export_has_no_set_piece_section():
    frame = _derive(multi_rows([0.6, 0.62]))
    rep = analyze(frame)
    doc = to_report_document(build_report(rep, build_profile(rep), None, metadata=FIXED))
    assert all(s.id != "set_pieces" for s in doc.sections)
    assert "Set Pieces" not in {s.title for s in doc.sections}


def test_open_play_core_sections_unchanged():
    frame = _derive(multi_rows([0.6, 0.62, 0.61]))
    rep = analyze(frame)
    report = build_report(rep, build_profile(rep), build_evolution(frame), metadata=FIXED)
    ids = {s.id for s in report.sections}
    assert {"progression", "final_third", "transitions", "recoveries"} <= ids
    assert report.executive_summary and report.key_takeaways


# ================================================================ Set Piece report
def test_setpiece_report_complete_data():
    sps = att_corners(14) + def_corners(10) + free_kicks(6)
    r = build_setpiece_report(sps, metadata=SP_FIXED)
    assert r.available and r.subject
    assert r.section("attacking_corners").available
    assert r.section("defensive_corners").available
    assert r.section("attacking_free_kicks").available
    assert not r.section("defensive_free_kicks").available    # honest: no data for that category
    assert r.key_takers and r.routines


def test_setpiece_report_partial_data():
    r = build_setpiece_report(att_corners(12), metadata=SP_FIXED)
    avail = [s.id for s in r.sections if s.available]
    assert "attacking_corners" in avail
    assert not r.section("defensive_corners").available
    assert not r.section("attacking_free_kicks").available


def test_setpiece_report_no_data_is_unavailable():
    r = build_setpiece_report([], metadata=SP_FIXED)
    assert not r.available
    assert r.notices and "unavailable" in r.notices[0].lower()


def test_setpiece_evidence_is_record_ids_not_fake_insight_ids():
    r = build_setpiece_report(att_corners(14) + def_corners(10), metadata=SP_FIXED)
    blob = json.dumps(r.to_dict())
    assert "insight_ids" not in blob                    # never invents P0 insight ids
    assert '"record_ids"' in blob
    ac = r.section("attacking_corners")
    assert ac.evidence.record_ids and all(x.startswith("ac") for x in ac.evidence.record_ids)


def test_setpiece_weakness_is_evidence_backed():
    # 80% attack-first-contact on defensive corners -> a real, evidenced weakness
    weak = build_setpiece_report(att_corners(12) + def_corners(10, attack_first=0.8), metadata=SP_FIXED)
    assert any("first contact" in w.heading.lower() for w in weak.weaknesses)
    # 20% attack-first-contact -> no invented weakness from that
    ok = build_setpiece_report(att_corners(12) + def_corners(10, attack_first=0.2), metadata=SP_FIXED)
    assert not any("first contact" in w.heading.lower() for w in ok.weaknesses)


def test_setpiece_report_deterministic_and_serializable():
    sps = att_corners(14) + def_corners(10) + free_kicks(6)
    a = build_setpiece_report(sps, metadata=SP_FIXED).to_dict()
    b = build_setpiece_report(sps, metadata=SP_FIXED).to_dict()
    assert a == b
    assert "DataFrame" not in json.dumps(a)


def test_setpiece_export_separate_document_and_filename():
    r = build_setpiece_report(att_corners(14) + def_corners(10) + free_kicks(6), metadata=SP_FIXED)
    for fmt in ("markdown", "html", "pdf"):
        out = render_setpiece_report(r, fmt)
        assert out.content and len(out.content) > 200
        assert "set_piece" in out.filename                # distinct from the Open Play report
    doc = to_setpiece_document(r)
    assert doc.template_id == "setpiece_scouting"
    assert any(s.id == "attacking_corners" for s in doc.sections)


def test_setpiece_export_unavailable_still_renders():
    r = build_setpiece_report([], metadata=SP_FIXED)
    out = render_setpiece_report(r, "html")
    assert out.content and "unavailable" in out.text.lower()


# ================================================================ two reports are independent
def test_open_play_and_setpiece_reports_are_independent():
    frame = _derive(multi_rows([0.6, 0.62]))
    rep = analyze(frame)
    op = build_report(rep, build_profile(rep), None, metadata=FIXED)
    sp = build_setpiece_report(att_corners(14), metadata=SP_FIXED)
    # different models, documents and filenames; neither leaks into the other
    assert to_report_document(op).template_id == "opposition_scouting"
    assert to_setpiece_document(sp).template_id == "setpiece_scouting"
    assert render_report(op, "markdown").filename != render_setpiece_report(sp, "markdown").filename
    assert "set piece" not in json.dumps(op.to_dict()).lower()


# ================================================================ Open Play embedded visuals (unchanged)
def _report_and_ids(frame):
    rep = analyze(frame)
    return build_report(rep, build_profile(rep), build_evolution(frame), metadata=FIXED), \
        {i.id: i for i in rep.insights}


def test_player_visual_scoped_to_player():
    report, by_id = _report_and_ids(_derive(multi_rows([0.6, 0.62, 0.61, 0.63])))
    plans = plan_report_visuals(report, by_id, {"team": "Opp", "match": "m4"}, mode="detailed")
    pp = next(p for p in plans if p.key == "players:primary")
    assert pp.selections["players"] == ["Star"] and pp.selections["match"] == "m4"


def test_dna_visual_is_team_scoped():
    report, by_id = _report_and_ids(_derive(multi_rows([0.6, 0.62, 0.61])))
    plans = plan_report_visuals(report, by_id, {"team": "Opp"}, mode="detailed")
    sec = next(p for p in plans if p.key == "section:progression")
    assert "players" not in sec.selections


class _StubEngine:
    def __init__(self):
        self.renders = 0
        self.viz_registry = {"Pass Map": {}, "Overview Heatmap": {}}
        self.metadata = {"themes": {"t": {}}}

    def pitch_spec_cls(self):
        return object()

    def apply_pitch_transforms(self, frame, spec):
        return frame

    def apply_filters(self, frame, sel):
        return frame

    def default_ctx(self, vt, spec, **kw):
        return {}

    def render(self, viz, frame, ctx):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        self.renders += 1
        return plt.figure()

    def export(self, fig, fmt, dpi, transparent):
        return b"PNGBYTES" * 80


def test_render_once_and_no_figures_in_model():
    eng = _StubEngine()
    frame = _derive(multi_rows([0.6, 0.62]))
    plans = [VisualPlan("a", "progress", {"team": "Opp"}), VisualPlan("b", "progress", {"team": "Opp"})]
    out = render_report_visuals(eng, frame, plans)
    assert set(out) == {"a", "b"} and eng.renders == 1
    report, _ = _report_and_ids(frame)
    assert "figure" not in json.dumps(report.to_dict()).lower()


def test_embedded_charts_in_open_play_export():
    report, by_id = _report_and_ids(_derive(multi_rows([0.6, 0.62, 0.61])))
    eng = _StubEngine()
    imgs = render_report_visuals(eng, _derive(multi_rows([0.6, 0.62, 0.61])),
                                 plan_report_visuals(report, by_id, {"team": "Opp"}, mode="detailed"))
    assert imgs
    doc = to_report_document(report, chart_images=imgs)
    assert any(sec.charts and sec.charts[0].image_b64 for sec in doc.sections)


def test_match_by_match_table_keeps_insufficient_not_zero():
    rows = multi_rows([0.6, 0.62, 0.61, 0.63])
    for i in range(45):
        rows.append(_ev("pass", 30, 15, 33, 15, player="P0", match="m5", minute=i))  # insufficient
    frame = _derive(rows)
    rep = analyze(frame)
    report = build_report(rep, build_profile(rep), build_evolution(frame, current_match="m5"),
                          metadata=FIXED, mode="detailed")
    tbl = next(a for a in report.appendix if a.table_rows and "Left-sided" in a.title)
    m5 = next(r for r in tbl.table_rows if r[0] == "m5")
    assert m5[1] == "Insufficient" and m5[2] == "insufficient"
    assert all(r[2] != "0%" for r in tbl.table_rows if r[1] != "Observed")


# ================================================================ UI wiring
def test_report_panel_registered_with_both_reports():
    from fap.ui.builtin import openplay_studio as S
    assert "report" in [p[0] for p in S.PANELS["bottom"]]
    assert hasattr(S, "_panel_openplay_report") and hasattr(S, "_panel_setpiece_report")
