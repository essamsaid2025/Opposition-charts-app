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


# ---------------------------------------------------------------- Phase 2B.2: unified mapping
def test_open_play_has_no_alias_table_of_its_own():
    """The platform is the only mapping engine. If this fails, a duplicate
    alias list has crept back into Open Play."""
    assert not hasattr(app, "COLUMN_ALIASES")


def test_app_aliases_come_from_the_platform():
    from fap.pipeline.columns import ALIASES
    # Open Play's fields are expressed in the platform's canonical vocabulary
    assert app._APP_TO_PLATFORM == {"event_type": "event_type", "x": "x", "y": "y",
                                    "x2": "end_x", "y2": "end_y"}
    for plat_field in app._APP_TO_PLATFORM.values():
        assert plat_field in ALIASES


def test_norm_key_is_the_platform_normalizer():
    from fap.pipeline.columns import normalize_name
    assert app._norm_key is normalize_name


# --- legacy parity: the mapped columns must be identical to the pre-2B.2 engine ---
LEGACY_HEADERS = [
    ["event_type", "x", "y"],
    ["event", "start_x", "start_y", "end_x", "end_y"],
    ["primary_event", "location_x", "location_y", "destination_x", "destination_y"],
    ["Event Name", "X Start", "Y Start", "target_x", "target_y"],
    ["type", "x_coord", "y_coord", "x_end", "y_end"],
    ["action", "pos_x", "pos_y", "pass_end_x", "pass_end_y"],
]


@pytest.mark.parametrize("headers", LEGACY_HEADERS)
def test_legacy_headers_still_map_to_canonical(headers):
    df = app.clean_columns(pd.DataFrame({h: [1, 2] for h in headers}))
    mapping, unresolved = app.resolve_column_mapping(df)
    assert unresolved == []
    mapped = app.apply_column_mapping(df, mapping)
    assert {"event_type", "x", "y"}.issubset(mapped.columns)
    if len(headers) > 3:
        assert {"x2", "y2"}.issubset(mapped.columns)


def _frame(headers):
    rows = {h: ([10, 80] if "x" in h.lower() else [40, 50]) for h in headers}
    rows[headers[0]] = ["pass", "shot"]
    return pd.DataFrame(rows)


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "json"])
def test_legacy_csv_excel_json_produce_identical_mapped_columns(fmt):
    """Same logical file in three formats -> identical mapped canonical columns."""
    headers = ["event_type", "location_x", "location_y", "end_x", "end_y"]
    src = _frame(headers)
    if fmt == "csv":
        data, name = src.to_csv(index=False).encode(), "legacy.csv"
    elif fmt == "xlsx":
        buf = io.BytesIO(); src.to_excel(buf, index=False)
        data, name = buf.getvalue(), "legacy.xlsx"
    else:
        data, name = src.to_json(orient="records").encode(), "legacy.json"

    cleaned = app.clean_columns(app.read_uploaded_file(_upload(data, name)))
    mapping, unresolved = app.resolve_column_mapping(cleaned)
    assert unresolved == []
    mapped = app.apply_column_mapping(cleaned, mapping)
    assert {"event_type", "x", "y", "x2", "y2"}.issubset(mapped.columns)

    df = app.add_derived_columns(
        app.platform_import(name, data, mapping, "0-100", "Data already left-to-right").frame)
    assert list(df["x"]) == [10.0, 80.0]
    assert list(df["event_type"]) == ["pass", "shot"]


def test_mapping_confidence_high_for_clean_headers_skips_dialog():
    df = app.clean_columns(pd.DataFrame({"event_type": ["pass"], "x": [1], "y": [2]}))
    from fap.pipeline.columns import CONFIDENCE_THRESHOLD
    assert app.mapping_confidence(df) >= CONFIDENCE_THRESHOLD


def test_mapping_confidence_low_for_unmappable_headers_opens_dialog():
    df = app.clean_columns(pd.DataFrame({"foo": [1], "bar": [2], "baz": [3]}))
    from fap.pipeline.columns import CONFIDENCE_THRESHOLD
    assert app.mapping_confidence(df) < CONFIDENCE_THRESHOLD


def test_mapping_confidence_ignores_absent_optional_fields():
    """A file with no player/team column must still import without the dialog."""
    df = app.clean_columns(pd.DataFrame({"event_type": ["pass"], "x": [1], "y": [2]}))
    assert app.mapping_confidence(df) == pytest.approx(1.0)


# ---------------------------------------------------------------- template system
def _isolated_service(tmp_path):
    from fap.cache import CacheManager
    from fap.config.settings import CacheSettings
    from fap.db.engine import Database
    from fap.pipeline.importer import ImportService
    from fap.pipeline.templates import TemplateRepository
    return ImportService(CacheManager(CacheSettings(backend="memory")),
                         TemplateRepository(Database(tmp_path / "t.sqlite3")))


def test_save_template_then_autoload_maps_unmappable_headers(tmp_path, monkeypatch):
    """A saved template teaches the platform a shape it cannot guess: the next
    file with the same columns maps itself, with no dialog."""
    svc = _isolated_service(tmp_path)
    monkeypatch.setattr(app, "import_service", lambda: svc)

    df = app.clean_columns(pd.DataFrame({"gps_code": ["pass"], "cx": [10], "cy": [20]}))
    assert app.mapping_confidence(df) < 1.0          # not guessable from aliases alone

    manual = {"event_type": "gps_code", "x": "cx", "y": "cy"}
    app.save_mapping_template("Custom GPS", df, manual, "gps.csv")

    detected, template_used = app.platform_detect(df)
    assert template_used == "Custom GPS"
    assert app.auto_map_columns(df) == manual
    assert app.mapping_confidence(df) == pytest.approx(1.0)


def test_saved_template_stores_platform_canonical_names(tmp_path, monkeypatch):
    """x2/y2 are Open Play's names; templates must persist the platform's."""
    svc = _isolated_service(tmp_path)
    monkeypatch.setattr(app, "import_service", lambda: svc)

    df = app.clean_columns(pd.DataFrame({"a": ["pass"], "b": [1], "c": [2], "d": [3], "e": [4]}))
    app.save_mapping_template("Third Party CSV", df,
                              {"event_type": "a", "x": "b", "y": "c", "x2": "d", "y2": "e"},
                              "third.csv")
    stored = svc._templates.list_all()[0]
    assert stored.name == "Third Party CSV"
    assert stored.mapping == {"a": "event_type", "b": "x", "c": "y", "d": "end_x", "e": "end_y"}
    assert stored.provider_id == "generic_csv"


# ------------------------------------------------ Phase 2B (preview/import unify)
# A StatsBomb export a club uploads under a neutral name. Before the fix the
# preview loaded it as generic JSON (columns `location`, `type_name`) and the
# mapping dialog opened; the import meanwhile loaded it as StatsBomb. The two
# paths must now resolve the SAME provider.
SB_NEUTRAL = json.dumps([{
    "type": {"name": "Pass"}, "team": {"name": "Barca"},
    "player": {"name": f"P{i}"}, "minute": i, "second": 1, "period": 1,
    "location": [40.0 + i, 30.0 + i],
    "pass": {"end_location": [60.0 + i, 50.0], "statsbomb_xg": 0.1},
} for i in range(20)]).encode()


def test_preview_and_import_resolve_the_same_provider():
    """The core Phase 2B fix: one provider-resolution path for both."""
    svc = app.import_service()
    preview = svc.inspect(SB_NEUTRAL, "events.json")
    result = svc.import_file(SB_NEUTRAL, "events.json")
    assert preview.provider_id == result.provider_id == "statsbomb"


def test_read_uploaded_file_uses_intelligent_detection_not_filename():
    """A renamed StatsBomb file yields x/y in the preview frame, not `location`."""
    frame = app.clean_columns(app.read_uploaded_file(_upload(SB_NEUTRAL, "events.json")))
    assert "x" in frame.columns and "y" in frame.columns
    assert "location" not in frame.columns


def test_renamed_vendor_file_imports_without_the_mapping_dialog():
    """The exact UI symptom: no unresolved fields, confidence above threshold."""
    from fap.pipeline.columns import CONFIDENCE_THRESHOLD
    raw = app.clean_columns(app.read_uploaded_file(_upload(SB_NEUTRAL, "events.json")))
    mapping, unresolved = app.resolve_column_mapping(raw)
    assert unresolved == []
    assert app.mapping_confidence(raw) >= CONFIDENCE_THRESHOLD


def test_inspect_frame_matches_the_provider_the_import_loads():
    """inspect's raw frame is exactly what the resolved provider produced."""
    svc = app.import_service()
    preview = svc.inspect(SB_NEUTRAL, "events.json")
    from fap.providers.base import provider_registry
    direct = provider_registry.create("statsbomb").load(io.BytesIO(SB_NEUTRAL), "events.json")
    assert list(preview.frame.columns) == list(direct.frame.columns)
    assert len(preview.frame) == len(direct.frame)


def test_generic_file_preview_still_falls_back_identically():
    """A file no signature recognizes resolves to the same generic provider in
    both paths - backward compatibility for plain CSV/Excel/JSON."""
    svc = app.import_service()
    csv = b"foo,bar,baz\n1,2,3\n"
    assert svc.inspect(csv, "mystery.csv").provider_id == "generic_csv"
    plain = json.dumps([{"a": 1, "b": 2}]).encode()
    assert svc.inspect(plain, "plain.json").provider_id == "generic_json"
