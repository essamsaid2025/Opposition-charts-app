"""P0.5 - Data Hub player-scouting dataset intelligence.

A valid player-scouting table (one row per player, percentile/metric columns) must
be recognised as PLAYER SCOUTING data - not forced through the event pipeline (which
failed with "No objects to concatenate") - analyzed correctly, persisted through the
EXISTING dataset system, and discoverable by the Scouting module. Detection is
row-count agnostic and never keys off the filename. Event datasets are unaffected.

Pure classification/schema tests need only pandas; the registration/discovery tests
run through the real platform (init_platform + WorkspaceManager + ScoutingService).
Fixtures are synthetic (derived from the structure of a scouting export), never the
literal uploaded file.
"""
import os
os.environ["FAP_TEST"] = "1"
import io
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pandas as pd
import pytest

from fap.datahub import classification as cl
from fap.datahub.classification import classify_frame
from fap.datahub.scouting_schema import (
    COUNT, PER_90, PERCENT, RATIO, SCALE_NORMALIZED, SCALE_RAW,
    analyze_player_scouting, classify_metric_unit,
)


# ---------------------------------------------------------------- fixtures (synthetic)
_METRICS = [
    "Non-penalty goals per 90", "npxG per 90", "Progressive passes per 90",
    "Progressive runs per 90", "Duels won, %", "Goal conversion, %",
    "npxG per shot", "Passes", "Shot assists per 90", "xA per 90",
]
_TEAMS = ["Club A", "Club B", "Club C", "Club D"]
_POS = ["CF, LW", "CF", "CF, AMF", "RW"]


def _scouting_frame(n_players: int, *, index_col: bool = True,
                    include=("Team", "Age", "League", "Position", "Birth country"),
                    normalized: bool = True) -> pd.DataFrame:
    """A player-scouting table shaped like a real export: an index artifact column,
    identity + dimensions, then numeric metrics. ``normalized`` keeps every value in
    0..1 (percentile-like), else uses realistic raw magnitudes."""
    rows = []
    for i in range(n_players):
        row = {}
        if index_col:
            row["Unnamed: 0"] = i
        row["Player"] = f"Player {i}"
        if "Team" in include:
            row["Team"] = _TEAMS[i % len(_TEAMS)]
        if "Age" in include:
            row["Age"] = 20 + (i % 15)
        if "League" in include:
            row["League"] = "Malta Premier League 25-26"
        if "Position" in include:
            row["Position"] = _POS[i % len(_POS)]
        if "Birth country" in include:
            row["Birth country"] = "Malta"
        for j, m in enumerate(_METRICS):
            base = ((i * 7 + j * 3) % 100) / 100.0        # deterministic 0..1
            row[m] = base if normalized else round(base * 40 + 1, 2)
        rows.append(row)
    return pd.DataFrame(rows)


def _scouting_csv(n_players: int, **kw) -> bytes:
    return _scouting_frame(n_players, **kw).to_csv(index=False).encode()


_EVENT_CSV = (b"event_type,x,y,team,player,minute,match_id,set_piece\n"
              b"pass,10,20,Home,Salah,1,M1,\n"
              b"shot,90,45,Home,Salah,2,M1,\n"
              b"corner,99,50,Home,Trent,4,M1,corner\n")


# ================================================================ A/B classification
@pytest.mark.parametrize("n", [1, 2, 5, 33, 250])
def test_row_count_agnostic_player_scouting(n):
    """A. + row-count agnostic: 1..hundreds of players all classify identically."""
    c = classify_frame(_scouting_frame(n))
    assert c.dataset_type == cl.PLAYER_SCOUTING
    assert c.entity_type == cl.ENTITY_PLAYER
    assert c.entity_count == n                     # count is metadata, not the type


def test_entity_count_reported_without_changing_type():
    for n in (1, 2, 5, 33):
        c = classify_frame(_scouting_frame(n))
        assert c.entity_count == n
        assert c.dataset_type == cl.PLAYER_SCOUTING


# ================================================================ C index artifact
def test_index_column_ignored():
    a = analyze_player_scouting(_scouting_frame(6, index_col=True))
    assert "Unnamed: 0" in a.schema.ignored
    assert all("unnamed" not in m.name for m in a.schema.metrics)
    # the index column is not counted as a metric
    assert a.metric_count == len(_METRICS)


# ================================================================ D metric units
def test_metric_unit_semantics():
    assert classify_metric_unit("Non-penalty goals per 90") == PER_90
    assert classify_metric_unit("Progressive passes per 90") == PER_90
    assert classify_metric_unit("Goals/90") == PER_90
    assert classify_metric_unit("Duels won, %") == PERCENT
    assert classify_metric_unit("Goal conversion, %") == PERCENT
    assert classify_metric_unit("npxG per shot") == RATIO
    assert classify_metric_unit("Passes") == COUNT


def test_value_scale_normalized_vs_raw():
    """Normalized (percentile) values are flagged, raw magnitudes are not - and the
    numbers are never converted either way."""
    norm = analyze_player_scouting(_scouting_frame(20, normalized=True))
    raw = analyze_player_scouting(_scouting_frame(20, normalized=False))
    assert norm.schema.value_scale == SCALE_NORMALIZED
    assert raw.schema.value_scale == SCALE_RAW


def test_age_is_dimension_not_metric():
    a = analyze_player_scouting(_scouting_frame(10))
    assert a.schema.dimensions.get("age") == "Age"
    assert all(m.source != "Age" for m in a.schema.metrics)


# ================================================================ E no concat error
def test_no_concat_error_on_coordinateless_frame():
    """The historical crash: a coordinate-less frame reaching detect_coordinate_system.
    It must return a null signal, never raise 'No objects to concatenate'."""
    from fap.pipeline.coordinates import detect_coordinate_system
    system, conf = detect_coordinate_system(_scouting_frame(5))
    assert (system, conf) == ("0-100", 0.0)


# ================================================================ H missing optional fields
@pytest.mark.parametrize("drop", ["Team", "Position", "League", "Birth country"])
def test_missing_optional_dimension_still_scouting(drop):
    include = tuple(x for x in ("Team", "Age", "League", "Position", "Birth country")
                    if x != drop)
    c = classify_frame(_scouting_frame(8, include=include))
    assert c.dataset_type == cl.PLAYER_SCOUTING


def test_player_plus_metrics_only_is_scouting():
    frame = _scouting_frame(4, index_col=False, include=())      # Player + metrics only
    c = classify_frame(frame)
    assert c.dataset_type == cl.PLAYER_SCOUTING
    assert c.signals["identity_columns"] == {"player": "Player"}


# ================================================================ I roster / invalid
def test_identity_only_table_is_roster():
    frame = pd.DataFrame({"Player": ["A", "B"], "Team": ["X", "Y"]})
    c = classify_frame(frame)
    assert c.dataset_type == cl.PLAYER_ROSTER
    assert c.entity_type == cl.ENTITY_PLAYER


def test_empty_table_is_unknown():
    assert classify_frame(pd.DataFrame()).dataset_type == cl.UNKNOWN


# ================================================================ J event regression
def test_event_dataset_still_event():
    frame = pd.read_csv(io.BytesIO(_EVENT_CSV))
    c = classify_frame(frame)
    assert c.dataset_type == cl.EVENT
    assert c.entity_type == cl.ENTITY_EVENT


def test_event_with_coordinates_never_scouting():
    # even with player/team identity columns, coordinates make it event data
    frame = pd.read_csv(io.BytesIO(_EVENT_CSV))
    assert not classify_frame(frame).is_player_scouting


# ================================================================ M naming variations
def test_naming_variations_resolve():
    frame = pd.DataFrame({
        "Player Name": ["A", "B"], "Club": ["X", "Y"], "Competition": ["L", "L"],
        "Role": ["CF", "CM"], "Nationality": ["ML", "BR"],
        "Goals per 90": [0.4, 0.2], "xG per 90": [0.3, 0.1], "Passes": [30, 40],
    })
    a = analyze_player_scouting(frame)
    assert a.classification.dataset_type == cl.PLAYER_SCOUTING
    d = a.schema.dimensions
    assert d.get("player") == "Player Name"
    assert d.get("team") == "Club"
    assert d.get("league") == "Competition"
    assert d.get("position") == "Role"
    assert d.get("country") == "Nationality"


# ================================================================ O deterministic
def test_classification_deterministic():
    frame = _scouting_frame(15)
    a = classify_frame(frame).to_dict()
    b = classify_frame(frame).to_dict()
    assert a == b


def test_quality_reports_partial_availability_honestly():
    frame = _scouting_frame(10)
    frame.loc[0:3, "xA per 90"] = None                # inject missingness
    a = analyze_player_scouting(frame)
    miss = next(c for c in a.quality.checks if c.key == "missing")
    assert miss.status == "warn"
    assert a.quality.grade in ("Fair", "Good", "Poor")


# ================================================================ integration (platform)
@pytest.fixture()
def platform_ctx(tmp_path):
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    from fap.bootstrap import init_platform
    from fap.identity.models import User
    from fap.identity.roles import Role
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"),
                       storage=StorageSettings(backend="local"))
    platform = init_platform(settings=settings)
    user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
    ws = platform.workspace_manager.ensure_workspace(user)
    try:
        yield platform, user, ws
    finally:
        platform.db.close()


def test_analyze_routes_scouting_not_event(platform_ctx):
    """E + routing: a scouting CSV analyzes without the concat crash and yields a
    player-scouting result, not an event ImportResult."""
    platform, user, ws = platform_ctx
    ar = platform.datahub.analyze(_scouting_csv(33), "shortlist.csv")
    assert ar.kind == cl.PLAYER_SCOUTING
    assert ar.import_result is None
    assert ar.scouting.summary()["entity_count"] == 33


def test_K_registration_metadata(platform_ctx):
    """K. Registration stores dataset_type/entity_type + semantic schema in the
    EXISTING dataset document via the WorkspaceManager (no second store)."""
    platform, user, ws = platform_ctx
    hub = platform.datahub
    ar = hub.analyze(_scouting_csv(12), "s.csv")
    ds = hub.save_scouting_dataset(user, ar.scouting, name="Shortlist", workspace_id=ws.id)
    assert ds.document["dataset_type"] == cl.PLAYER_SCOUTING
    assert ds.document["entity_type"] == "player"
    assert ds.document["scouting_schema"]["metrics"]
    assert ds.rows == 12
    # persisted frame is retrievable through the shared dataset storage
    assert len(platform.workspace_manager.dataset_frame(ds.id)) == 12
    # health/compatibility are scouting-aware (not red event axes)
    assert "Scouting" in hub.modules_supported(ds.id)


def test_L_scouting_module_discovers_dataset(platform_ctx):
    """L. The Scouting module finds the registered dataset by kind - no filename."""
    platform, user, ws = platform_ctx
    hub = platform.datahub
    ar = hub.analyze(_scouting_csv(20), "whatever.csv")
    ds = hub.save_scouting_dataset(user, ar.scouting, name="Board", workspace_id=ws.id)
    sc = platform.scouting
    avail = sc.available_scouting_datasets(user, workspace_id=ws.id)
    assert any(d["id"] == ds.id and d["players"] == 20 for d in avail)
    schema = sc.scouting_dataset_schema(user, ds.id)
    assert schema and len(schema["metrics"]) == len(_METRICS)
    assert len(sc.scouting_dataset_frame(user, ds.id)) == 20


def test_N_no_filename_dependency(platform_ctx):
    """N. Classification is identical regardless of filename (incl. 'match'/'event')."""
    platform, user, ws = platform_ctx
    hub = platform.datahub
    csv = _scouting_csv(9)
    for name in ("Malta CF.csv", "match.csv", "event_export.csv", "x.csv"):
        assert hub.analyze(csv, name).kind == cl.PLAYER_SCOUTING


def test_J_event_import_unaffected(platform_ctx):
    """J. Event datasets still route to the event pipeline and keep their modules."""
    platform, user, ws = platform_ctx
    hub = platform.datahub
    er = hub.analyze(_EVENT_CSV, "match.csv")
    assert er.kind == "event"
    ds = hub.save_dataset(user, er.import_result, name="vs Rival", workspace_id=ws.id, metadata={})
    assert ds.document.get("dataset_type") is None          # not a scouting dataset
    assert "Open Play" in hub.modules_supported(ds.id)
    # the scouting discovery must NOT pick up an event dataset
    assert all(d["id"] != ds.id for d in platform.scouting.available_scouting_datasets(user, workspace_id=ws.id))
