"""Open Play <-> platform import migration (Phase 2B.1B).

Open Play no longer calls pandas directly: read_uploaded_file goes through the
platform provider registry, and the main flow runs ImportService end to end.
These tests pin the migration:

  * read_uploaded_file keeps its contract (uploaded file -> raw DataFrame)
  * it gains every registered format, JSON included, without app.py knowing
  * platform_import produces the exact frame Open Play's charts expect
  * the coordinate/flip selectboxes still mean what they meant before
No visualization code is exercised here.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys, pathlib, io, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest

import app


def _upload(data: bytes, name: str):
    up = io.BytesIO(data)
    up.name = name
    return up


CSV = b"event_type,x,y,x2,y2,player\npass,10,20,30,40,Ada\nshot,90,50,,,Bo\n"


# ---------------------------------------------------------------- read_uploaded_file contract
def test_read_uploaded_file_still_returns_raw_frame():
    frame = app.read_uploaded_file(_upload(CSV, "m.csv"))
    assert isinstance(frame, pd.DataFrame)
    assert list(frame.columns) == ["event_type", "x", "y", "x2", "y2", "player"]
    assert len(frame) == 2


def test_read_uploaded_file_now_reads_json_through_the_platform():
    data = json.dumps([{"event_type": "pass", "x": 10, "y": 20},
                       {"event_type": "shot", "x": 90, "y": 50}]).encode()
    frame = app.read_uploaded_file(_upload(data, "events.json"))
    assert len(frame) == 2 and "event_type" in frame.columns


def test_read_uploaded_file_rejects_unsupported_type_as_valueerror():
    # back-compat: the UI catches ValueError and shows "Could not read file"
    with pytest.raises(ValueError):
        app.read_uploaded_file(_upload(b"irrelevant", "notes.docx"))


def test_excel_still_loads():
    df = pd.DataFrame({"event_type": ["pass"], "x": [50], "y": [50]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    frame = app.read_uploaded_file(_upload(buf.getvalue(), "m.xlsx"))
    assert len(frame) == 1


# ---------------------------------------------------------------- platform_import
def _mapping(frame: pd.DataFrame) -> dict:
    mapping, unresolved = app.resolve_column_mapping(app.clean_columns(frame))
    assert not unresolved
    return mapping


def test_platform_import_produces_the_open_play_chart_contract():
    """Every column add_derived_columns and the charts rely on must exist."""
    result = app.platform_import("m.csv", CSV, _mapping(app.read_uploaded_file(_upload(CSV, "m.csv"))),
                                 "0-100", "Data already left-to-right")
    df = app.add_derived_columns(result.frame)
    for col in ("event_type", "x", "y", "x2", "y2", "minute", "second", "period",
                "team", "opponent", "player", "receiver", "outcome", "shot_result",
                "body_part", "phase", "sequence_id"):
        assert col in df.columns, col
    for col in ("distance", "is_forward", "is_backward", "is_lateral", "is_progressive",
                "into_final_third", "into_box", "in_box", "start_third", "lane",
                "time_min", "shot_distance"):
        assert col in df.columns, col
    assert result.provider_id == "generic_csv"


def test_platform_import_matches_the_legacy_pipeline_numerically():
    """The migrated path must agree with the pre-migration app-local pipeline."""
    raw = app.read_uploaded_file(_upload(CSV, "m.csv"))
    cleaned = app.clean_columns(raw)
    mapping = _mapping(raw)

    legacy = app.add_derived_columns(app.flip_attacking_direction(
        app.normalize_coordinates(app.ensure_columns(app.apply_column_mapping(cleaned, mapping)),
                                  "0-100"),
        "Data already left-to-right"))
    migrated = app.add_derived_columns(
        app.platform_import("m.csv", CSV, mapping, "0-100", "Data already left-to-right").frame)

    for col in ("x", "y", "x2", "y2", "distance", "shot_distance", "time_min"):
        pd.testing.assert_series_equal(migrated[col].reset_index(drop=True),
                                       legacy[col].reset_index(drop=True),
                                       check_names=False, check_dtype=False)
    for col in ("is_forward", "is_progressive", "into_final_third", "in_box"):
        assert list(migrated[col]) == list(legacy[col]), col


def test_coord_mode_120x80_normalizes_like_before():
    csv = b"event_type,x,y,x2,y2\npass,60,40,120,80\n"
    mapping = _mapping(app.read_uploaded_file(_upload(csv, "m.csv")))
    migrated = app.platform_import("m.csv", csv, mapping, "120 x 80",
                                   "Data already left-to-right").frame
    assert migrated.loc[0, "x"] == pytest.approx(50.0)
    assert migrated.loc[0, "y"] == pytest.approx(50.0)
    assert migrated.loc[0, "x2"] == pytest.approx(100.0)


def test_attack_direction_flip_still_mirrors_x_only():
    csv = b"event_type,x,y,x2,y2\npass,10,20,30,40\n"
    mapping = _mapping(app.read_uploaded_file(_upload(csv, "m.csv")))
    flipped = app.platform_import(
        "m.csv", csv, mapping, "0-100",
        "Team attacks right-to-left in data (flip to left-to-right)").frame
    assert flipped.loc[0, "x"] == pytest.approx(90.0)
    assert flipped.loc[0, "x2"] == pytest.approx(70.0)
    assert flipped.loc[0, "y"] == pytest.approx(20.0)   # y untouched, as before


def test_open_play_json_import_end_to_end():
    data = json.dumps({"events": [
        {"event_type": "pass", "start": {"x": 10, "y": 20}, "end": {"x": 30, "y": 40}},
        {"event_type": "carry", "start": {"x": 50, "y": 50}, "end": {"x": 60, "y": 55}},
    ]}).encode()
    raw = app.read_uploaded_file(_upload(data, "feed.json"))
    assert "start_x" in raw.columns          # flattened by the generic JSON provider
    mapping, unresolved = app.resolve_column_mapping(app.clean_columns(raw))
    assert not unresolved                    # start_x/start_y resolve via the alias engine
    df = app.add_derived_columns(
        app.platform_import("feed.json", data, mapping, "0-100",
                            "Data already left-to-right").frame)
    assert len(df) == 2 and df.loc[0, "x"] == pytest.approx(10.0)


def test_platform_import_reports_validation_and_quality():
    """Open Play now gets the platform's validation + quality for free."""
    result = app.platform_import("m.csv", CSV, _mapping(app.read_uploaded_file(_upload(CSV, "m.csv"))),
                                 "0-100", "Data already left-to-right")
    assert 0 <= result.quality.overall <= 100
    assert result.validation is not None
