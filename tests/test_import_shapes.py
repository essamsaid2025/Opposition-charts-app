"""Single-kind import shapes: files with no event_type column.

A bare ``x,y`` heat-map dump, a shot map (``x,y,xG,result,bodyPart,…``) and a
manual pass export (a single qualifier column + start/end coords) used to fail
import with *"Missing required column: event_type"*. The importer now infers the
one event kind from the columns and injects it, so these per-player exports flow
through the normal pipeline. A genuine event log is never reinterpreted.
"""
import pandas as pd
import pytest

from fap.cache import CacheManager
from fap.config.settings import CacheSettings
from fap.db.engine import Database
from fap.pipeline.importer import ImportService
from fap.pipeline.shapes import (
    infer_event_shape, looks_like_pass_qualifiers)
from fap.pipeline.templates import TemplateRepository
from fap.providers.base import load_builtin_providers
from fap.visuals import analysis as A

load_builtin_providers()


@pytest.fixture
def importer(tmp_path):
    return ImportService(CacheManager(CacheSettings(backend="memory")),
                         TemplateRepository(Database(tmp_path / "s.sqlite3")))


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


# ------------------------------------------------------------ pure inference
def test_infer_touch_from_bare_xy():
    shape = infer_event_shape(["x", "y"])
    assert shape and shape.event_type == "touch"


def test_infer_shot_from_shotmap_columns():
    shape = infer_event_shape(["x", "y", "xG", "xGOT", "result", "bodyPart", "minute"])
    assert shape and shape.event_type == "shot"
    assert shape.extra_mapping.get("result") == "shot_result"


def test_infer_none_when_event_column_present():
    assert infer_event_shape(["Event", "X", "Y", "X2", "Y2"]) is None


def test_infer_none_without_coordinates():
    assert infer_event_shape(["x", "minute"]) is None


def test_pass_qualifiers_guard():
    assert looks_like_pass_qualifiers(["Accurate", "Inaccurate", "Key pass", "Assist"])
    assert not looks_like_pass_qualifiers(["pass", "shot"])   # real events
    assert not looks_like_pass_qualifiers([])


# ------------------------------------------------------------ end-to-end import
def test_heatmap_imports_as_touches(importer):
    df = pd.DataFrame({"x": [48.6, 71.5, 94.6, 34.0], "y": [38.2, 15.8, 26.4, 28.7]})
    res = importer.import_file(_csv(df), "player_heatmap.csv")
    assert res.validation.ok
    assert res.summary["inferred_event_type"] == "touch"
    assert set(res.frame["event_type"].unique()) == {"touch"}
    assert res.frame["x"].between(0, 100).all()


def test_shotmap_imports_as_shots(importer):
    df = pd.DataFrame({
        "x": [94.0, 93.8, 95.0], "y": [22.1, 38.2, 32.2],
        "xG": [0.05, 0.13, 0.17], "xGOT": [0.0, 0.0, 0.68],
        "result": ["Post", "Miss", "Goal"], "bodyPart": ["RightFoot", "RightFoot", "Header"],
        "minute": [4, 56, 54]})
    res = importer.import_file(_csv(df), "player_shotmap.csv")
    assert res.validation.ok
    assert res.summary["inferred_event_type"] == "shot"
    shots = A.shots(res.frame)
    assert len(shots) == 3
    assert shots["shot_xg"].notna().all()
    assert (shots["shot_result"].str.lower() == "goal").sum() == 1


def test_pass_qualifier_file_imports_as_passes(importer):
    df = pd.DataFrame({
        "Event": ["Accurate", "inaccurate", "Key pass", "Assist"],
        "X": [45, 92, 75, 98], "Y": [94, 89, 93, 70],
        "X2": [43, 75, 81, 97], "Y2": [53, 87, 73, 51]})
    res = importer.import_file(_csv(df), "pass_events.csv")
    assert res.validation.ok
    assert res.summary["inferred_event_type"] == "pass"
    assert set(res.frame["event_type"].unique()) == {"pass"}
    assert len(A.passes(res.frame)) == 4
    # the qualifier column became the outcome: Accurate/inaccurate normalize
    outcomes = set(res.frame["outcome"].str.lower())
    assert "successful" in outcomes and "unsuccessful" in outcomes
    assert res.frame["end_x"].notna().all()


def test_explicit_constant_overrides_inference(importer):
    df = pd.DataFrame({"x": [10, 20], "y": [30, 40]})
    res = importer.import_file(_csv(df), "h.csv", constants={"event_type": "carry"})
    assert set(res.frame["event_type"].unique()) == {"carry"}


def test_real_event_log_is_never_reinterpreted(importer):
    df = pd.DataFrame({
        "event_type": ["pass", "shot", "carry"],
        "x": [10, 90, 50], "y": [20, 40, 55],
        "end_x": [20, 95, 60], "end_y": [25, 45, 50]})
    res = importer.import_file(_csv(df), "real.csv")
    assert res.summary["inferred_event_type"] is None
    assert set(res.frame["event_type"].unique()) == {"pass", "shot", "carry"}
