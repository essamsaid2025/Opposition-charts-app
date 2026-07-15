"""Provider Intelligence (Phase 2B.3).

The mission: recognize the provider from the file's *content*, so a StatsBomb
export called events.json is still a StatsBomb export. The hard part is not
recognizing vendors - it is not stealing files that belong to someone else, so
roughly half of these tests assert what must NOT be detected.
"""
import json
import time

import pandas as pd
import pytest

from fap.cache import CacheManager
from fap.config.settings import CacheSettings
from fap.db.engine import Database
from fap.pipeline.importer import ImportService
from fap.pipeline.templates import TemplateRepository
from fap.providers.base import provider_registry
from fap.providers.custom import (
    CustomProviderRepository, temporary_custom_provider,
)
from fap.providers.intelligence import ProviderIntelligence
from fap.providers.sampling import sample_file
from fap.providers.signature import ProviderSignature


@pytest.fixture()
def engine() -> ProviderIntelligence:
    return ProviderIntelligence()


@pytest.fixture()
def importer(tmp_path) -> ImportService:
    db = Database(tmp_path / "i.sqlite3")
    return ImportService(CacheManager(CacheSettings(backend="memory")),
                         TemplateRepository(db),
                         custom_providers=CustomProviderRepository(db))


# ---------------------------------------------------------------- fixtures
SB = json.dumps([{
    "type": {"name": "Pass"}, "possession_team": {"name": "Barca"},
    "play_pattern": {"name": "Regular Play"}, "location": [60.0, 40.0],
    "minute": 3, "second": 1, "period": 1, "under_pressure": True,
    "pass": {"end_location": [90.0, 20.0], "statsbomb_xg": 0.1},
}] * 5).encode()

WY = json.dumps({"events": [{
    "eventName": "Pass", "teamId": 1, "playerId": 9, "matchPeriod": "1H",
    "eventSec": 12.0, "positions": [{"x": 40, "y": 30}, {"x": 60, "y": 50}],
    "tags": [{"id": 1801}]}] * 5}).encode()

OPTA = (b'<Games><Game id="g1"><Event id="1" type_id="1" period_id="1" min="4" sec="1" '
        b'team_id="t" player_id="p" outcome="1" x="40" y="50">'
        b'<Q qualifier_id="140" value="70"/></Event></Game></Games>')

SPORTSCODE = (b'<file><ALL_INSTANCES><instance><ID>1</ID><start>10</start><end>18</end>'
              b'<code>Pass</code></instance></ALL_INSTANCES></file>')

METRICA = (b"Team,Type,Subtype,Period,Start Frame,Start Time [s],End Frame,From,To,"
           b"Start X,Start Y,End X,End Y\nHome,PASS,,1,1,3.0,5,P1,P2,0.4,0.3,0.7,0.5\n")

SKILLCORNER = json.dumps({"data": [{"trackable_object": 12, "frame": 1,
                                    "x": 10.0, "y": 5.0}]}).encode()
SECOND_SPECTRUM = (b'{"gameEventId": "e1", "wallClock": 1600000, "event_type": "pass", '
                   b'"x": -20.0, "y": 5.0}')
CATAPULT = (b"Player Name,Player Load,Odometer,Velocity\nAda,3.2,120.5,7.1\n"
            b"Bo,4.1,130.0,7.9\n")
GPSPORTS = b"Athlete,Speed (m/s),Distance (m),Heart Rate\nAda,7.2,900,180\n"
INSTAT = b"Action,Half,Second,Player,Team,Pos x,Pos y\npass,1,10,Ada,Lions,40,50\n"
STATS_PERFORM = json.dumps({"matchInfo": {"id": "m1"},
                            "liveData": {"event": [{"contestantId": "c1", "typeId": 1,
                                                    "periodId": 1, "x": 40, "y": 50}]}}).encode()

GENERIC_CSV = b"Action,start_x,origin_y,target_x,end_y,Player Name,Team Name,min\npass,10,20,30,40,Ada,Lions,3\n"
GENERIC_JSON = json.dumps([{"event_type": "pass", "x": 10, "y": 20, "player": "Ada"}] * 3).encode()


def _best(engine, data, filename):
    report = engine.detect(data, filename)
    return report.best.provider_id if report.best and not report.best.generic else None


# ---------------------------------------------------------------- vendor recognition by name
@pytest.mark.parametrize("filename,data,expected", [
    ("statsbomb_events.json", SB, "statsbomb"),
    ("wyscout_match.json", WY, "wyscout"),
    ("opta_f24.xml", OPTA, "opta_f24"),
    ("hudl_export.csv", b"Row,Timeline,Instance,Code\n1,0,1,Pass\n", "hudl"),
    ("sportscode_timeline.xml", SPORTSCODE, "sportscode"),
    ("metrica_events.csv", METRICA, "metrica"),
    ("skillcorner_tracking.json", SKILLCORNER, "skillcorner_events"),
    ("second_spectrum_events.jsonl", SECOND_SPECTRUM, "second_spectrum_events"),
    ("tracab_export.csv", b"event_type,x,y\npass,-1000,500\n", "tracab_events"),
    ("catapult_session.csv", CATAPULT, "catapult"),
    ("gpsports_session.csv", GPSPORTS, "gpsports"),
    ("instat_match.csv", INSTAT, "instat"),
    ("statsperform_ma3.json", STATS_PERFORM, "stats_perform"),
])
def test_provider_recognized_by_name_and_content(engine, filename, data, expected):
    assert _best(engine, data, filename) == expected


# ---------------------------------------------------------------- the mission: content only
@pytest.mark.parametrize("data,expected", [
    (SB, "statsbomb"),
    (WY, "wyscout"),
    (CATAPULT, "catapult"),
    (STATS_PERFORM, "stats_perform"),
])
def test_provider_recognized_with_a_neutral_filename(engine, data, expected):
    """The whole point: the filename says nothing, the content says everything."""
    suffix = ".json" if data.lstrip()[:1] in (b"{", b"[") else ".csv"
    assert _best(engine, data, f"export_2024{suffix}") == expected


def test_opta_recognized_without_opta_in_the_name(engine):
    assert _best(engine, OPTA, "match_events.xml") == "opta_f24"


def test_skillcorner_recognized_by_fingerprint(engine):
    assert _best(engine, SKILLCORNER, "tracking.json") == "skillcorner_events"


# ---------------------------------------------------------------- generic must stay generic
def test_generic_json_is_not_stolen_by_a_vendor(engine):
    assert _best(engine, GENERIC_JSON, "events.json") is None      # -> legacy fallback


def test_generic_csv_is_not_stolen_by_a_vendor(engine):
    assert _best(engine, GENERIC_CSV, "match.csv") is None


def test_a_plain_events_key_is_not_enough_to_be_wyscout(engine):
    """A nested event array is how half the world exports JSON."""
    data = json.dumps({"events": [{"event_type": "pass", "x": 1, "y": 2}]}).encode()
    assert _best(engine, data, "feed.json") is None


def test_a_player_name_column_is_not_enough_to_be_catapult(engine):
    data = b"Player Name,event_type,x,y\nAda,pass,10,20\n"
    assert _best(engine, data, "squad.csv") is None


def test_unknown_schema_is_reported_for_an_unrecognized_file(engine):
    report = engine.detect(GENERIC_CSV, "match.csv")
    assert report.unknown_schema is True
    assert report.best is not None and report.best.generic      # generic candidate offered


# ---------------------------------------------------------------- scoring / evidence
def test_evidence_is_reported_for_a_match(engine):
    report = engine.detect(SB, "statsbomb_events.json")
    rules = {e.rule for e in report.best.matched_rules}
    assert "filename" in rules and "fingerprint" in rules
    assert report.best.score > 0
    assert "StatsBomb" in report.reasoning


def test_more_evidence_means_more_confidence(engine):
    named = engine.detect(SB, "statsbomb_events.json").best
    unnamed = engine.detect(SB, "export.json").best
    assert named.confidence > unnamed.confidence      # the filename is worth something
    assert named.provider_id == unnamed.provider_id == "statsbomb"


def test_confidence_ordering_puts_the_best_explanation_first(engine):
    report = engine.detect(SB, "statsbomb_events.json")
    scores = [m.score for m in report.candidates]
    assert scores == sorted(scores, reverse=True)
    assert report.candidates[0].provider_id == "statsbomb"


def test_missing_required_columns_penalize(engine):
    """Catapult's name is on the file but its schema is not."""
    report = engine.detect(b"event_type,x,y\npass,1,2\n", "catapult_export.csv")
    catapult = next(m for m in report.candidates + tuple()
                    if m.provider_id == "catapult") if any(
        m.provider_id == "catapult" for m in report.candidates) else None
    # it may be rejected outright; if it survives, it must be penalized
    if catapult is not None:
        assert any(e.rule == "required_columns" for e in catapult.failed_rules)
    else:
        assert _best(engine, b"event_type,x,y\npass,1,2\n", "catapult_export.csv") != "catapult"


def test_extension_is_a_gate_not_a_score(engine):
    """A provider that cannot physically read the bytes is never a candidate."""
    report = engine.detect(SB, "statsbomb_events.csv")     # json content, csv extension
    assert all(m.provider_id != "statsbomb" for m in report.candidates)


def test_a_filename_alone_never_beats_content_evidence(engine):
    """Mixed signature: the name says Hudl, the content is unmistakably StatsBomb."""
    report = engine.detect(SB, "hudl_export.json")
    assert report.best.provider_id == "statsbomb"


def test_ambiguity_is_reported(engine):
    report = engine.detect(SB, "statsbomb_events.json")
    assert report.ambiguous is False          # one clear winner
    assert report.confident is True


# ---------------------------------------------------------------- sampling / performance
def test_sampling_reads_only_the_head_of_a_large_file():
    """A million-row file must cost about what a small one costs."""
    header = b"event_type,x,y,player,team\n"
    row = b"pass,10,20,Ada,Lions\n"
    big = header + row * 1_000_000
    assert len(big) > 20_000_000
    start = time.perf_counter()
    sample = sample_file(big, "huge.csv")
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"sampling a 1M-row file took {elapsed:.2f}s"
    assert sample.columns == ("event_type", "x", "y", "player", "team")
    assert len(sample.text_head) <= 64_000          # never the whole file


def test_detection_of_a_large_file_is_fast(engine):
    big = b"event_type,x,y\n" + b"pass,10,20\n" * 500_000
    start = time.perf_counter()
    engine.detect(big, "huge.csv")
    assert time.perf_counter() - start < 1.0


def test_huge_json_is_sampled_not_parsed():
    record = '{"event_type": "pass", "x": 1, "y": 2}'
    big = ("[" + ",".join([record] * 200_000) + "]").encode()
    assert len(big) > 4_000_000
    start = time.perf_counter()
    sample = sample_file(big, "huge.json")
    assert time.perf_counter() - start < 1.5
    assert "event_type" in sample.columns
    assert any("sampled first" in n for n in sample.notes)


# ---------------------------------------------------------------- custom providers
def test_temporary_custom_provider_is_offered_for_an_unknown_export():
    sample = sample_file(b"club_action,club_x,club_y\npass,10,20\n", "club.csv")
    spec = temporary_custom_provider(sample)
    assert spec is not None
    assert spec.base_provider_id == "generic_csv"
    assert spec.signature.required_columns == ("club_action", "club_x", "club_y")
    assert not spec.saved                       # nothing persisted yet


def test_saved_custom_provider_is_recognized_next_time(tmp_path):
    data = b"club_action,club_x,club_y\npass,10,20\n"
    repo = CustomProviderRepository(Database(tmp_path / "c.sqlite3"))
    plain = ProviderIntelligence()
    assert _best(plain, data, "club.csv") is None            # unknown today

    spec = temporary_custom_provider(sample_file(data, "club.csv"))
    saved = repo.save(spec, "My Club")
    assert saved.saved and saved.name == "My Club"

    taught = ProviderIntelligence(extra_signatures=repo.signatures())
    report = taught.detect(data, "another_export.csv")       # different name, same shape
    assert report.best is not None
    assert report.best.provider_id == spec.id
    assert report.best.provider_name == "My Club"


def test_custom_provider_round_trips_through_the_database(tmp_path):
    repo = CustomProviderRepository(Database(tmp_path / "c.sqlite3"))
    spec = temporary_custom_provider(sample_file(b"a,b,c\n1,2,3\n", "x.csv"))
    repo.save(spec, "Training Export")
    stored = repo.get(spec.id)
    assert stored.name == "Training Export"
    assert stored.signature.required_columns == ("a", "b", "c")
    assert [s.name for s in repo.list_all()] == ["Training Export"]
    repo.delete(spec.id)
    assert repo.get(spec.id) is None


def test_import_through_a_saved_custom_provider(importer):
    data = b"club_action,club_x,club_y\npass,10,20\nshot,80,50\n"
    spec = temporary_custom_provider(sample_file(data, "club.csv"))
    importer._customs.save(spec, "My Club")
    result = importer.import_file(data, "unnamed_export.csv",
                                  mapping={"club_action": "event_type",
                                           "club_x": "x", "club_y": "y"})
    assert result.provider_id == spec.id           # recognized as the club's own export
    assert len(result.frame) == 2


# ---------------------------------------------------------------- import integration
def test_import_reports_the_detection_in_the_summary(importer):
    result = importer.import_file(SB, "events.json")
    assert result.provider_id == "statsbomb"       # content, not filename
    assert result.summary["provider_confidence"] > 0.5
    assert result.summary["matched_rules"]
    assert result.summary["provider_version"] == "statsbomb-v4"
    assert "StatsBomb" in result.summary["provider_reasoning"]
    assert result.detection is not None


def test_import_summary_carries_the_full_story(importer):
    result = importer.import_file(GENERIC_CSV, "match.csv")
    s = result.summary
    for key in ("provider", "provider_name", "provider_confidence", "provider_version",
                "provider_reasoning", "matched_rules", "failed_rules", "generated_fields",
                "missing_required", "unknown_fields", "warnings", "event_schema",
                "template_used", "rows"):
        assert key in s, key
    assert s["provider"] == "generic_csv"          # unchanged fallback behaviour
    assert s["unknown_schema"] is True


def test_explicit_provider_choice_still_wins(importer):
    result = importer.import_file(b"event_type,x,y\npass,10,20\n", "anything.csv",
                                  provider_id="manual")
    assert result.provider_id == "manual"
    assert result.detection is None                # no detection was needed


# ---------------------------------------------------------------- plugin architecture
def test_adding_a_provider_needs_no_engine_change():
    """One class + one registration. The engine must never name a provider.

    Checked against the parsed module rather than its text, so the prose in the
    docstring cannot pass or fail the test.
    """
    import ast
    import inspect
    from fap.providers import intelligence

    tree = ast.parse(inspect.getsource(intelligence))
    docstrings = {ast.get_docstring(n) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))}
    literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    literals -= docstrings

    ids = set(provider_registry.ids())
    assert not (literals & ids), f"engine hard-codes provider ids: {literals & ids}"
    # nor may it import any concrete provider
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any("builtin" in m for m in imported), "engine imports a concrete provider"


def test_every_builtin_provider_declares_a_signature():
    missing = [cls.info.id for cls in provider_registry
               if not isinstance(getattr(cls, "signature", None), ProviderSignature)]
    assert missing == []


def test_generic_providers_are_marked_generic():
    generics = {cls.info.id for cls in provider_registry
                if getattr(cls, "signature", None) and cls.signature.generic}
    assert generics == {"generic_csv", "generic_excel", "generic_json"}
