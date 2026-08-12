"""P2 tests — transitions, turnovers, evidence-backed vulnerabilities, and
multi-match tactical evolution. P2 rules live inside the existing P0 framework and
are consumed by P1; the multi-match layer orchestrates one P0 pass per match.
"""
import json

import pandas as pd

from fap.analytics.tactical import (
    Confidence, analyze, analyze_evolution, build_evolution, build_multimatch, build_profile,
)
from fap.analytics.tactical.transitions import build_recovery_transitions, build_turnovers
from fap.openplay import add_derived_columns
from fap.pipeline.schema import coerce_schema


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


def transition_rows(mid="m1", n=30, *, shot_every=4, seq=True, times=True, side="left"):
    """Each recovery is followed (later in the same possession) by a progressive pass
    (and sometimes a shot). Follow-ups carry a LATER timestamp so time-ordering places
    them after the recovery."""
    y = {"left": 15.0, "central": 50.0, "right": 85.0}[side]
    rows, s = [], 0
    for k in range(n):
        s += 1
        sq = s if seq else None
        rows.append(_ev("recovery", 40.0, y, 40.0, y, player="D", match=mid, minute=k, second=0, seq=sq))
        rows.append(_ev("pass", 42.0, y, 78.0, y, player="Star", match=mid, minute=k, second=5, seq=sq))
        if shot_every and k % shot_every == 0:
            rows.append(_ev("shot", 88.0, 45.0, 100.0, 50.0, player="Star", match=mid, minute=k,
                            second=10, seq=sq))
    if not times:                                  # truly remove the timestamp signal
        for r in rows:
            r.pop("minute", None)
            r.pop("second", None)
    return rows


def match_rows(mid, left_share, n=80):
    nleft = int(n * left_share)
    ncen = (n - nleft) // 2
    nright = n - nleft - ncen
    rows = []
    for lane, c, y in [("left", nleft, 15.0), ("central", ncen, 50.0), ("right", nright, 85.0)]:
        for i in range(c):
            rows.append(_ev("pass", 30.0, y, 58.0, y, player=f"P{i%6}", match=mid, minute=i % 90))
    return rows


# ================================================================ transitions
def test_recovery_to_progression_and_direction():
    rep = analyze(_derive(transition_rows()))
    ids = {i.id for i in rep.insights}
    assert "transitions.recovery_to_progression" in ids
    assert "transitions.direction" in ids
    d = next(i for i in rep.insights if i.id == "transitions.direction")
    assert d.meta["side"] == "left"


def test_recovery_to_final_third_rapid_only_with_timestamps():
    rep = analyze(_derive(transition_rows(times=True)))
    ft = next(i for i in rep.insights if i.id == "transitions.recovery_to_final_third")
    assert "within" in ft.short_explanation.lower()            # rapid % shown when timestamps exist
    # without timestamps (sequence only): still available, but no "within Ns" speed claim
    rep2 = analyze(_derive(transition_rows(times=False, seq=True)))
    ft2 = next(i for i in rep2.insights if i.id == "transitions.recovery_to_final_third")
    assert "within" not in ft2.short_explanation.lower()


def test_recovery_to_shot():
    rep = analyze(_derive(transition_rows(shot_every=2)))     # many recoveries -> shot
    assert "transitions.recovery_to_shot" in {i.id for i in rep.insights}


def test_transitions_require_sequence_or_timestamps():
    rows = transition_rows(seq=True, times=True)
    df = _derive(rows).drop(columns=["sequence_id", "minute", "second"])
    rep = analyze(df)
    assert not [i for i in rep.insights if i.category.value == "Transitions"]
    assert any("Transition analysis unavailable" in n for n in rep.notices)


# ================================================================ turnovers
def test_turnover_classification_and_no_double_count():
    rows = [_ev("pass", 40, 85, 55, 85, outcome="unsuccessful") for _ in range(10)]
    rows += [_ev("dispossessed", 40, 85, 40, 85, outcome="") for _ in range(3)]
    rows += [_ev("pass", 40, 85, 55, 85, outcome="successful") for _ in range(5)]   # not a turnover
    df = _derive(rows)
    to = build_turnovers(df)
    assert len(to) == 13                                       # 10 failed passes + 3 dispossessions
    assert to.index.is_unique                                  # never double-counted


def test_turnover_zone_concentration_vulnerability():
    rows = [_ev("pass", 40, 85, 55, 85, outcome="unsuccessful") for _ in range(30)]   # right, middle third
    rows += [_ev("pass", 40, 15, 55, 15, outcome="unsuccessful") for _ in range(6)]
    rep = analyze(_derive(rows))
    tz = [i for i in rep.insights if i.id == "vulnerability.turnover_zone"]
    assert tz and tz[0].category.value == "Vulnerability"
    # observation vs interpretation kept separate; never a bare "press them here"
    assert "may represent a potential pressure opportunity" in tz[0].interpretation.lower()
    assert "press them" not in (tz[0].recommendation.lower())


def test_route_failure_uses_rate_not_raw_count():
    # LEFT is the dominant route (most attempts) but has a LOW loss rate -> NOT flagged,
    # proving the rule uses rate against a denominator, not raw turnover counts.
    rows = [_ev("pass", 30, 15, 45, 15, outcome=("unsuccessful" if i < 10 else "successful"))
            for i in range(100)]                              # left: 100 attempts, 10% loss
    rep = analyze(_derive(rows))
    assert "vulnerability.route_failure" not in {i.id for i in rep.insights}

    # now make the dominant route also high-loss -> flagged
    rows2 = [_ev("pass", 30, 15, 45, 15, outcome=("unsuccessful" if i < 30 else "successful"))
             for i in range(50)]                              # left: 50 attempts, 60% loss
    rep2 = analyze(_derive(rows2))
    rf = [i for i in rep2.insights if i.id == "vulnerability.route_failure"]
    assert rf and rf[0].meta["rate"] >= 0.45


def test_final_third_inefficiency_vulnerability():
    # many final-third entries, but no box entries / shots -> inefficiency
    rows = [_ev("pass", 40, 15, 75, 15) for _ in range(40)]   # into final third, never into box
    rep = analyze(_derive(rows))
    assert "vulnerability.final_third_inefficiency" in {i.id for i in rep.insights}


def test_no_vulnerability_on_insufficient_turnovers():
    rows = [_ev("pass", 40, 85, 55, 85, outcome="unsuccessful") for _ in range(5)]   # below min_turnovers
    rep = analyze(_derive(rows))
    assert not [i for i in rep.insights if i.id == "vulnerability.turnover_zone"]


# ================================================================ P1 integration
def test_p1_transition_section_populated():
    prof = build_profile(analyze(_derive(transition_rows())))
    t = prof.section("transitions")
    assert t.available
    assert any(x.startswith("transitions.") for x in t.insight_ids)


def test_p1_consumes_vulnerability_insights():
    rows = [_ev("pass", 40, 85, 55, 85, outcome="unsuccessful") for _ in range(30)]
    rows += [_ev("pass", 40, 15, 75, 15) for _ in range(40)]   # + final-third inefficiency
    prof = build_profile(analyze(_derive(rows)))
    vids = {x for v in prof.vulnerabilities for x in v.insight_ids}
    assert any(x.startswith("vulnerability.") for x in vids)
    # traceable back to real P0 insights
    valid = {i.id for i in analyze(_derive(rows)).insights}
    assert vids <= valid


# ================================================================ multi-match
def _multi(shares, n=80, tiny_last=False):
    rows = []
    for k, s in enumerate(shares):
        rows += match_rows(f"m{k+1}", s, n=n)
    if tiny_last:
        rows += match_rows("mTiny", 0.7, n=6)
    return _derive(rows)


def test_baseline_and_current_vs_baseline():
    evo = build_evolution(_multi([0.45, 0.50, 0.55, 0.60, 0.66]), current_match="m5")
    left = next(p for p in evo.patterns if p.insight_id == "progression.left_dominance")
    assert left.usable_count == 5
    assert left.current_share > left.baseline_share      # current match above baseline
    assert left.delta_pp > 0


def test_consistency_counts_match_recurrence():
    evo = build_evolution(_multi([0.60, 0.62, 0.61, 0.63, 0.64]))
    left = next(p for p in evo.patterns if p.insight_id == "progression.left_dominance")
    assert left.classification == "Consistent"
    assert left.present_count == 5


def test_emerging_pattern():
    evo = build_evolution(_multi([0.30, 0.32, 0.34, 0.60, 0.66]))   # left only dominant late
    left = next(p for p in evo.patterns if p.insight_id == "progression.left_dominance")
    assert left.classification in ("Emerging", "Consistent")
    assert left.trend == "Increasing"


def test_declining_pattern():
    evo = build_evolution(_multi([0.66, 0.60, 0.34, 0.30, 0.28]))
    left = next(p for p in evo.patterns if p.insight_id == "progression.left_dominance")
    assert left.trend == "Decreasing"
    assert left.classification in ("Declining", "Mixed")


def test_stable_vs_volatile():
    stable = build_evolution(_multi([0.55, 0.56, 0.54, 0.55, 0.56]))
    lp = next(p for p in stable.patterns if p.insight_id == "progression.left_dominance")
    assert lp.trend == "Stable"
    volatile = build_evolution(_multi([0.72, 0.30, 0.65, 0.28, 0.70]))
    lpv = next(p for p in volatile.patterns if p.insight_id == "progression.left_dominance")
    assert lpv.trend == "Volatile"


def test_insufficient_matches():
    evo = build_evolution(_multi([0.6, 0.62]))               # only 2 matches (< min_matches)
    assert evo.insufficient
    assert all(p.classification == "Insufficient" for p in evo.patterns)


def test_low_quality_match_excluded_from_baseline():
    evo = build_evolution(_multi([0.5, 0.55, 0.6, 0.62, 0.64], tiny_last=True))
    assert evo.usable_count == 5
    assert any(mid == "mTiny" for mid, _ in evo.excluded)


def test_evolution_serializable():
    evo = build_evolution(_multi([0.45, 0.5, 0.55, 0.6, 0.66]))
    s = json.dumps(evo.to_dict())
    assert '"patterns"' in s and "DataFrame" not in s


def test_evolution_evidence_preserves_player_scope():
    """P2 evidence refs must carry player identity so the P0 player-evidence fix is
    not bypassed when opening a specific match's evidence."""
    rows = []
    for k in range(4):
        for i in range(60):
            # 'Star' dominates progression in every match
            rows.append(_ev("pass", 30, 15, 58, 15, player=("Star" if i < 30 else f"P{i%5}"),
                            match=f"m{k+1}", minute=i % 90))
    evo = build_evolution(_derive(rows))
    pp = next((p for p in evo.patterns if p.insight_id == "progression.primary_player"), None)
    assert pp is not None and pp.evidence
    assert pp.evidence[0].players == ("Star",)               # player scope carried through


# ================================================================ UI wiring
def test_evolution_panel_registered():
    from fap.ui.builtin import openplay_studio as S
    bottom_ids = [p[0] for p in S.PANELS["bottom"]]
    assert "evolution" in bottom_ids
    assert "profile" in bottom_ids and "tactical" in bottom_ids
