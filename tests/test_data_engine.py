"""Universal Football Data Engine tests: column detection, coordinate
detection + normalization, cleaning, validation, quality, filters, templates."""
import numpy as np
import pandas as pd
import pytest

from fap.pipeline.cleaning import clean
from fap.pipeline.columns import detect_columns
from fap.pipeline.coordinates import coord_registry, detect_coordinate_system
from fap.pipeline.filters import FilterSet
from fap.pipeline.pipeline import DataPipeline
from fap.pipeline.quality import score
from fap.pipeline.schema import coerce_schema
from fap.pipeline.templates import TemplateRepository, column_signature
from fap.pipeline.validation import ValidationEngine
from fap.providers.base import RawDataset
from fap.db.engine import Database


# ---------------------------------------------------------------- columns
def test_column_aliases_detected():
    df = pd.DataFrame(columns=["start_x", "origin_y", "target_x", "end_y",
                               "Player Name", "Team Name", "action", "Match Minute"])
    detected = detect_columns(df)
    m = detected.mapping
    assert m["start_x"] == "x" and m["origin_y"] == "y"
    assert m["target_x"] == "end_x" and m["end_y"] == "end_y"
    assert m["Player Name"] == "player" and m["Team Name"] == "team"
    assert m["action"] == "event_type" and m["Match Minute"] == "minute"
    assert detected.overall_confidence > 0.9 and not detected.needs_review


def test_low_confidence_flags_review():
    df = pd.DataFrame(columns=["colA", "colB", "colC"])
    detected = detect_columns(df)
    assert detected.needs_review


# ---------------------------------------------------------------- coordinates
@pytest.mark.parametrize("system,point,expected", [
    ("statsbomb", (60.0, 40.0), (50.0, 50.0)),          # y inverted
    ("statsbomb", (120.0, 0.0), (100.0, 100.0)),
    ("wyscout", (50.0, 20.0), (50.0, 80.0)),
    ("opta", (50.0, 20.0), (50.0, 20.0)),
    ("metrica", (0.5, 0.25), (50.0, 75.0)),
    ("105x68", (52.5, 34.0), (50.0, 50.0)),
    ("skillcorner", (0.0, 0.0), (50.0, 50.0)),
    ("second_spectrum", (-52.5, -34.0), (0.0, 0.0)),
    ("tracab", (5250.0, 3400.0), (100.0, 100.0)),
])
def test_coordinate_normalization(system, point, expected):
    df = pd.DataFrame({"x": [point[0]], "y": [point[1]]})
    out = coord_registry.create(system).to_canonical(df)
    assert out.loc[0, "x"] == pytest.approx(expected[0], abs=0.01)
    assert out.loc[0, "y"] == pytest.approx(expected[1], abs=0.01)


@pytest.mark.parametrize("xs,ys,expected", [
    ([0.1, 0.9], [0.2, 0.8], "metrica"),
    ([110, 30], [70, 20], "statsbomb"),
    ([-40, 40], [-20, 20], "skillcorner"),
    ([-4000, 4000], [-3000, 3000], "tracab"),
    ([10, 95], [15, 90], "0-100"),
    ([10, 103], [5, 60], "105x68"),
])
def test_coordinate_detection(xs, ys, expected):
    system, conf = detect_coordinate_system(pd.DataFrame({"x": xs, "y": ys}))
    assert system == expected and conf > 0.5


# ---------------------------------------------------------------- cleaning
def test_cleaning_normalizes_events_outcomes_bools_duplicates():
    df = coerce_schema(pd.DataFrame({
        "event_type": ["  Passes ", "Take On", "shots", "pass"],
        "x": [10, 20, 30, 10], "y": [10, 20, 30, 10],
        "outcome": ["Accurate", "0", "won", ""],
        "under_pressure": ["yes", "no", "1", ""],
    }))
    df.loc[3] = df.loc[0]  # exact duplicate
    out, log = clean(df)
    assert set(out["event_type"]) == {"pass", "dribble", "shot"}
    assert out["outcome"].tolist()[:3] == ["successful", "unsuccessful", "successful"]
    assert out["under_pressure"].tolist()[:3] == [True, False, True]
    assert len(out) == 3 and any("duplicated" in a for a in log)


# ---------------------------------------------------------------- validation
def test_validation_engine_detects_issues():
    df = coerce_schema(pd.DataFrame({
        "event_type": ["pass", "levitation", "shot"],
        "x": [10, 200, 50], "y": [10, 20, 50],
        "minute": [5, 500, 40], "period": [1, 9, 2],
        "shot_xg": [np.nan, np.nan, 3.5],
    }))
    report = ValidationEngine().run(df)
    codes = {i.code for i in report.issues}
    assert {"coordinates_out_of_range", "impossible_minute",
            "invalid_period", "impossible_xg"} <= codes
    assert "unknown_events" in codes           # levitation
    assert not report.ok
    assert "Validation report" in report.to_markdown()


def test_validation_passes_clean_data():
    df = coerce_schema(pd.DataFrame({
        "event_type": ["pass"] * 3, "x": [10, 20, 30], "y": [10, 20, 30],
        "minute": [1, 2, 3], "team": ["A"] * 3, "player": ["P"] * 3,
        "match_id": ["m1"] * 3,
    }))
    assert ValidationEngine().run(df).ok


# ---------------------------------------------------------------- quality
def test_quality_score_bounds_and_components():
    good = coerce_schema(pd.DataFrame({
        "event_type": ["pass"] * 10, "x": range(10, 20), "y": range(10, 20),
        "minute": range(10), "team": ["A"] * 10, "player": ["P"] * 10,
        "jersey_number": [7] * 10, "match_id": ["m"] * 10,
    }))
    q = score(good)
    assert 0 <= q.overall <= 100 and q.overall > 85
    assert set(q.components) == {"completeness", "coordinate_validity",
                                 "player_information", "event_consistency",
                                 "timeline_consistency"}
    assert score(good.iloc[0:0]).overall == 0.0


# ---------------------------------------------------------------- filters
def _frame():
    df = coerce_schema(pd.DataFrame({
        "event_type": ["pass", "shot", "pass", "carry"],
        "x": [10, 20, 30, 40], "y": [10, 20, 30, 40],
        "minute": [5, 50, 80, 90], "period": [1, 2, 2, 2],
        "outcome": ["successful", "", "unsuccessful", "successful"],
        "body_part": ["left foot", "head", "right foot", ""],
        "player": ["A", "B", "A", "C"], "competition": ["League", "Cup", "League", "League"],
        "shot_xg": [np.nan, 0.4, np.nan, np.nan],
    }))
    df["time_min"] = df["minute"]
    return df


def test_filter_engine_declarative_fields():
    df = _frame()
    out = FilterSet(event_types=("pass",), periods=(2,), outcomes=("unsuccessful",)).apply(df)
    assert len(out) == 1 and out.iloc[0]["player"] == "A"
    assert len(FilterSet(competitions=("league",)).apply(df)) == 3
    assert len(FilterSet(body_parts=("Head",)).apply(df)) == 1
    assert len(FilterSet(minute_range=(45, 95)).apply(df)) == 3


def test_filter_engine_custom_ops():
    df = _frame()
    assert len(FilterSet(custom=(("shot_xg", "gte", 0.3),)).apply(df)) == 1
    assert len(FilterSet(custom=(("player", "in", ("A", "C")),)).apply(df)) == 3
    assert len(FilterSet(custom=(("body_part", "contains", "foot"),)).apply(df)) == 2
    assert FilterSet().to_dict()["custom"] == []   # serializable
    restored = FilterSet.from_dict(FilterSet(custom=(("x", "between", (15, 35)),)).to_dict())
    assert len(restored.apply(df)) == 2


# ---------------------------------------------------------------- templates
def test_template_roundtrip_and_signature(tmp_path):
    repo = TemplateRepository(Database(tmp_path / "t.sqlite3"))
    cols = ["PosX", "PosY", "Action"]
    repo.save("Club tagging v1", "generic_csv", cols,
              {"PosX": "x", "PosY": "y", "Action": "event_type"})
    found = repo.find_by_signature(["action", "posy", "posx"])   # order/case-insensitive
    assert found is not None and found.mapping["PosX"] == "x"
    assert repo.find_by_signature(["totally", "different"]) is None
    assert column_signature(cols) == column_signature(list(reversed(cols)))


# ---------------------------------------------------------------- pipeline perf contract
def test_pipeline_backward_compat_and_derived_fields():
    raw = RawDataset(
        frame=pd.DataFrame({"event_type": ["pass"], "x": [60.0], "y": [40.0],
                            "x2": [120.0], "y2": [80.0]}),
        native_coord_system="120x80",
    )
    df = DataPipeline().run(raw)
    assert df.loc[0, "x"] == pytest.approx(50.0)
    assert df.loc[0, "end_x"] == pytest.approx(100.0)
    assert df.loc[0, "x2"] == pytest.approx(100.0)          # legacy alias intact
    assert df.loc[0, "into_final_third"]
    assert df.loc[0, "pass_length"] > 0                      # derived when missing
    assert "y_plot" in df.columns
