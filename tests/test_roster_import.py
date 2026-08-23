"""Shared roster bulk-import (CSV/Excel) — pure parse/map/coerce logic.

Covers the domain-neutral core reused by both the First-Team squad import and the
Scouting registry import: file reading, tolerant column auto-mapping, per-field
coercion (int/float/bool/list/choices), and row building with skip/issue tracking.
The Streamlit render layer is not exercised here (it is a thin view).
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
import pytest

from fap.ui.components.roster_import import (
    FieldSpec, auto_map, build_rows, coerce, excel_sheets, read_table)


SPECS = [
    FieldSpec("display_name", "Name", ("player", "full name"), required=True),
    FieldSpec("shirt_number", "Shirt number", ("number", "no", "shirt no"), kind="int"),
    FieldSpec("foot", "Preferred foot", ("foot",), choices=("left", "right", "both")),
    FieldSpec("secondary_positions", "Secondary positions", (), kind="list"),
    FieldSpec("market_value", "Market value", ("value",), kind="float"),
]


def _csv(text: str) -> bytes:
    return text.encode()


def test_read_csv_and_headers():
    frame = read_table(_csv("Player,No,Foot\nAda,7,left\n"), "squad.csv")
    assert list(frame.columns) == ["Player", "No", "Foot"]
    assert len(frame) == 1


def test_auto_map_is_tolerant_to_punctuation_and_case():
    headers = ["Player", "Shirt No.", "Preferred Foot", "Value"]
    mapping = auto_map(headers, SPECS)
    assert mapping["display_name"] == "Player"
    assert mapping["shirt_number"] == "Shirt No."
    assert mapping["foot"] == "Preferred Foot"
    assert mapping["market_value"] == "Value"


def test_auto_map_claims_each_header_once():
    # two specs whose aliases could both grab "Name" — only the first wins
    specs = [FieldSpec("a", "Alpha", ("name",)), FieldSpec("b", "Beta", ("name",))]
    mapping = auto_map(["Name"], specs)
    assert mapping == {"a": "Name"}


def test_coerce_kinds():
    assert coerce("7", FieldSpec("n", "N", kind="int")) == (7, None)
    assert coerce("1.5", FieldSpec("v", "V", kind="float")) == (1.5, None)
    assert coerce("yes", FieldSpec("b", "B", kind="bool")) == (True, None)
    assert coerce("CB, RB ; LB", FieldSpec("p", "P", kind="list")) == (["CB", "RB", "LB"], None)


def test_coerce_blank_is_omitted_not_error():
    assert coerce("", FieldSpec("x", "X")) == (None, None)
    assert coerce(float("nan"), FieldSpec("x", "X", kind="int")) == (None, None)


def test_coerce_choice_validation():
    val, err = coerce("Left", FieldSpec("foot", "Foot", choices=("left", "right")))
    assert val == "left" and err is None
    bad, err2 = coerce("sideways", FieldSpec("foot", "Foot", choices=("left", "right")))
    assert bad is None and "not one of" in err2


def test_build_rows_skips_blank_and_reports_missing_required():
    frame = pd.DataFrame([
        {"Player": "Ada", "No": "7", "Foot": "left"},
        {"Player": "", "No": "", "Foot": ""},           # fully blank -> skipped silently
        {"Player": "", "No": "9", "Foot": "right"},     # missing required name -> issue
    ])
    mapping = auto_map(list(frame.columns), SPECS)
    rows, issues = build_rows(frame, SPECS, mapping)
    assert len(rows) == 1
    assert rows[0] == {"display_name": "Ada", "shirt_number": 7, "foot": "left"}
    assert len(issues) == 1 and "Row 3" in issues[0] and "missing" in issues[0]


def test_build_rows_reports_bad_value():
    frame = pd.DataFrame([{"Player": "Ada", "No": "seven"}])
    mapping = auto_map(list(frame.columns), SPECS)
    rows, issues = build_rows(frame, SPECS, mapping)
    assert rows == [] and len(issues) == 1 and "Shirt number" in issues[0]


def _settings(tmp_path):
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    from dataclasses import replace
    return replace(AppSettings(environment="development"),
                   user_data_dir=str(tmp_path / "ud"),
                   database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                   cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))


def _user():
    from fap.identity.models import User
    from fap.identity.roles import Role
    return User(email="coach@club.com", name="Coach", role=Role.SUPER_ADMIN, provider_id="dev")


@pytest.fixture()
def platform(tmp_path):
    from fap.bootstrap import init_platform
    plat = init_platform(settings=_settings(tmp_path))
    yield plat
    try:
        plat.db.close()
    except Exception:
        pass


def test_first_team_callback_creates_players_and_contract(platform):
    """The exact kwargs the First-Team import passes must satisfy the real
    PlayersService (create_player + add_contract) — guards signature drift."""
    user, ws = _user(), None
    ws = platform.workspace_manager.ensure_workspace(user)
    svc = platform.players

    def create_row(row: dict) -> None:                        # mirrors players.py
        contract = {k: row.pop(k) for k in ("contract_end", "market_value") if k in row}
        p = svc.create_player(user, workspace_id=ws.id, **row)
        if any(v for v in contract.values()):
            svc.add_contract(user, p.id, contract_end=contract.get("contract_end", ""),
                             market_value=contract.get("market_value"))

    create_row({"display_name": "Ada Hegerberg", "shirt_number": 14,
                "primary_position": "ST", "foot": "right",
                "secondary_positions": ["CF"], "contract_end": "2027-06-30",
                "market_value": 500000.0})
    create_row({"display_name": "No Contract Player", "primary_position": "CB"})
    players = svc.search(user, workspace_id=ws.id)
    assert {p.name for p in players} == {"Ada Hegerberg", "No Contract Player"}
    ada = next(p for p in players if p.name == "Ada Hegerberg")
    assert ada.shirt_number == 14 and ada.secondary_positions == ["CF"]
    assert svc.current_contract(ada.id).contract_end == "2027-06-30"


def test_scouting_callback_creates_targets(platform):
    """The exact kwargs the Scouting import passes must satisfy the real
    ScoutingService.create_player (positional name + document identity)."""
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    svc = platform.scouting

    def create_row(row: dict) -> None:                        # mirrors scouting.py
        name = str(row.pop("name", "")).strip()
        svc.create_player(user, name, workspace_id=ws.id, player_type="first_team", **row)

    create_row({"name": "Erling Haaland", "club": "Salzburg", "position": "ST",
                "age": 19, "foot": "left", "source": "league export",
                "status": "monitoring", "priority": "high"})
    rows = svc.player_registry(user, filters={"query": "Haaland"}, workspace_id=ws.id)
    assert len(rows) == 1 and rows[0]["club"] == "Salzburg"
    assert rows[0]["operational_id"].startswith("CLB-")


def test_excel_roundtrip():
    frame = pd.DataFrame([{"Player": "Ada", "No": 7}])
    buf = frame.to_excel  # ensure openpyxl path is available
    from io import BytesIO
    bio = BytesIO()
    frame.to_excel(bio, index=False)
    data = bio.getvalue()
    assert "Sheet1" in excel_sheets(data)
    out = read_table(data, "squad.xlsx")
    assert list(out.columns) == ["Player", "No"] and len(out) == 1
