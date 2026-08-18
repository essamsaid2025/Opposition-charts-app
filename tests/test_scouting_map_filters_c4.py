"""Phase C4 — scouting player-map semantic filters (pure, canonical-reuse).

Locks: filters compose (successful + progressive + final-third), counts equal filtered rows,
per-map controls are semantic (shot map has no progressive/direction), availability is honest
when required fields are absent, the source frame is never mutated, and the derived columns come
from the CANONICAL fap.openplay.add_derived_columns (no second progressive/zone formula).
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from fap.scouting import map_filters as MF


def _events():
    # x,x2 chosen against the CANONICAL rules: progressive = dx>=10 & (100-x2)<=0.75*(100-x);
    # into_final_third = x<66.67 & x2>=66.67
    rows = [
        # A: successful, progressive, into final third
        dict(x=50, y=50, x2=70, y2=50, minute=1, second=0, outcome="successful"),
        # B: successful, NOT progressive (short), not final third
        dict(x=10, y=50, x2=14, y2=50, minute=2, second=0, outcome="successful"),
        # C: UNsuccessful, progressive, into final third
        dict(x=52, y=50, x2=72, y2=50, minute=3, second=0, outcome="unsuccessful"),
        # D: successful, progressive but NOT into final third (both sides < 66.67)
        dict(x=20, y=50, x2=40, y2=50, minute=4, second=0, outcome="successful"),
    ]
    return pd.DataFrame(rows)


def test_reuses_canonical_derived_columns():
    d = MF.derive(_events())
    for c in ("is_progressive", "into_final_third", "into_box", "lane", "start_third",
              "is_forward"):
        assert c in d.columns                         # exactly what add_derived_columns provides


def test_filters_compose_successful_progressive_final_third():
    f = _events()
    out = MF.apply(f, {"outcome": "Successful", "progressive": "Progressive only",
                       "zone": "Final third"})
    # only row A satisfies all three
    assert list(out["minute"]) == [1]


def test_count_equals_filtered_rows():
    f = _events()
    s = MF.summarize(f, {"outcome": "Successful"})
    assert s["events"] == int((f["outcome"] == "successful").sum()) == 3
    assert s["empty"] is False


def test_empty_state_is_honest():
    f = _events()
    s = MF.summarize(f, {"outcome": "Successful", "progressive": "Progressive only",
                         "zone": "Penalty area"})   # nothing enters the box here
    assert s["events"] == 0 and s["empty"] is True


def test_shot_map_controls_are_semantic():
    # a shot map must NOT offer progressive / direction (section 18)
    fs = MF.applicable_filters("shot_map")
    assert "progressive" not in fs and "direction" not in fs and "outcome" in fs
    # a pass map DOES
    assert "progressive" in MF.applicable_filters("pass_map")


def test_availability_is_honest_without_coordinates():
    # a frame with no movement coords -> progressive/direction unavailable, with a reason
    bare = pd.DataFrame({"x": [1, 2], "y": [1, 2], "outcome": ["successful", "unsuccessful"]})
    av = MF.available_filters(bare, "pass_map")
    assert av["progressive"]["available"] is False and av["progressive"]["reason"]
    assert av["outcome"]["available"] is True         # outcome column present -> available


def test_apply_never_mutates_source():
    f = _events()
    before = f.copy()
    MF.apply(f, {"progressive": "Progressive only"})
    pd.testing.assert_frame_equal(f, before)          # source untouched (no derived cols leaked in)
