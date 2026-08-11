"""Tactical Insight Engine (P0) tests.

Covers the rules (progression / final-third / box / recovery / player), the
statistical safeguards (small sample, empty frame, missing columns/coords/
players/timestamps, filtered-to-empty), the confidence framework, serialization,
and the canonical-dataset -> filters -> engine integration path.
"""
import json

import numpy as np
import pandas as pd
import pytest

from fap.analytics.tactical import (
    Confidence, InsightThresholds, Priority, TacticalInsightEngine, analyze,
)
from fap.analytics.tactical.model import InsightReport
from fap.analytics.tactical.thresholds import DEFAULT_THRESHOLDS, grade
from fap.openplay import add_derived_columns
from fap.openplay.engine import apply_filters
from fap.pipeline.schema import coerce_schema

TH = DEFAULT_THRESHOLDS


# ------------------------------------------------------------------ builders
def _rows(kind, n, *, x, y, end_x, end_y, player="P", team="Opp", start=0):
    return [{"event_type": kind, "x": x, "y": y, "end_x": end_x, "end_y": end_y,
             "player": (player(i) if callable(player) else player), "team": team,
             "opponent": "Us", "minute": (start + i) % 90, "second": 0,
             "period": 1, "match_id": "m1", "outcome": "successful"} for i in range(n)]


def _frame(rows):
    return pd.DataFrame(rows)


def _lane_y(lane):
    return {"left": 15.0, "central": 50.0, "right": 85.0}[lane]


def progression_frame(dist=(("left", 60), ("central", 18), ("right", 18)), player_star=None):
    rows = []
    for lane, c in dist:
        y = _lane_y(lane)
        pl = (lambda i, s=player_star, ln=lane: s if (ln == "left" and i < c // 2) else f"P{i%9}") \
            if player_star else (lambda i: f"P{i%9}")
        rows += _rows("pass", c, x=30.0, y=y, end_x=58.0, end_y=y, player=pl)
    return _frame(rows)


# ------------------------------------------------------------------ rules
def test_left_progression_dominance():
    rep = analyze(progression_frame())
    ids = {i.id for i in rep.insights}
    assert "progression.left_dominance" in ids
    ins = next(i for i in rep.insights if i.id == "progression.left_dominance")
    assert ins.category.value == "Progression"
    assert ins.sample_size == 96
    assert ins.subject == "Opp"
    # observation and interpretation are DISTINCT fields (no overclaiming)
    assert ins.observation and ins.interpretation and ins.observation != ins.interpretation
    assert any("Left Lane" in e.label for e in ins.evidence)
    assert ins.supporting_viz is not None and ins.supporting_viz.event_types
    # right/central dominance must NOT also fire (mutually exclusive)
    assert "progression.right_dominance" not in ids
    assert "progression.central_dominance" not in ids


def test_right_progression_dominance():
    rep = analyze(progression_frame(dist=(("left", 18), ("central", 18), ("right", 60))))
    assert "progression.right_dominance" in {i.id for i in rep.insights}


def test_dominant_progression_corridor_channel():
    rep = analyze(progression_frame())
    assert "progression.dominant_corridor" in {i.id for i in rep.insights}


def test_final_third_entry_concentration():
    # entries into the final third arriving on the left (end_x >= 66.67)
    rows = _rows("pass", 40, x=40.0, y=15.0, end_x=75.0, end_y=15.0)       # left
    rows += _rows("pass", 12, x=40.0, y=50.0, end_x=75.0, end_y=50.0)      # central
    rep = analyze(_frame(rows))
    ids = {i.id for i in rep.insights}
    assert "final_third.entry_concentration" in ids
    assert "final_third.preferred_corridor" in ids


def test_box_entry_concentration():
    rows = _rows("cross", 20, x=70.0, y=85.0, end_x=90.0, end_y=70.0)      # right into box
    rows += _rows("cross", 4, x=70.0, y=15.0, end_x=90.0, end_y=30.0)      # left into box
    rep = analyze(_frame(rows))
    assert "final_third.box_entry_concentration" in {i.id for i in rep.insights}


def test_recovery_zone_and_high_concentration():
    # recoveries clustered in the final third, left lane
    rows = _rows("recovery", 30, x=75.0, y=15.0, end_x=75.0, end_y=15.0)
    rows += _rows("interception", 5, x=40.0, y=50.0, end_x=40.0, end_y=50.0)
    rep = analyze(_frame(rows))
    ids = {i.id for i in rep.insights}
    assert "recoveries.dominant_zone" in ids
    assert "recoveries.high_concentration" in ids
    high = next(i for i in rep.insights if i.id == "recoveries.high_concentration")
    # must NOT overclaim pressing — it explicitly disclaims a pressing metric
    assert "not a measured pressing" in high.interpretation.lower()


def test_dominant_progression_player():
    rep = analyze(progression_frame(player_star="Star"))
    ins = [i for i in rep.insights if i.id == "progression.primary_player"]
    assert ins and ins[0].subject == "Star"
    assert ins[0].meta["player"] == "Star"


# ------------------------------------------------------------------ safeguards
def test_insufficient_sample_no_insight():
    # only a handful of progressive actions -> below the denominator threshold
    rep = analyze(progression_frame(dist=(("left", 4), ("central", 1), ("right", 1))))
    assert not [i for i in rep.insights if i.category.value == "Progression"]
    assert any("Progression analysis inconclusive" in n for n in rep.notices)


def test_empty_dataset():
    rep = analyze(pd.DataFrame())
    assert isinstance(rep, InsightReport)
    assert rep.count == 0
    assert rep.notices and "No events" in rep.notices[0]


def test_missing_end_coordinates():
    rows = _rows("pass", 80, x=30.0, y=15.0, end_x=58.0, end_y=15.0)
    df = _frame(rows).drop(columns=["end_x", "end_y"])
    rep = analyze(df)
    assert not [i for i in rep.insights if i.category.value in ("Progression", "Final Third")]
    assert any("end coordinates" in n for n in rep.notices)


def test_missing_players():
    df = progression_frame().drop(columns=["player"])
    rep = analyze(df)
    assert not [i for i in rep.insights if i.category.value == "Players"]
    assert not [i for i in rep.insights if i.id == "progression.primary_player"]
    assert any("Player insights unavailable" in n for n in rep.notices)


def test_missing_timestamps_does_not_crash():
    df = progression_frame().drop(columns=["minute", "second"])
    rep = analyze(df)                                  # must not raise
    assert isinstance(rep, InsightReport)


def test_missing_coordinates_no_crash():
    df = progression_frame().drop(columns=["x", "y"])
    rep = analyze(df)
    assert isinstance(rep, InsightReport)


def test_filtered_to_empty():
    df = progression_frame()
    filtered = df[df["team"] == "DoesNotExist"]
    rep = analyze(filtered)
    assert rep.count == 0
    assert rep.notices


# ------------------------------------------------------------------ confidence
def test_grade_high_confidence():
    level, score, br = grade(sample=200, min_sample=20, effect=1.0, quality=92.0, th=TH)
    assert level is Confidence.HIGH
    assert 0.0 <= score <= 1.0 and set(br) == {"sample", "effect", "quality", "score"}


def test_grade_low_when_borderline():
    level, _, _ = grade(sample=21, min_sample=20, effect=0.05, quality=55.0, th=TH)
    assert level in (Confidence.LOW, Confidence.MEDIUM)


def test_grade_poor_quality_forced_low():
    # strong sample + effect, but data quality below the floor -> never confident
    level, _, _ = grade(sample=500, min_sample=20, effect=1.0, quality=10.0, th=TH)
    assert level is Confidence.LOW


def test_high_confidence_case_end_to_end():
    rep = analyze(progression_frame())
    left = next(i for i in rep.insights if i.id == "progression.left_dominance")
    assert left.confidence is Confidence.HIGH
    assert left.priority is Priority.HIGH


def test_low_confidence_case_end_to_end():
    # a real but weak/borderline pattern via custom (lenient) thresholds so the rule
    # fires but grades low
    th = InsightThresholds(min_progressive_actions=10, dominance_share=0.40,
                           min_effect_margin=0.05)
    rep = TacticalInsightEngine(th).analyze(
        progression_frame(dist=(("left", 24), ("central", 18), ("right", 18))))
    prog = [i for i in rep.insights if i.id == "progression.left_dominance"]
    assert prog and prog[0].confidence in (Confidence.LOW, Confidence.MEDIUM)


# ------------------------------------------------------------------ serialization
def test_report_is_serializable_without_frames():
    rep = analyze(progression_frame())
    d = rep.to_dict()
    s = json.dumps(d)                                  # must round-trip through JSON
    assert '"insights"' in s and d["summary"]["count"] == rep.count
    for ins in d["insights"]:
        # only lightweight fields — never a DataFrame/figure
        assert isinstance(ins["event_ids"], list)
        assert all(not isinstance(v, (pd.DataFrame, pd.Series)) for v in ins.values())
        assert len(ins["event_ids"]) <= 50


# ------------------------------------------------------------------ integration
def test_engine_respects_open_play_filters():
    """canonical dataset -> existing Open Play apply_filters -> engine."""
    opp = progression_frame()                               # left-dominant, team "Opp"
    us = _frame(_rows("pass", 40, x=30.0, y=85.0, end_x=58.0, end_y=85.0, team="Us"))  # right, "Us"
    # the real Studio flow: canonical active frame -> add_derived_columns -> apply_filters
    combined = add_derived_columns(coerce_schema(pd.concat([opp, us], ignore_index=True)))

    filtered = apply_filters(combined, {"team": "Opp"})
    rep = analyze(filtered)
    assert rep.subject == "Opp"
    assert "progression.left_dominance" in {i.id for i in rep.insights}

    filtered_us = apply_filters(combined, {"team": "Us"})
    rep_us = analyze(filtered_us)
    assert rep_us.subject == "Us"
    assert "progression.right_dominance" in {i.id for i in rep_us.insights}


def test_insights_ordered_by_priority_then_confidence():
    rep = analyze(progression_frame(player_star="Star"))
    ranks = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
    seq = [ranks[i.priority] for i in rep.insights]
    assert seq == sorted(seq)


def test_no_unsupported_tactical_claims():
    """The engine must never assert formations or pressing systems."""
    rep = analyze(progression_frame())
    blob = " ".join(f"{i.observation} {i.interpretation} {i.recommendation}"
                    for i in rep.insights).lower()
    for banned in ("4-3-3", "4-4-2", "3-5-2", "plays a ", "presses high", "high press"):
        assert banned not in blob


# ------------------------------------------------------------------ UI integration glue
def test_ui_panel_wired_and_evidence_maps_to_real_visualizations():
    """The Tactical Insights panel is registered in the Studio and its 'supporting
    evidence' hints resolve to EXISTING registry visualizations (no second chart
    system). Uses the real injected Open Play engine (app import is FAP_TEST-guarded)."""
    import os
    import pathlib
    import sys

    os.environ["FAP_TEST"] = "1"
    root = pathlib.Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    import app  # noqa: F401  (registers the Open Play engine at import)
    from fap.openplay.engine import get_engine
    from fap.ui.builtin import openplay_studio as S

    eng = get_engine()
    assert eng is not None

    # the panel is wired into the Studio's bottom region, and the existing quick
    # insights panel is preserved (additive, not a replacement)
    bottom_ids = [p[0] for p in S.PANELS["bottom"]]
    assert bottom_ids[0] == "tactical"
    assert "insights" in bottom_ids

    # every supporting-viz hint the rules emit resolves to a real registry chart
    for hint, ets in [("progress", ("pass", "carry")), ("recovery", ("recovery",)),
                      ("box", ("cross",)), ("final third", ("pass",)), ("touch", ())]:
        name = S._match_viz(eng, hint, ets)
        assert name in eng.viz_registry


# ---- P0 bug fix: player-insight supporting evidence must be scoped to the player ----
def _derive(df):
    return add_derived_columns(coerce_schema(df))


def _two_player_frame():
    # Player A dominates progression (left), Player B progresses on the right, plus filler.
    rows = _rows("pass", 40, x=30.0, y=15.0, end_x=58.0, end_y=15.0, player="A")
    rows += _rows("pass", 30, x=30.0, y=85.0, end_x=58.0, end_y=85.0, player="B")
    rows += _rows("pass", 20, x=30.0, y=50.0, end_x=58.0, end_y=50.0, player=lambda i: f"C{i%3}")
    return _frame(rows)


def test_player_evidence_scopes_to_that_player():
    """Test 1 — a player insight's supporting evidence carries the player and the
    existing filter yields ONLY that player's events (excludes Player B)."""
    from fap.ui.builtin import openplay_studio as S
    frame = _derive(_two_player_frame())
    ins = next(i for i in analyze(frame).insights if i.id == "progression.primary_player")
    assert ins.subject == "A"
    assert ins.supporting_viz.players == ("A",)
    sel = S._evidence_selections({}, ins.supporting_viz, frame)
    assert sel["players"] == ["A"] and "B" not in sel["players"]
    # end-to-end through the EXISTING Open Play filter
    filtered = apply_filters(frame, sel)
    assert set(filtered["player"].astype(str)) == {"A"}


def test_team_insight_evidence_shows_whole_team():
    """Test 2 — a team-level insight is not player-scoped; evidence shows the team."""
    from fap.ui.builtin import openplay_studio as S
    frame = _derive(progression_frame())
    ins = next(i for i in analyze(frame).insights if i.id == "progression.left_dominance")
    assert ins.supporting_viz.players == ()
    sel = S._evidence_selections({}, ins.supporting_viz, frame)
    assert "players" not in sel
    assert apply_filters(frame, sel)["player"].astype(str).nunique() > 1


def test_player_evidence_preserves_existing_filters():
    """Test 3 — existing filters (e.g. second half + team) are preserved and the
    player + event filters are added on top."""
    from fap.ui.builtin import openplay_studio as S
    frame = _derive(_two_player_frame())
    ins = next(i for i in analyze(frame).insights if i.id == "progression.primary_player")
    base = {"team": "Opp", "minute_range": (45, 90)}
    sel = S._evidence_selections(base, ins.supporting_viz, frame)
    assert sel["team"] == "Opp"
    assert sel["minute_range"] == (45, 90)
    assert sel["players"] == ["A"]
    assert sel.get("event_types")                # relevant event filter applied too


def test_team_insight_does_not_inherit_player_filter():
    """Test 4 — a team-level insight must NOT inherit a previously selected player."""
    from fap.ui.builtin import openplay_studio as S
    frame = _derive(progression_frame())
    ins = next(i for i in analyze(frame).insights if i.id == "progression.left_dominance")
    base = {"players": ["Someone Else"], "team": "Opp"}
    sel = S._evidence_selections(base, ins.supporting_viz, frame)
    assert "players" not in sel                  # stale player filter cleared
    assert sel["team"] == "Opp"                  # other filters preserved


def test_player_evidence_ignores_unknown_player_names():
    """Robustness — a player not present in the frame never widens scope to nothing;
    it falls back to the whole team rather than an empty/foreign filter."""
    from fap.ui.builtin import openplay_studio as S
    from fap.analytics.tactical.model import SupportingViz
    frame = _derive(_two_player_frame())
    sv = SupportingViz(description="x", viz_hint="progress", event_types=("pass",),
                       players=("Ghost",))
    sel = S._evidence_selections({}, sv, frame)
    assert "players" not in sel
