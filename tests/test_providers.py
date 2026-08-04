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


# ---------------------------------------------------------------- generic json
def test_json_list_of_objects(importer):
    data = json.dumps([{"event_type": "pass", "x": 10, "y": 20, "player": "Ada"},
                       {"event_type": "shot", "x": 90, "y": 50, "player": "Ada"}]).encode()
    result = importer.import_file(data, "events.json")
    assert result.provider_id == "generic_json"
    assert len(result.frame) == 2
    assert result.frame.loc[0, "event_type"] == "pass"


def test_json_nested_event_array_is_found_and_flattened(importer):
    data = json.dumps({
        "match": {"id": 7, "competition": "Prem"},
        "events": [{"type": "pass", "start": {"x": 10, "y": 20}, "player": {"name": "Ada"}},
                   {"type": "shot", "start": {"x": 90, "y": 50}, "player": {"name": "Bo"}}],
    }).encode()
    raw = provider_registry.create("generic_json").load(BytesIO(data), "feed.json")
    # nested objects flattened with parent_child names, unknown fields preserved
    assert "start_x" in raw.frame.columns and "player_name" in raw.frame.columns
    assert raw.meta["record_path"] == "events"
    assert list(raw.frame["player_name"]) == ["Ada", "Bo"]


def test_json_dictionary_root_of_records():
    data = json.dumps({"e1": {"type": "pass", "x": 1, "y": 2},
                       "e2": {"type": "shot", "x": 3, "y": 4}}).encode()
    raw = provider_registry.create("generic_json").load(BytesIO(data), "d.json")
    assert len(raw.frame) == 2 and set(raw.frame["type"]) == {"pass", "shot"}


def test_json_single_object_root_is_one_row():
    data = json.dumps({"type": "pass", "x": 1, "y": 2}).encode()
    raw = provider_registry.create("generic_json").load(BytesIO(data), "one.json")
    assert len(raw.frame) == 1


def test_json_lines_supported():
    data = b'{"event_type": "pass", "x": 1, "y": 2}\n{"event_type": "shot", "x": 3, "y": 4}\n'
    raw = provider_registry.create("generic_json").load(BytesIO(data), "e.jsonl")
    assert len(raw.frame) == 2


def test_json_explicit_record_path_option():
    data = json.dumps({"a": {"rows": [{"x": 1}, {"x": 2}]},
                       "decoys": [{"x": 9}, {"x": 9}, {"x": 9}]}).encode()
    raw = provider_registry.create("generic_json").load(
        BytesIO(data), "p.json", options={"record_path": "a.rows"})
    assert len(raw.frame) == 2 and list(raw.frame["x"]) == [1, 2]


def test_json_invalid_raises_provider_error():
    from fap.core.exceptions import ProviderError
    with pytest.raises(ProviderError):
        provider_registry.create("generic_json").load(BytesIO(b"{nope"), "bad.json")


def test_generic_json_never_steals_vendor_json(importer):
    """Vendor plugins outrank the category="file" catch-all."""
    data = json.dumps(SB_EVENTS).encode()
    assert importer.pick_provider("statsbomb_events.json").info.id == "statsbomb"
    assert importer.pick_provider("wyscout_events.json").info.id == "wyscout"
    assert importer.pick_provider("plain_events.json").info.id == "generic_json"
    assert importer.import_file(data, "statsbomb_events.json").provider_id == "statsbomb"


def test_generic_json_registered():
    assert "generic_json" in set(provider_registry.ids())


# ================================================================ opta — deep vocabulary
# A cross-from-corner, a through-ball assist, a headed shot on target, and a red
# card - each exercising qualifier ids the old 1-qualifier parser ignored.
OPTA_DEEP = b"""<Games><Game id="g2" competition_name="UCL" season_name="2025/26" game_date="2026-03-01">
<Event id="1" type_id="1" period_id="1" min="5" sec="10" team_id="10" player_id="100" outcome="1" x="80" y="90">
  <Q qualifier_id="2"/><Q qualifier_id="6"/><Q qualifier_id="140" value="95.0"/><Q qualifier_id="141" value="50.0"/>
</Event>
<Event id="2" type_id="1" period_id="1" min="6" sec="20" team_id="10" player_id="101" outcome="1" x="60" y="50">
  <Q qualifier_id="4"/><Q qualifier_id="210"/>
</Event>
<Event id="3" type_id="15" period_id="1" min="7" sec="0" team_id="10" player_id="102" outcome="0" x="88" y="45">
  <Q qualifier_id="15"/>
</Event>
<Event id="4" type_id="17" period_id="2" min="80" sec="0" team_id="10" player_id="103" outcome="0" x="0" y="0">
  <Q qualifier_id="33"/>
</Event>
</Game></Games>"""


def _opta_load(options=None):
    return provider_registry.create("opta_f24").load(BytesIO(OPTA_DEEP), "opta_deep.xml",
                                                     options=options)


def test_opta_qualifiers_resolve_subtypes():
    f = _opta_load().frame
    # cross from a corner -> its own canonical event_type + set piece resolved
    assert f.loc[0, "event_type"] == "cross"
    assert f.loc[0, "set_piece"] == "Corner"
    assert f.loc[0, "end_x"] == pytest.approx(95.0)
    # through ball that is an assist -> sub-type + assist/key_pass flags
    assert f.loc[1, "event_type"] == "pass" and f.loc[1, "sub_event"] == "through ball"
    assert bool(f.loc[1, "assist"]) and bool(f.loc[1, "key_pass"])


def test_opta_shot_bodypart_and_card():
    f = _opta_load().frame
    # attempt-saved header -> shot, on-target "Saved", head body part
    assert f.loc[2, "event_type"] == "shot"
    assert f.loc[2, "shot_result"] == "Saved" and f.loc[2, "body_part"] == "head"
    # red-card qualifier -> card event with the colour resolved
    assert f.loc[3, "event_type"] == "card" and f.loc[3, "sub_event"] == "red card"


def test_opta_name_resolution_with_lineup():
    lineup = {"teams": {"10": "Real Madrid"},
              "players": {"100": "Vinicius", "101": "Bellingham",
                          "102": "Mbappe", "103": "Ruediger"}}
    ds = _opta_load(options={"lineup_data": lineup})
    f = ds.frame
    assert f.loc[0, "team"] == "Real Madrid" and f.loc[0, "player"] == "Vinicius"
    assert f.loc[1, "player"] == "Bellingham"
    assert ds.meta["name_resolution"] == "resolved" and ds.meta["unresolved_players"] == []


def test_opta_name_resolution_nested_lineup_shape():
    lineup = {"teams": [{"id": "10", "name": "Real Madrid",
                         "players": [{"id": "100", "name": "Vinicius"}]}]}
    f = _opta_load(options={"lineup_data": lineup}).frame
    assert f.loc[0, "team"] == "Real Madrid" and f.loc[0, "player"] == "Vinicius"


def test_opta_falls_back_to_ids_without_lineup():
    ds = _opta_load()
    f = ds.frame
    assert f.loc[0, "team"] == "10" and f.loc[0, "player"] == "100"   # raw ids kept
    assert ds.meta["name_resolution"] == "ids_only"
    assert "100" in ds.meta["unresolved_players"]


def test_opta_backwards_compatible_and_robust():
    # original fixture still parses exactly as before
    f = provider_registry.create("opta_f24").load(BytesIO(OPTA_XML), "opta_f24_game.xml").frame
    assert f.loc[0, "event_type"] == "pass" and f.loc[1, "shot_result"] == "Goal"
    # a malformed x value must not raise (row kept, x is NaN)
    bad = b'<Games><Game id="g"><Event id="1" type_id="1" x="oops" y="5"/></Game></Games>'
    f2 = provider_registry.create("opta_f24").load(BytesIO(bad), "opta.xml").frame
    assert len(f2) == 1 and pd.isna(f2.loc[0, "x"])


# ================================================================ wyscout — deep vocabulary
WS_DEEP = {"events": [
    {"eventName": "Pass", "subEventName": "Cross", "teamId": 675, "playerId": 10,
     "matchPeriod": "1H", "eventSec": 30, "positions": [{"x": 80, "y": 90}, {"x": 95, "y": 50}],
     "tags": [{"id": 301}, {"id": 402}, {"id": 1801}]},
    {"eventName": "Shot", "subEventName": "Shot", "teamId": 675, "playerId": 11,
     "matchPeriod": "2H", "eventSec": 600, "positions": [{"x": 88, "y": 45}],
     "tags": [{"id": 403}, {"id": 101}]},
    {"eventName": "Foul", "subEventName": "", "teamId": 675, "playerId": 12,
     "matchPeriod": "2H", "eventSec": 700, "positions": [{"x": 50, "y": 50}],
     "tags": [{"id": 1701}]},
    {"eventName": "Pass", "subEventName": "High pass", "teamId": 675, "playerId": 13,
     "matchPeriod": "1H", "eventSec": 40, "positions": [{"x": 40, "y": 30}, {"x": 70, "y": 60}],
     "tags": [{"id": 901}, {"id": 1802}]},
]}


def _ws_load(payload, options=None):
    return provider_registry.create("wyscout").load(
        BytesIO(json.dumps(payload).encode()), "wyscout_deep.json", options=options)


def test_wyscout_tags_resolve_subtypes():
    f = _ws_load(WS_DEEP).frame
    # cross sub-event lifted to its own type; assist tag sets assist + key_pass
    assert f.loc[0, "event_type"] == "cross"
    assert bool(f.loc[0, "assist"]) and bool(f.loc[0, "key_pass"])
    assert f.loc[0, "body_part"] == "right foot" and f.loc[0, "outcome"] == "successful"
    # through-ball tag recorded, inaccurate tag -> unsuccessful
    assert "through ball" in f.loc[3, "notes"] and f.loc[3, "outcome"] == "unsuccessful"


def test_wyscout_shot_and_card_tags():
    f = _ws_load(WS_DEEP).frame
    assert f.loc[1, "shot_result"] == "Goal" and f.loc[1, "body_part"] == "head"
    # a foul carrying a red-card tag resolves the card
    assert f.loc[2, "sub_event"] == "red card" and "red card" in f.loc[2, "notes"]


def test_wyscout_name_resolution_with_lineup():
    lineup = {"teams": {"675": "Zamalek"},
              "players": {"10": "Shikabala", "11": "Zizo", "12": "Fatouh", "13": "Attia"}}
    ds = _ws_load(WS_DEEP, options={"lineup_data": lineup})
    f = ds.frame
    assert f.loc[0, "team"] == "Zamalek" and f.loc[0, "player"] == "Shikabala"
    assert ds.meta["name_resolution"] == "resolved"


def test_wyscout_name_resolution_from_embedded_roster():
    payload = dict(WS_DEEP,
                   teams=[{"wyId": 675, "name": "Zamalek"}],
                   players=[{"wyId": 10, "shortName": "Shikabala"}])
    ds = _ws_load(payload)                       # no options -> embedded roster used
    assert ds.frame.loc[0, "team"] == "Zamalek" and ds.frame.loc[0, "player"] == "Shikabala"
    assert ds.meta["name_resolution"] == "resolved"


def test_wyscout_falls_back_to_ids_without_lineup():
    ds = _ws_load(WS_DEEP)
    assert ds.frame.loc[0, "team"] == "675" and ds.frame.loc[0, "player"] == "10"
    assert ds.meta["name_resolution"] == "ids_only" and "10" in ds.meta["unresolved_players"]


def test_wyscout_backwards_compatible_and_robust():
    f = provider_registry.create("wyscout").load(
        BytesIO(json.dumps(WS_EVENTS).encode()), "wyscout_match.json").frame
    assert f.loc[0, "event_type"] == "Pass" and f.loc[0, "outcome"] == "successful"
    # a non-list payload raises a clean ProviderError, not a raw TypeError
    from fap.core.exceptions import ProviderError
    with pytest.raises(ProviderError):
        provider_registry.create("wyscout").load(BytesIO(b'{"events": 5}'), "w.json")
