"""P2.1 — multi-match evidence semantics.

Regression tests proving the aggregation distinguishes a genuine measured value from
'insight did not fire because the family sample was insufficient'. Insufficient /
unavailable matches must never be treated as a value of 0: they are excluded from
recurrence, trend and baseline. A genuine observed absence (family had enough data,
pattern simply wasn't dominant) IS counted.
"""
import json

import pandas as pd

from fap.analytics.tactical import analyze_evolution, build_evolution, build_multimatch
from fap.openplay import add_derived_columns
from fap.pipeline.schema import coerce_schema


# ------------------------------------------------------------------ builders
def _derive(rows):
    return add_derived_columns(coerce_schema(pd.DataFrame(rows)))


def match_rows(mid, left_share, n=80, date=None):
    """A match where `left_share` of progression goes left (rest split)."""
    nl = int(n * left_share)
    nc = (n - nl) // 2
    nr = n - nl - nc
    rows = []
    for lane, c, y in [("left", nl, 15.0), ("central", nc, 50.0), ("right", nr, 85.0)]:
        for i in range(c):
            r = {"event_type": "pass", "x": 30.0, "y": y, "end_x": 58.0, "end_y": y,
                 "player": f"P{i%6}", "team": "Opp", "opponent": "Us", "minute": i % 90,
                 "second": 0, "period": 1, "match_id": mid, "outcome": "successful"}
            if date:
                r["date"] = date
            rows.append(r)
    return rows


def insufficient_match(mid, n=45, date=None):
    """Match-level usable (>= min events) but the progression family is INSUFFICIENT
    (short lateral passes => 0 progressive actions)."""
    rows = []
    for i in range(n):
        r = {"event_type": "pass", "x": 30.0, "y": 15.0, "end_x": 33.0, "end_y": 15.0,
             "player": "P0", "team": "Opp", "opponent": "Us", "minute": i % 90, "second": 0,
             "period": 1, "match_id": mid, "outcome": "successful"}
        if date:
            r["date"] = date
        rows.append(r)
    return rows


def _left(evo):
    return next(p for p in evo.patterns if p.insight_id == "progression.left_dominance")


# ================================================================ Test A
def test_insufficient_match_is_not_zero():
    rows = []
    for k, s in enumerate([0.60, 0.62, 0.61, 0.63]):
        rows += match_rows(f"m{k+1}", s)
    rows += insufficient_match("m5")
    p = _left(build_evolution(_derive(rows)))
    assert p.usable_count == 5
    assert p.observable_count == 4                 # the insufficient match is excluded
    assert p.insufficient_count == 1
    assert "m5" not in p.observable_match_ids
    assert all(s > 0 for s in p.shares)            # no 0 injected by the insufficient match


# ================================================================ Test B
def test_recurrence_ignores_insufficient_matches():
    rows = []
    for k, s in enumerate([0.60, 0.62, 0.61, 0.63]):
        rows += match_rows(f"m{k+1}", s)
    rows += insufficient_match("m5")
    p = _left(build_evolution(_derive(rows)))
    assert p.present_count == 4 and p.observable_count == 4
    assert p.recurrence == "4 / 4"                 # NOT 4 / 5
    assert p.classification == "Consistent"


# ================================================================ Test C
def test_trend_ignores_insufficient_matches():
    # an insufficient match in the MIDDLE would, if 0-padded, make the trend Volatile
    rows = match_rows("m1", 0.55) + match_rows("m2", 0.58) + insufficient_match("m3")
    rows += match_rows("m4", 0.61) + match_rows("m5", 0.64)
    p = _left(build_evolution(_derive(rows)))
    assert p.observable_count == 4 and "m3" not in p.observable_match_ids
    assert p.trend == "Increasing"                 # would be "Volatile" under 0-padding
    assert p.trend != "Volatile"


# ================================================================ Test D
def test_no_delta_when_current_match_insufficient():
    rows = []
    for k, s in enumerate([0.60, 0.62, 0.61, 0.63]):
        rows += match_rows(f"m{k+1}", s)
    rows += insufficient_match("m5")
    p = _left(build_evolution(_derive(rows), current_match="m5"))
    assert p.current_status == "Insufficient"
    assert p.current_share is None and p.delta is None and p.delta_pp is None


def test_no_delta_when_baseline_insufficient():
    # only the current match is observable; every other match is insufficient
    rows = match_rows("m1", 0.62) + insufficient_match("m2") + insufficient_match("m3")
    p = _left(build_evolution(_derive(rows), current_match="m1"))
    assert p.baseline_status == "Insufficient"
    assert p.baseline_share is None and p.delta is None


# ================================================================ Test E
def test_genuine_observed_absence_is_counted_not_dropped():
    # m3 has a full progression sample but left is NOT dominant -> OBSERVED_ABSENT (a real
    # negative observation), distinct from an insufficient-sample match.
    rows = (match_rows("m1", 0.62) + match_rows("m2", 0.61) + match_rows("m3", 0.34)
            + match_rows("m4", 0.63) + match_rows("m5", 0.64))
    p = _left(build_evolution(_derive(rows)))
    assert p.observable_count == 5                  # m3 IS observable (had the data)
    assert p.insufficient_count == 0
    assert "m3" in p.observable_match_ids and "m3" not in p.present_match_ids
    assert p.recurrence == "4 / 5"                  # genuine absence counts in the denominator
    assert 0.0 in p.shares                          # observed-absent is a real 0 strength
    assert any(s > 0.5 for s in p.shares)           # fired matches keep their measured value


# ================================================================ ordering
def test_matches_ordered_chronologically_by_date():
    # appended late-match first, but dates should drive the order
    rows = match_rows("mLate", 0.62, date="2024-05-01") + match_rows("mEarly", 0.60, date="2024-01-01")
    ctx = build_multimatch(_derive(rows))
    assert [m.match_id for m in ctx.matches] == ["mEarly", "mLate"]


def test_ordering_falls_back_to_appearance_without_dates():
    rows = match_rows("mB", 0.62) + match_rows("mA", 0.60)   # no date column
    ctx = build_multimatch(_derive(rows))
    assert [m.match_id for m in ctx.matches] == ["mB", "mA"]  # appearance order, deterministic


# ================================================================ serialization
def test_serializable_with_null_delta():
    rows = []
    for k, s in enumerate([0.60, 0.62, 0.61, 0.63]):
        rows += match_rows(f"m{k+1}", s)
    rows += insufficient_match("m5")
    evo = build_evolution(_derive(rows), current_match="m5")
    d = evo.to_dict()
    s = json.dumps(d)                              # None deltas must serialize (null)
    assert '"delta": null' in s or '"delta_pp": null' in s
    assert "DataFrame" not in s
