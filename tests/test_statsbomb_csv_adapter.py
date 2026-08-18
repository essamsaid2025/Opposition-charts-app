"""Flattened-StatsBomb CSV adapter — reshape to canonical event columns, guarded.

Locks: the dotted/list-coord StatsBomb export is detected + reshaped (location->x/y scaled to
0-100, end-location->x2/y2, type.name->event_type, player/team), so it classifies as EVENT; a
normal metrics/canonical-xy frame is left completely untouched (every other format is safe).
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

from fap.datahub.classification import classify_frame
from fap.pipeline.statsbomb_csv import looks_like_statsbomb_csv, reshape


def _sb():
    return pd.DataFrame({
        "match_id": [16073, 16073, 16073],
        "type.name": ["Pass", "Pass", "Shot"],
        "player.name": ["A", "A", "B"],
        "team.name": ["T", "T", "T"],
        "minute": [1, 2, 3], "second": [0, 0, 0],
        "location": ["[60, 40]", "[30, 40]", "[110, 40]"],
        "pass.end_location": ["[90, 40]", "[45, 40]", None],
        "shot.end_location": [None, None, "[120, 40]"],
        "pass.outcome.name": [None, "Incomplete", None],   # 1st pass complete, 2nd failed
    })


def test_detects_only_statsbomb_shape():
    assert looks_like_statsbomb_csv(_sb()) is True
    assert looks_like_statsbomb_csv(pd.DataFrame({"player": ["A"], "passes": [1]})) is False
    # a frame already carrying canonical x/y is NOT reshaped again
    assert looks_like_statsbomb_csv(pd.DataFrame({"type.name": ["Pass"], "location": ["[1,1]"],
                                                  "x": [1.0], "y": [1.0]})) is False


def test_reshape_adds_scaled_canonical_columns():
    r = reshape(_sb())
    for c in ("x", "y", "x2", "y2", "event_type", "player", "team"):
        assert c in r.columns
    # 60/120*100 = 50 ; 40/80*100 = 50
    assert abs(r.loc[0, "x"] - 50.0) < 1e-6 and abs(r.loc[0, "y"] - 50.0) < 1e-6
    # pass end 90 -> 75 ; shot end 120 -> 100
    assert abs(r.loc[0, "x2"] - 75.0) < 1e-6 and abs(r.loc[2, "x2"] - 100.0) < 1e-6
    assert r.loc[0, "event_type"] == "Pass" and r.loc[0, "player"] == "A"


def test_outcome_only_for_passes():
    r = reshape(_sb())
    assert r.loc[0, "outcome"] == "successful"      # complete pass (blank outcome.name)
    assert r.loc[1, "outcome"] == "unsuccessful"    # failed pass
    assert pd.isna(r.loc[2, "outcome"])             # shot -> left NA, not fabricated


def test_reshaped_frame_classifies_as_event():
    assert reshape(_sb()) is not _sb()              # returns a copy
    assert classify_frame(reshape(_sb())).dataset_type == "event"
    # BEFORE reshape the same shape is misread (no canonical x/y) -> not event
    assert classify_frame(_sb()).dataset_type != "event"


def test_non_statsbomb_frame_is_untouched():
    m = pd.DataFrame({"player": ["A", "B"], "passes": [1, 2], "tackles": [3, 4]})
    out = reshape(m)
    assert list(out.columns) == ["player", "passes", "tackles"]
