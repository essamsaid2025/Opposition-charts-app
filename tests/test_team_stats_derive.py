"""Derived team metrics: Field Tilt + PPDA computed from an aggregated team-stats
comparison file when absent, using the standard formulas — and kept from the file
when present. Correctness is the whole point, so the expected values are hand-computed.
"""
import os
os.environ["FAP_TEST"] = "1"
import io
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from fap.datahub.team_stats_derive import DERIVED_CATEGORY, derive_team_stats
from fap.datahub.team_stats_schema import analyze_team_stats


_BASE_ROWS = [
    ("Distribution", "All passes in final third", 100, 50),
    ("Distribution", "All passes in defensive third", 200, 100),
    ("Distribution", "All passes in middle third", 150, 120),
    ("Defensive", "All tackles", 20, 30),
    ("Defensive", "Interceptions", 10, 8),
    ("Summary", "Fouls", 12, 10),
]


def _frame(rows, a="Team A", b="Team B"):
    return pd.DataFrame([{"Category": c, "Statistic": s, a: va, b: vb}
                         for c, s, va, vb in rows])


def _by_name(stats):
    return {s.name: s for s in stats}


# ================================================================ both derived
def test_field_tilt_and_ppda_derived_when_absent():
    an = analyze_team_stats(_frame(_BASE_ROWS))
    a, b = an.teams
    stats = _by_name(an.schema.stats)
    assert "Field Tilt" in stats and "PPDA" in stats
    ft, pp = stats["Field Tilt"], stats["PPDA"]
    assert ft.category == DERIVED_CATEGORY and pp.category == DERIVED_CATEGORY
    # Field Tilt = share of final-third passes: 100/150 = 67%, 50/150 = 33%
    assert ft.values[a] == 67.0 and ft.values[b] == 33.0 and ft.unit == "percent"
    # PPDA_A = B(def+mid) / A(tackles+int+fouls) = (100+120)/(20+10+12) = 220/42 = 5.24
    # PPDA_B = A(def+mid) / B(...)               = (200+150)/(30+8+10) = 350/48 = 7.29
    assert pp.values[a] == 5.24 and pp.values[b] == 7.29
    assert pp.raw[a] == "5.2" and pp.raw[b] == "7.3"


# ================================================================ keep file's own
def test_existing_field_tilt_is_not_overwritten():
    rows = _BASE_ROWS + [("Distribution", "Field Tilt", "60%", "40%")]
    an = analyze_team_stats(_frame(rows))
    fts = [s for s in an.schema.stats if s.name.lower() == "field tilt"]
    assert len(fts) == 1                                   # not duplicated
    assert fts[0].category == "Distribution"              # the file's own row, unchanged
    assert fts[0].values["Team A"] == 60.0
    # PPDA still derived (absent in the file)
    assert any(s.name == "PPDA" for s in an.schema.stats)


# ================================================================ needs inputs
def test_no_ppda_without_defensive_actions():
    rows = [r for r in _BASE_ROWS if r[1] != "All tackles"]  # remove tackles
    stats = analyze_team_stats(_frame(rows)).schema.stats
    assert not any(s.name == "PPDA" for s in stats)          # missing input -> skip
    assert any(s.name == "Field Tilt" for s in stats)        # field tilt still derivable


def test_no_derivation_for_more_than_two_teams():
    rows = [{"Category": c, "Statistic": s, "A": va, "B": vb, "C": va}
            for c, s, va, vb in _BASE_ROWS]
    an = analyze_team_stats(pd.DataFrame(rows))
    assert len(an.teams) == 3
    assert not any(s.category == DERIVED_CATEGORY for s in an.schema.stats)


# ================================================================ integrity + surfacing
def test_original_stats_untouched_and_derived_appended():
    an = analyze_team_stats(_frame(_BASE_ROWS))
    original = [s for s in an.schema.stats if s.category != DERIVED_CATEGORY]
    assert len(original) == len(_BASE_ROWS)               # every file row preserved
    assert DERIVED_CATEGORY in an.schema.categories
    # the derived rows are real TeamStats and surface in the comparison view
    from fap.openplay.team_compare import TeamComparison
    cmp = TeamComparison.from_schema(an.schema)
    labels = cmp.stat_labels()
    assert "PPDA" in labels and "Field Tilt" in labels


def test_derive_helper_is_pure_and_two_team_only():
    an = analyze_team_stats(_frame(_BASE_ROWS))
    base = [s for s in an.schema.stats if s.category != DERIVED_CATEGORY]
    got = derive_team_stats(base, list(an.teams))
    assert {s.name for s in got} == {"Field Tilt", "PPDA"}
    assert derive_team_stats(base, ["only_one"]) == []     # needs exactly two teams
