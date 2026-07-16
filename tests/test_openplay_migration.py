"""Phase 4 - Open Play engine migration.

The data/import/mapping/config business logic moved from app.py into the
platform package fap.openplay. These tests pin: the new home is Streamlit-free,
app.py re-exports the same objects (backward compatibility), and behaviour is
byte-for-byte identical to the platform implementation.
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
import fap.openplay as op
from fap.openplay import config, mapping, transforms, imports as op_imports

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "fap" / "openplay"


# ---------------------------------------------------------------- one-way deps
@pytest.mark.parametrize("module", ["config", "transforms", "mapping", "imports", "runtime"])
def test_controllers_never_import_streamlit(module):
    text = (SRC / f"{module}.py").read_text(encoding="utf-8")
    assert "import streamlit" not in text and "\nimport st" not in text


def test_openplay_does_not_import_app():
    for module in ("config", "transforms", "mapping", "imports", "runtime", "__init__"):
        text = (SRC / f"{module}.py").read_text(encoding="utf-8")
        assert "import app" not in text


# ---------------------------------------------------------------- backward compatibility
MOVED_FUNCS = [
    "read_uploaded_file", "platform_import", "clean_columns", "ensure_columns",
    "validate_data", "normalize_coordinates", "flip_attacking_direction",
    "add_derived_columns", "pct", "safe_count", "is_success", "alias_candidates",
    "platform_detect", "auto_map_columns", "mapping_confidence", "save_mapping_template",
    "mapping_log", "resolve_column_mapping", "apply_column_mapping", "mapping_preview_table",
]
MOVED_CONSTS = [
    "REQUIRED_CANONICAL", "OPTIONAL_CANONICAL", "CANONICAL_LABELS", "DEF_EVENTS",
    "ARROW_EVENTS", "SUCCESS_WORDS", "REQUIRED_MINIMUM", "PITCH_LENGTH", "PITCH_WIDTH",
    "W", "COORD_SYSTEM_IDS", "_APP_TO_PLATFORM", "_PLATFORM_TO_APP", "_norm_key",
]


def test_app_still_exposes_every_migrated_name():
    for name in MOVED_FUNCS + MOVED_CONSTS:
        assert hasattr(app, name), name


def test_app_names_are_the_platform_objects():
    # app re-exports the same function objects, not copies
    for name in MOVED_FUNCS:
        assert getattr(app, name) is getattr(op, name), name
    assert app.add_derived_columns is transforms.add_derived_columns
    assert app.read_uploaded_file is op_imports.read_uploaded_file
    assert app.resolve_column_mapping is mapping.resolve_column_mapping


def test_app_is_only_entry_point_plus_visualization():
    """app.py must no longer DEFINE the migrated helpers (only import them)."""
    source = (pathlib.Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    for name in ("read_uploaded_file", "add_derived_columns", "resolve_column_mapping",
                 "normalize_coordinates", "clean_columns", "platform_import"):
        assert f"def {name}(" not in source, f"app.py still defines {name}"
    # the entry points remain
    assert "def run_app(" in source and "def main(" in source


# ---------------------------------------------------------------- behaviour identical
def test_transforms_behaviour_unchanged():
    df = pd.DataFrame({"event_type": ["pass", "shot"], "x": [10.0, 90.0], "y": [20.0, 50.0],
                       "x2": [30.0, 95.0], "y2": [40.0, 55.0], "minute": [1, 2], "second": [0, 30]})
    d = app.add_derived_columns(app.ensure_columns(df))
    assert list(d["distance"].round(2)) == [pytest.approx(28.28, abs=0.01),
                                            pytest.approx(7.07, abs=0.01)]
    # row0 dx=20 (>8) True; row1 dx=5 (<=8) False - the exact pre-migration rule
    assert list(d["is_forward"]) == [True, False]
    assert d.loc[0, "start_third"] == "Defensive Third"


def test_coordinate_normalization_unchanged():
    df = pd.DataFrame({"x": [60.0], "y": [40.0], "x2": [120.0], "y2": [80.0]})
    out = app.normalize_coordinates(df, "120 x 80")
    assert out.loc[0, "x"] == pytest.approx(50.0) and out.loc[0, "x2"] == pytest.approx(100.0)


def test_import_workflow_through_migrated_controller():
    CSV = b"event_type,x,y,x2,y2\npass,10,20,30,40\nshot,90,50,,\n"
    up = io.BytesIO(CSV); up.name = "m.csv"
    raw = app.read_uploaded_file(up)
    mp, unresolved = app.resolve_column_mapping(app.clean_columns(raw))
    assert unresolved == []
    result = app.platform_import("m.csv", CSV, mp, "0-100", "Data already left-to-right")
    frame = app.add_derived_columns(result.frame)
    assert result.provider_id == "generic_csv" and frame.loc[0, "x"] == pytest.approx(10.0)


def test_config_constants_match_expected_values():
    assert config.REQUIRED_MINIMUM == ["event_type", "x", "y"]
    assert config.COORD_SYSTEM_IDS == {"0-100": "0-100", "120 x 80": "120x80"}
    assert config.SUCCESS_WORDS == ["successful", "success", "complete", "won"]
    assert app.DEF_EVENTS == config.DEF_EVENTS


def test_headless_fallback_without_ui_injection():
    """openplay controllers work with no UI having injected a service."""
    from fap.openplay import runtime
    df = pd.DataFrame(columns=["event_type", "x", "y"])
    # detection uses the headless platform fallback; must not raise
    assert isinstance(mapping.mapping_confidence(df), float)
