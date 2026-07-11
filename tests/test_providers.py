"""Provider plugin tests: every vendor format parses into a RawDataset and
runs through the full ImportService to a canonical frame."""
import json
from io import BytesIO

import pandas as pd
import pytest

from fap.cache import CacheManager
from fap.config.settings import CacheSettings
from fap.db.engine import Database
from fap.pipeline.importer import ImportService
from fap.pipeline.templates import TemplateRepository
from fap.providers.base import provider_registry
from fap.providers.detection import detect_format


@pytest.fixture()
def importer(tmp_path) -> ImportService:
    return ImportService(CacheManager(CacheSettings(backend="memory")),
                         TemplateRepository(Database(tmp_path / "i.sqlite3")))


# ---------------------------------------------------------------- format detection
def test_format_detection_csv_delimiter_and_encoding():
    data = "event;x;y\npass;10;20\nshot;30;40\n".encode("cp1252")
    fmt = detect_format(data, "data.csv")
    assert fmt.kind == "csv" and fmt.delimiter == ";" and fmt.header_row == 0


def test_format_detection_json_and_xml():
    assert detect_format(b'[{"a": 1}]', "x.json").kind == "json"
    assert detect_format(b"<Games></Games>", "x.xml").kind == "xml"


# ---------------------------------------------------------------- csv/excel end-to-end
def test_csv_import_with_aliases_and_coord_detection(importer):
    csv = ("Action,start_x,origin_y,target_x,end_y,Player Name,Team Name,min\n"
           "Passes,60,40,110,70,Maria,Lions,12\n"
           "Shots,100,40,118,40,Maria,Lions,34\n").encode()
    result = importer.import_file(csv, "match.csv")
    assert result.provider_id == "generic_csv"
    assert result.coord_system == "statsbomb"        # 110/118 x with y<=80
    assert result.frame.loc[0, "event_type"] == "pass"      # cleaned synonym
    assert result.frame.loc[0, "x"] == pytest.approx(50.0)
    assert result.frame.loc[0, "player"] == "Maria"
    assert 0 <= result.quality.overall <= 100


def test_import_cache_hit(importer):
    csv = b"event_type,x,y\npass,10,20\n"
    first = importer.import_file(csv, "m.csv")
    second = importer.import_file(csv, "m.csv")
    assert not first.cache_hit and second.cache_hit
    assert len(second.frame) == len(first.frame)


def test_excel_import(importer, tmp_path):
    df = pd.DataFrame({"event_type": ["pass"], "x": [50], "y": [50], "team": ["A"]})
    path = tmp_path / "m.xlsx"
    df.to_excel(path, index=False)
    result = importer.import_file(path.read_bytes(), "m.xlsx")
    assert result.provider_id == "generic_excel" and len(result.frame) == 1


# ---------------------------------------------------------------- statsbomb
SB_EVENTS = [{
    "type": {"name": "Pass"}, "team": {"name": "Barcelona"},
    "player": {"name": "Xavi"}, "position": {"name": "CM"},
    "minute": 10, "second": 30, "period": 1, "possession": 5,
    "location": [60.0, 40.0], "under_pressure": True,
    "play_pattern": {"name": "Regular Play"},
    "pass": {"end_location": [90.0, 20.0], "length": 30.4, "angle": -0.5,
             "height": {"name": "Ground Pass"}, "recipient": {"name": "Iniesta"},
             "body_part": {"name": "Right Foot"}},
}, {
    "type": {"name": "Shot"}, "team": {"name": "Barcelona"},
    "player": {"name": "Messi"}, "minute": 55, "second": 2, "period": 2,
    "location": [108.0, 36.0],
    "shot": {"end_location": [120.0, 40.0], "statsbomb_xg": 0.31,
             "outcome": {"name": "Goal"}, "body_part": {"name": "Left Foot"}},
}]


def test_statsbomb_provider_and_normalization(importer):
    data = json.dumps(SB_EVENTS).encode()
    result = importer.import_file(data, "statsbomb_events.json")
    assert result.provider_id == "statsbomb"
    assert result.coord_system == "statsbomb"
    f = result.frame
    assert f.loc[0, "x"] == pytest.approx(50.0) and f.loc[0, "y"] == pytest.approx(50.0)
    assert f.loc[0, "receiver"] == "Iniesta" and bool(f.loc[0, "under_pressure"])
    assert f.loc[1, "shot_xg"] == pytest.approx(0.31)
    assert f.loc[1, "shot_result"].lower() == "goal"
    assert f.loc[0, "pass_height"] == "Ground Pass"


# ---------------------------------------------------------------- wyscout
WS_EVENTS = {"events": [{
    "eventName": "Pass", "subEventName": "Simple pass", "teamId": 675,
    "playerId": 3359, "matchPeriod": "1H", "eventSec": 92.5, "matchId": 12345,
    "positions": [{"x": 50, "y": 20}, {"x": 70, "y": 40}],
    "tags": [{"id": 1801}],
}]}


def test_wyscout_provider(importer):
    result = importer.import_file(json.dumps(WS_EVENTS).encode(), "wyscout_match.json")
    f = result.frame
    assert result.coord_system == "wyscout"
    assert f.loc[0, "y"] == pytest.approx(80.0)              # y inverted
    assert f.loc[0, "outcome"] == "successful"               # tag 1801
    assert f.loc[0, "period"] == 1 and f.loc[0, "minute"] == 1


# ---------------------------------------------------------------- opta
OPTA_XML = b"""<Games><Game id="g1" competition_name="League" season_name="2025/26" game_date="2026-02-01">
<Event id="1" type_id="1" period_id="1" min="4" sec="12" team_id="t1" player_id="p9" outcome="1" x="42.1" y="55.3">
  <Q qualifier_id="140" value="68.0"/><Q qualifier_id="141" value="30.5"/>
</Event>
<Event id="2" type_id="16" period_id="2" min="67" sec="3" team_id="t1" player_id="p10" outcome="1" x="88.0" y="52.0"/>
</Game></Games>"""


def test_opta_provider(importer):
    result = importer.import_file(OPTA_XML, "opta_f24_game.xml")
    f = result.frame
    assert result.provider_id == "opta_f24" and result.coord_system == "opta"
    assert f.loc[0, "event_type"] == "pass"
    assert f.loc[0, "end_x"] == pytest.approx(68.0)
    assert f.loc[1, "event_type"] == "shot" and f.loc[1, "shot_result"] == "Goal"
    assert f.loc[0, "competition"] == "League"


# ---------------------------------------------------------------- sportscode
SC_XML = b"""<file><ALL_INSTANCES>
<instance><ID>1</ID><start>62.0</start><end>68.0</end><code>Pass</code>
  <label><group>Player</group><text>N. Keita</text></label>
  <label><group>Team</group><text>Lions</text></label>
  <label><text>build-up</text></label></instance>
<instance><ID>2</ID><start>125.5</start><end>130.0</end><code>Shot</code>
  <label><group>Outcome</group><text>Won</text></label></instance>
</ALL_INSTANCES></file>"""


def test_sportscode_provider(importer):
    result = importer.import_file(SC_XML, "sportscode_timeline.xml")
    f = result.frame
    assert result.provider_id == "sportscode"
    assert f.loc[0, "event_type"] == "pass" and f.loc[0, "player"] == "N. Keita"
    assert f.loc[0, "minute"] == 1
    assert f.loc[1, "outcome"] == "successful"               # "Won" normalized


# ---------------------------------------------------------------- metrica
METRICA_CSV = (b"Team,Type,Subtype,Period,Start Frame,Start Time [s],End Time [s],"
               b"From,To,Start X,Start Y,End X,End Y\n"
               b"Home,PASS,,1,1,3.0,4.5,Player1,Player2,0.5,0.25,0.7,0.5\n")


def test_metrica_provider(importer):
    result = importer.import_file(METRICA_CSV, "metrica_events.csv")
    f = result.frame
    assert result.coord_system == "metrica"
    assert f.loc[0, "x"] == pytest.approx(50.0)
    assert f.loc[0, "y"] == pytest.approx(75.0)              # 0-1 y inverted
    assert f.loc[0, "player"] == "Player1" and f.loc[0, "receiver"] == "Player2"


# ---------------------------------------------------------------- centered-meter vendors
def test_skillcorner_and_second_spectrum_and_tracab(importer):
    sc = json.dumps([{"event_type": "pass", "x": 0.0, "y": 0.0, "player": "A"}]).encode()
    r1 = importer.import_file(sc, "skillcorner_events.json")
    assert r1.frame.loc[0, "x"] == pytest.approx(50.0)

    ss = b'{"event_type": "pass", "x": -52.5, "y": -34.0}\n{"event_type": "shot", "x": 40.0, "y": 10.0}'
    r2 = importer.import_file(ss, "second_spectrum_events.jsonl")
    assert r2.frame.loc[0, "x"] == pytest.approx(0.0)
    assert len(r2.frame) == 2

    tr = b"event_type,x,y\npass,0,0\n"
    r3 = importer.import_file(tr, "tracab_match_events.csv")
    assert r3.coord_system == "tracab"
    assert r3.frame.loc[0, "x"] == pytest.approx(50.0)


# ---------------------------------------------------------------- provider selection
def test_all_required_providers_registered():
    ids = set(provider_registry.ids())
    assert {"generic_csv", "generic_excel", "statsbomb", "wyscout", "opta_f24",
            "hudl", "sportscode", "metrica", "skillcorner_events",
            "tracab_events", "second_spectrum_events", "manual"} <= ids


def test_explicit_provider_choice_overrides_autodetect(importer):
    csv = b"event_type,x,y\npass,10,20\n"
    result = importer.import_file(csv, "anything.csv", provider_id="manual")
    assert result.provider_id == "manual"
