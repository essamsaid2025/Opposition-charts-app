"""Opponent Tactical DNA / Tactical Profile (P1) tests.

Covers profile generation (sufficient / limited / missing data), evidence
traceability back to valid P0 insight ids, filter awareness, data-quality-driven
transition availability, key players / strengths / vulnerabilities, and the
'no unsupported claims' guarantees (no formations, no pressing claims, no invented
roles or vulnerabilities). P1 is exercised as a pure consumer of the P0 report.
"""
import json

import pandas as pd

from fap.analytics.tactical import (
    Confidence, TacticalInsightEngine, analyze, analyze_profile, build_profile,
)
from fap.analytics.tactical.profile import TacticalProfile
from fap.openplay import add_derived_columns
from fap.openplay.engine import apply_filters
from fap.pipeline.schema import coerce_schema

_ALLOWED_ROLES = {"Primary progression contributor", "Primary final-third outlet",
                  "Leads attacking involvement"}


# ------------------------------------------------------------------ builders
def _rows(kind, n, *, x, y, end_x, end_y, player="P", team="Opp", **extra):
    base = {"event_type": kind, "team": team, "opponent": "Us", "second": 0, "period": 1,
            "match_id": "m1", "outcome": "successful"}
    return [dict(base, x=x, y=y, end_x=end_x, end_y=end_y,
                 player=(player(i) if callable(player) else player),
                 minute=i % 90, **extra) for i in range(n)]


def _derive(rows):
    return add_derived_columns(coerce_schema(pd.DataFrame(rows)))


def _lane_y(lane):
    return {"left": 15.0, "central": 50.0, "right": 85.0}[lane]


def progression_rows(dist=(("left", 60), ("central", 18), ("right", 18)), star=None, seq=False):
    rows = []
    for lane, c in dist:
        y = _lane_y(lane)
        pl = (lambda i, s=star, ln=lane: s if (ln == "left" and i < c // 2) else f"P{i%9}") \
            if star else (lambda i: f"P{i%9}")
        extra = {"sequence_id": "s1"} if seq else {}
        rows += _rows("pass", c, x=30.0, y=y, end_x=58.0, end_y=y, player=pl, **extra)
    return rows


def rich_rows():
    """Strong left progression + final-third + a dominant player + recoveries."""
    rows = _rows("pass", 60, x=30.0, y=15.0, end_x=75.0, end_y=15.0, player="Star")   # left, final third
    rows += _rows("pass", 16, x=30.0, y=50.0, end_x=75.0, end_y=50.0, player=lambda i: f"P{i%6}")
    rows += _rows("pass", 14, x=30.0, y=85.0, end_x=75.0, end_y=85.0, player=lambda i: f"P{i%6}")
    rows += _rows("cross", 16, x=70.0, y=15.0, end_x=90.0, end_y=25.0, player="Star")  # box, left
    rows += _rows("recovery", 26, x=75.0, y=15.0, end_x=75.0, end_y=15.0, player=lambda i: f"P{i%6}")
    return rows


# ------------------------------------------------------------------ generation
def test_profile_sufficient_evidence():
    prof = build_profile(analyze(_derive(rich_rows())))
    assert isinstance(prof, TacticalProfile)
    assert prof.subject == "Opp"
    assert not prof.limited_evidence
    assert prof.confidence in (Confidence.HIGH, Confidence.MEDIUM)
    ai = prof.section("attacking_identity")
    assert ai.available and ai.headline
    assert len(ai.insight_ids) >= 2               # assembled from multiple P0 insights
    assert prof.section("progression").available
    assert prof.key_players and prof.key_strengths


def test_profile_limited_evidence():
    prof = build_profile(analyze(_derive(progression_rows(dist=(("left", 5), ("central", 2))))))
    assert prof.limited_evidence
    assert prof.confidence_label == "Limited evidence"


def test_profile_missing_data_empty_frame():
    prof = build_profile(analyze(pd.DataFrame()))
    assert prof.limited_evidence
    assert not any(s.available for s in prof.sections)
    assert prof.insights_used == 0


def test_profile_recovery_section():
    rows = _rows("recovery", 30, x=75.0, y=15.0, end_x=75.0, end_y=15.0)
    rows += _rows("interception", 6, x=40.0, y=50.0, end_x=40.0, end_y=50.0)
    prof = build_profile(analyze(_derive(rows)))
    rec = prof.section("recoveries")
    assert rec.available
    # careful terminology: carries P0's non-pressing disclaimer, never "high press"
    text = (rec.headline + " " + " ".join(rec.lines)).lower()
    assert "high press" not in text
    assert "not a measured pressing" in text or "cannot" in text


def test_player_profile_present_with_roles():
    prof = build_profile(analyze(_derive(rich_rows())))
    star = next((p for p in prof.key_players if p.name == "Star"), None)
    assert star is not None
    for role in star.role.split(" · "):
        assert role in _ALLOWED_ROLES         # never an invented football role
    assert star.insight_ids and star.primary_insight_id


# ------------------------------------------------------------------ traceability
def test_every_reference_is_a_valid_p0_insight_id():
    report = analyze(_derive(rich_rows()))
    prof = build_profile(report)
    valid = {i.id for i in report.insights}
    refs: set[str] = set()
    for s in prof.sections:
        refs.update(s.insight_ids)
        if s.available and s.primary_insight_id:
            assert s.primary_insight_id in valid
    for p in prof.key_players:
        refs.update(p.insight_ids)
        assert p.primary_insight_id in valid
    for it in (*prof.key_strengths, *prof.vulnerabilities):
        refs.update(it.insight_ids)
        assert it.primary_insight_id in valid
    assert refs and refs <= valid              # non-empty and all valid


# ------------------------------------------------------------------ filter awareness
def test_profile_is_filter_aware():
    opp = _rows("pass", 60, x=30.0, y=15.0, end_x=58.0, end_y=15.0, team="Opp")   # left
    us = _rows("pass", 40, x=30.0, y=85.0, end_x=58.0, end_y=85.0, team="Us")     # right
    combined = add_derived_columns(coerce_schema(pd.DataFrame(opp + us)))

    prof_opp = build_profile(analyze(apply_filters(combined, {"team": "Opp"})))
    prof_us = build_profile(analyze(apply_filters(combined, {"team": "Us"})))
    assert prof_opp.subject == "Opp" and prof_us.subject == "Us"
    # the filtered profiles describe different sides
    ids_opp = {x for s in prof_opp.sections for x in s.insight_ids}
    ids_us = {x for s in prof_us.sections for x in s.insight_ids}
    assert "progression.left_dominance" in ids_opp
    assert "progression.right_dominance" in ids_us


# ------------------------------------------------------------------ data-quality behaviour
def test_transitions_unavailable_without_sequence_data():
    prof = build_profile(analyze(_derive(progression_rows(seq=False))))
    t = prof.section("transitions")
    assert not t.available and "sequence" in t.reason.lower()


def test_transitions_unavailable_but_data_present_reason_differs():
    prof = build_profile(analyze(_derive(progression_rows(seq=True))))
    t = prof.section("transitions")
    assert not t.available
    assert "not modelled" in t.reason.lower()


# ------------------------------------------------------------------ vulnerabilities
def test_no_vulnerability_when_not_evidenced():
    # balanced-ish: the weakest side is not unusually low -> no vulnerability invented
    prof = build_profile(analyze(_derive(progression_rows(dist=(("left", 46), ("central", 30),
                                                                 ("right", 24))))))
    assert prof.vulnerabilities == ()


def test_one_sided_progression_yields_evidenced_vulnerability():
    prof = build_profile(analyze(_derive(progression_rows(dist=(("left", 72), ("central", 22),
                                                                 ("right", 6))))))
    assert prof.vulnerabilities
    v = prof.vulnerabilities[0]
    assert "right" in v.text.lower()
    assert v.confidence in (Confidence.MEDIUM, Confidence.LOW)   # never overclaimed as High
    assert v.primary_insight_id in {i.id for i in analyze(_derive(progression_rows(
        dist=(("left", 72), ("central", 22), ("right", 6))))).insights}


# ------------------------------------------------------------------ no unsupported claims
def test_no_formation_or_pressing_claims():
    prof = build_profile(analyze(_derive(rich_rows())))
    blob = " ".join(
        [s.text for s in prof.summary]
        + [sec.headline + " " + " ".join(sec.lines) for sec in prof.sections]
        + [it.text + " " + it.detail for it in (*prof.key_strengths, *prof.vulnerabilities)]
        + [p.role for p in prof.key_players]).lower()
    for banned in ("4-3-3", "4-4-2", "3-5-2", "formation", "high press", "presses high",
                   "plays a ", "playmaker", "false nine"):
        # "formation" is allowed ONLY inside the explicit no-inference disclaimer
        if banned == "formation":
            assert "formation and role assignments are not inferred" in blob
            continue
        assert banned not in blob


# ------------------------------------------------------------------ serialization / determinism
def test_profile_serializable_and_deterministic():
    report = analyze(_derive(rich_rows()))
    p1 = build_profile(report)
    p2 = build_profile(report)
    d1, d2 = p1.to_dict(), p2.to_dict()
    assert d1 == d2                               # deterministic
    s = json.dumps(d1)                            # serializable, no frames/figures
    assert '"summary"' in s and '"coverage"' in s
    assert "DataFrame" not in s


def test_analyze_profile_convenience_matches_two_step():
    frame = _derive(rich_rows())
    one = analyze_profile(frame).to_dict()
    two = build_profile(TacticalInsightEngine().analyze(frame)).to_dict()
    assert one == two
