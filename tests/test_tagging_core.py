"""Tagging Studio core: coordinates, events, undo/redo history, validation, export.

Pure — no Streamlit, no browser. Priority order mirrors the spec: data correctness,
then coordinate correctness, then reliability (history), then export stability.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pytest

from fap.tagging import coordinates as C
from fap.tagging.export import (CSV_COLUMNS, project_from_dict, session_to_csv,
                                session_to_rows, to_project_dict)
from fap.tagging.models import TagEvent, TaggingSession
from fap.tagging.schema import PRESETS, tag_by_key
from fap.tagging.validation import validate_event, validate_session


# ------------------------------------------------------------------ coordinates
def test_pitch_click_maps_to_canonical():
    assert C.canonical_from_pitch_fraction(0.0, 0.0) == (0.0, 100.0)   # top-left
    assert C.canonical_from_pitch_fraction(1.0, 1.0) == (100.0, 0.0)   # bottom-right
    assert C.canonical_from_pitch_fraction(0.5, 0.5) == (50.0, 50.0)   # centre


def test_goal_click_maps_to_canonical():
    assert C.canonical_from_goal_fraction(0.0, 1.0) == (0.0, 0.0)       # left post, ground
    assert C.canonical_from_goal_fraction(1.0, 0.0) == (100.0, 100.0)   # right post, crossbar


def test_pitch_transform_is_reversible():
    for fx, fy in [(0.12, 0.87), (0.4, 0.4), (0.99, 0.01)]:
        x, y = C.canonical_from_pitch_fraction(fx, fy)
        rfx, rfy = C.pitch_fraction_from_canonical(x, y)
        assert rfx == pytest.approx(fx, abs=1e-3) and rfy == pytest.approx(fy, abs=1e-3)


def test_coordinates_are_pixel_size_independent():
    # same physical location at two canvas widths -> identical canonical coordinate
    px = 240
    for width in (600, 1280, 1920):
        fx = px / width
        x_small, _ = C.canonical_from_pitch_fraction(px / 600, 0.5)
        x_here, _ = C.canonical_from_pitch_fraction(px / width, 0.5)
        assert (x_here == pytest.approx(px / width * 100))
    # the fraction is the contract; equal fractions always give equal coordinates
    assert C.canonical_from_pitch_fraction(0.333, 0.5) == C.canonical_from_pitch_fraction(0.333, 0.5)


def test_out_of_range_is_clamped():
    assert C.canonical_from_pitch_fraction(1.5, -0.2) == (100.0, 100.0)


# ------------------------------------------------------------------ events
def test_point_line_and_goal_events():
    s = TaggingSession()
    pt = s.add_event(TagEvent(event_type="shot", coordinate_space="pitch",
                              team="Team A", player="P9", x=88.0, y=52.0, outcome="Saved"))
    ln = s.add_event(TagEvent(event_type="pass", coordinate_space="pitch",
                              x=30.0, y=40.0, x2=60.0, y2=44.0, outcome="Successful"))
    gl = s.add_event(TagEvent(event_type="shot_on_target", coordinate_space="goal",
                              player="P9", goal_x=62.0, goal_y=48.0, outcome="Goal"))
    assert len(s) == 3
    assert pt.id and pt.x == 88.0 and pt.outcome == "Saved"
    assert tag_by_key("pass").geometry == "line" and ln.x2 == 60.0
    assert gl.coordinate_space == "goal" and gl.goal_x == 62.0
    # every event has an id
    assert len({e.id for e in s.events}) == 3


def test_metadata_is_nullable_not_faked():
    e = TagEvent(event_type="recovery", coordinate_space="pitch", x=10, y=10)
    assert e.minute is None and e.second is None and e.video_timestamp is None
    assert e.frame is None and e.outcome == ""


# ------------------------------------------------------------------ history
def test_undo_redo_create():
    s = TaggingSession()
    s.add_event(TagEvent(event_type="pass", coordinate_space="pitch", x=1, y=2, x2=3, y2=4))
    assert len(s) == 1 and s.can_undo()
    assert s.undo() and len(s) == 0
    assert s.can_redo() and s.redo() and len(s) == 1


def test_undo_delete_and_edit_and_move():
    s = TaggingSession()
    e = s.add_event(TagEvent(event_type="duel", coordinate_space="pitch", x=50, y=50,
                             outcome="Won", player="P4"))
    s.delete_event(e.id)
    assert len(s) == 0
    s.undo()
    assert len(s) == 1 and s.get(e.id) is not None            # delete undone
    s.edit_event(e.id, player="P7", outcome="Lost")
    assert s.get(e.id).player == "P7"
    s.undo()
    assert s.get(e.id).player == "P4" and s.get(e.id).outcome == "Won"   # edit undone
    s.move_event(e.id, x=12.5, y=80.0)
    assert s.get(e.id).x == 12.5
    s.undo()
    assert s.get(e.id).x == 50.0                              # move undone


def test_multiple_operations_history_order():
    s = TaggingSession()
    for i in range(5):
        s.add_event(TagEvent(event_type="recovery", coordinate_space="pitch", x=i, y=i))
    assert len(s) == 5
    for _ in range(3):
        s.undo()
    assert len(s) == 2
    s.redo()
    assert len(s) == 3
    # a new edit clears the redo stack
    s.add_event(TagEvent(event_type="recovery", coordinate_space="pitch", x=9, y=9))
    assert not s.can_redo()


# ------------------------------------------------------------------ validation
def test_validation_flags_bad_data():
    assert validate_event(TagEvent(event_type="pass", coordinate_space="pitch",
                                   x=10, y=10, x2=None, y2=5))            # missing x2
    assert validate_event(TagEvent(event_type="shot", coordinate_space="pitch",
                                   x=120, y=10))                          # x out of range
    assert validate_event(TagEvent(event_type="save", coordinate_space="pitch",
                                   x=10, y=10))                           # wrong space
    assert validate_event(TagEvent(event_type="duel", coordinate_space="pitch",
                                   x=10, y=10, outcome="Nope"))           # bad outcome
    assert validate_event(TagEvent(event_type="nonexistent"))            # unknown type
    # a clean event validates
    assert validate_event(TagEvent(event_type="pass", coordinate_space="pitch",
                                   x=10, y=10, x2=20, y2=20)) == []


def test_validate_session_reports_per_event():
    s = TaggingSession()
    s.add_event(TagEvent(event_type="shot", coordinate_space="pitch", x=200, y=10))
    s.add_event(TagEvent(event_type="pass", coordinate_space="pitch", x=1, y=1, x2=2, y2=2))
    problems = validate_session(s)
    assert len(problems) == 1 and "0–100" in problems[0][1]


# ------------------------------------------------------------------ export
def test_csv_has_stable_schema_and_blanks_irrelevant_fields():
    s = TaggingSession(match_id="M1")
    s.add_event(TagEvent(event_type="pass", coordinate_space="pitch",
                         x=34.2, y=45.1, x2=62.7, y2=41.2, team="Team A", player="P8"))
    s.add_event(TagEvent(event_type="shot_on_target", coordinate_space="goal",
                         goal_x=83.2, goal_y=42.7, player="P9", outcome="Goal"))
    rows = session_to_rows(s)
    assert list(rows[0].keys()) == list(CSV_COLUMNS)          # deterministic order
    # pass: canonical line coords + goal coords blank
    assert rows[0]["event_type"] == "pass" and rows[0]["end_x"] == 62.7
    assert rows[0]["goal_x"] == "" and rows[0]["goal_y"] == ""
    assert rows[0]["coordinate_space"] == "pitch" and rows[0]["match_id"] == "M1"
    # goal event: emitted as a SHOT (Open-Play compatible) with end_y + shot_result,
    # pitch x/y blank, original tag preserved, raw goal coords kept
    g = rows[1]
    assert g["event_type"] == "shot" and g["tag_type"] == "shot_on_target"
    assert g["shot_result"] == "Goal" and 44 <= float(g["end_y"]) <= 56
    assert g["x"] == "" and g["goal_x"] == 83.2 and g["coordinate_space"] == "goal"
    csv_text = session_to_csv(s)
    assert csv_text.splitlines()[0] == ",".join(CSV_COLUMNS)


def test_csv_coordinates_are_in_range():
    s = TaggingSession()
    s.add_event(TagEvent(event_type="carry", coordinate_space="pitch",
                         x=10, y=20, x2=30, y2=40))
    for row in session_to_rows(s):
        for f in ("x", "y", "end_x", "end_y"):
            if row[f] != "":
                assert 0 <= float(row[f]) <= 100


def test_project_round_trips_with_history():
    s = TaggingSession(match_id="M9", competition="UCL", attack_direction="rl")
    s.add_event(TagEvent(event_type="pass", coordinate_space="pitch", x=1, y=2, x2=3, y2=4))
    s.add_event(TagEvent(event_type="shot", coordinate_space="pitch", x=90, y=50))
    doc = to_project_dict(s, ui_state={"layer": "goal"}, name="Test")
    s2, ui = project_from_dict(doc)
    assert len(s2) == 2 and s2.match_id == "M9" and s2.attack_direction == "rl"
    assert ui == {"layer": "goal"}
    assert s2.can_undo()                                     # history preserved
    s2.undo()
    assert len(s2) == 1


def test_presets_narrow_event_choice_but_schema_extensible():
    assert set(PRESETS["Shooting"]).issubset({t for t in PRESETS["All"]})
    assert "pass" in PRESETS["Passing"] and "pass" not in PRESETS["Goalkeeper"]
