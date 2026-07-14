"""Provider-independent column mapping engine tests.

Covers every alias listed in the spec, best-match + logging when several aliases
are present, manual/session mapping, the preview table, and CSV/Excel parity.
No visualization code is exercised here.
"""
import os
os.environ["FAP_TEST"] = "1"
import matplotlib
matplotlib.use("Agg")
import sys, pathlib, io
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pandas as pd
import pytest
import app


def _clean(cols):
    return app.clean_columns(pd.DataFrame({c: [1, 2] for c in cols}))


# ---- requirement 1: recognise the listed aliases for every field ----
EVENT_ALIASES = ["event_type", "event", "type", "eventname", "event_name",
                 "primary_event", "action", "event action", "Event", "Type"]
X_ALIASES = ["x", "start_x", "location_x", "x_start"]
Y_ALIASES = ["y", "start_y", "location_y", "y_start"]
X2_ALIASES = ["x2", "end_x", "target_x", "destination_x"]
Y2_ALIASES = ["y2", "end_y", "target_y", "destination_y"]


@pytest.mark.parametrize("alias", EVENT_ALIASES)
def test_event_type_aliases(alias):
    df = _clean([alias, "x", "y"])
    mapping, unresolved = app.resolve_column_mapping(df)
    assert "event_type" in mapping and unresolved == []
    assert app.validate_data(app.apply_column_mapping(df, mapping)) == []


@pytest.mark.parametrize("alias", X_ALIASES)
def test_x_aliases(alias):
    df = _clean(["event", alias, "y"])
    mapping, unresolved = app.resolve_column_mapping(df)
    assert mapping.get("x") == app.clean_columns(pd.DataFrame({alias: [1]})).columns[0]
    assert unresolved == []


@pytest.mark.parametrize("alias", Y_ALIASES)
def test_y_aliases(alias):
    df = _clean(["event", "x", alias])
    mapping, unresolved = app.resolve_column_mapping(df)
    assert "y" in mapping and unresolved == []


@pytest.mark.parametrize("alias", X2_ALIASES)
def test_x2_aliases(alias):
    df = _clean(["event", "x", "y", alias])
    mapping, _ = app.resolve_column_mapping(df)
    assert "x2" in mapping


@pytest.mark.parametrize("alias", Y2_ALIASES)
def test_y2_aliases(alias):
    df = _clean(["event", "x", "y", alias])
    mapping, _ = app.resolve_column_mapping(df)
    assert "y2" in mapping


# ---- requirement 2/3: single alias renames; multiple -> best match + log ----
def test_single_alias_renamed_to_canonical():
    df = _clean(["primary_event", "location_x", "location_y"])
    mapping, _ = app.resolve_column_mapping(df)
    mapped = app.apply_column_mapping(df, mapping)
    assert {"event_type", "x", "y"}.issubset(mapped.columns)


def test_multiple_aliases_best_match_and_log():
    # both 'event_type' (canonical) and 'action' present -> canonical wins, log notes the other
    df = _clean(["event_type", "action", "x", "y"])
    mapping, _ = app.resolve_column_mapping(df)
    assert mapping["event_type"] == "event_type"
    logs = app.mapping_log(df, mapping)
    assert any("event" in m.lower() and "action" in m.lower() for m in logs)


def test_best_match_prefers_canonical_over_alias_for_x():
    df = _clean(["event", "x", "start_x", "y"])
    mapping, _ = app.resolve_column_mapping(df)
    assert mapping["x"] == "x"                      # literal beats alias
    assert "start_x" in app.alias_candidates(df)["x"]


# ---- requirement 4/6: manual mapping resolves what auto cannot ----
def test_unmappable_then_manual():
    df = _clean(["foo", "bar", "baz"])
    mapping, unresolved = app.resolve_column_mapping(df)
    assert set(unresolved) == {"event_type", "x", "y"}
    manual = {"event_type": "foo", "x": "bar", "y": "baz"}
    mapping2, unresolved2 = app.resolve_column_mapping(df, manual)
    assert unresolved2 == []
    assert app.validate_data(app.apply_column_mapping(df, mapping2)) == []


def test_validation_fails_only_after_auto_and_manual_fail():
    df = _clean(["foo", "bar", "baz"])
    # no manual -> still unresolved -> would fail
    _, unresolved = app.resolve_column_mapping(df, {})
    assert unresolved  # blocks import (dialog stays open); validate_data would report missing
    assert app.validate_data(df) != []


def test_manual_override_frees_source():
    df = _clean(["event", "label", "yy"])
    mapping, unresolved = app.resolve_column_mapping(df, {"event_type": "label", "x": "event", "y": "yy"})
    assert unresolved == []
    assert mapping["x"] == "event" and mapping["event_type"] == "label"
    assert len(set(mapping.values())) == len(mapping)   # no source used twice


def test_stale_manual_mapping_ignored():
    df = _clean(["event_type", "x", "y"])
    mapping, unresolved = app.resolve_column_mapping(df, {"event_type": "not_here"})
    assert unresolved == [] and mapping["event_type"] == "event_type"


# ---- requirement 7: preview table original -> mapped ----
def test_preview_table_shows_original_and_mapped():
    df = _clean(["primary_event", "location_x", "location_y", "team"])
    mapping, _ = app.resolve_column_mapping(df)
    tbl = app.mapping_preview_table(df, mapping)
    assert list(tbl.columns) == ["Original column", "Mapped to"]
    row = tbl[tbl["Original column"] == "primary_event"].iloc[0]
    assert "Event type" in row["Mapped to"]
    # unmapped column shows a dash
    assert tbl[tbl["Original column"] == "team"].iloc[0]["Mapped to"] == "—"


# ---- requirement 8: CSV and Excel parity ----
def _write_and_read(df, suffix):
    class _Up:
        def __init__(self, name, data): self.name = name; self._d = data
        def read(self): return self._d
        def seek(self, *_): pass
        def __getattr__(self, _): return lambda *a, **k: None
    buf = io.BytesIO()
    if suffix == "csv":
        buf.write(df.to_csv(index=False).encode()); buf.seek(0)
        up = io.BytesIO(buf.getvalue()); up.name = "f.csv"
    else:
        df.to_excel(buf, index=False); buf.seek(0)
        up = io.BytesIO(buf.getvalue()); up.name = "f.xlsx"
    return app.read_uploaded_file(up)


@pytest.mark.parametrize("suffix", ["csv", "xlsx"])
def test_csv_and_excel_map_identically(suffix):
    src = pd.DataFrame({"eventName": ["pass", "shot"], "location_x": [10, 80],
                        "location_y": [40, 50], "end_x": [30, 90], "end_y": [45, 55]})
    loaded = _write_and_read(src, suffix)
    cleaned = app.clean_columns(loaded)
    mapping, unresolved = app.resolve_column_mapping(cleaned)
    assert unresolved == []
    mapped = app.apply_column_mapping(cleaned, mapping)
    assert {"event_type", "x", "y", "x2", "y2"}.issubset(mapped.columns)


def test_norm_key_equivalence():
    assert app._norm_key("Event Action") == app._norm_key("event_action") == "eventaction"
    assert app._norm_key("Start X") == app._norm_key("start_x") == "startx"
