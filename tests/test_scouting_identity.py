"""P4.1 - Player identity + recruitment vocabulary.

The scouting module is now PLAYER-centric: the persistent player_id is the
identity anchor, a dataset row only a source resolved back by name/alias. These
tests pin identity persistence (aliases/display_name/source in the existing
document JSON - no migration), the single dataset-independent resolver (id first,
then exact name/alias, ambiguity surfaced), and the canonical recruitment
status/priority vocabulary with back-compatible normalization.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pytest

from fap.scouting import identity
from fap.scouting.models import Player


# ---------------------------------------------------------------- pure vocab
def test_status_normalization_back_compat():
    assert identity.normalize_status("prospect") == "watching"
    assert identity.normalize_status("recommended") == "target"
    assert identity.normalize_status("Shortlisted") == "shortlisted"
    assert identity.normalize_status("signed") == "signed"
    # unknown value is not fabricated into a different meaning - passes through
    assert identity.normalize_status("loan-target") == "loan-target"


def test_priority_normalization():
    assert identity.normalize_priority("urgent") == "critical"
    assert identity.normalize_priority("High") == "high"
    assert identity.normalize_priority("") == ""


def test_status_pipeline_and_terminals():
    assert identity.RECRUITMENT_STATUSES[-2:] == ("rejected", "archived")
    assert "signed" in identity.STATUS_PIPELINE
    assert identity.is_terminal("rejected") and not identity.is_terminal("target")
    nxt = identity.next_statuses("shortlisted")
    assert "scouted" in nxt and "shortlisted" not in nxt and "rejected" in nxt


# ---------------------------------------------------------------- pure identity helpers
def _player(name, *, pid="p1", aliases=None, display=None, source=None):
    doc = {}
    if aliases is not None:
        doc["aliases"] = aliases
    if display is not None:
        doc["display_name"] = display
    if source is not None:
        doc["source"] = source
    return Player(id=pid, name=name, document=doc)


def test_identity_keys_include_name_aliases_display():
    p = _player("S. Mamadu bah", aliases=["Mamadou Bah", "Bah"], display="S. Bah")
    keys = identity.identity_keys(p)
    assert "s. mamadu bah" in keys and "mamadou bah" in keys and "s. bah" in keys


def test_resolve_by_id_wins():
    a = _player("A", pid="1"); b = _player("B", pid="2")
    r = identity.resolve([a, b], player_id="2")
    assert r.found and r.player.id == "2" and not r.ambiguous


def test_resolve_by_alias():
    p = _player("S. Mamadu bah", pid="1", aliases=["Mamadou Bah"])
    r = identity.resolve([p], name="mamadou bah")
    assert r.found and r.player.id == "1"


def test_resolve_ambiguous_is_surfaced_not_guessed():
    a = _player("John Smith", pid="1"); b = _player("John Smith", pid="2")
    r = identity.resolve([a, b], name="John Smith")
    assert not r.found and r.ambiguous and len(r.candidates) == 2


def test_resolve_no_match():
    r = identity.resolve([_player("A", pid="1")], name="Nobody")
    assert not r.found and not r.ambiguous and r.candidates == []


# ---------------------------------------------------------------- integration (persistence)
@pytest.fixture()
def ctx(tmp_path):
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


def test_identity_fields_persist_in_document(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "Mamadou Bah")
    sc.set_display_name(user, p.id, "S. Bah")
    sc.set_source(user, p.id, "Malta league export")
    # reload from the DB - identity attributes survive with no schema migration
    reloaded = sc.get_player(p.id)
    assert identity.aliases_of(reloaded) == ["Mamadou Bah"]
    assert identity.display_name_of(reloaded) == "S. Bah"
    assert identity.source_of(reloaded) == "Malta league export"


def test_alias_add_remove_and_set(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Player One", workspace_id=ws.id)
    sc.add_alias(user, p.id, "P. One")
    sc.add_alias(user, p.id, "P. One")                 # duplicate ignored
    sc.add_alias(user, p.id, "Player One")             # equal to name -> ignored
    assert identity.aliases_of(sc.get_player(p.id)) == ["P. One"]
    sc.set_aliases(user, p.id, ["Uno", "One"])
    assert identity.aliases_of(sc.get_player(p.id)) == ["Uno", "One"]
    sc.remove_alias(user, p.id, "Uno")
    assert identity.aliases_of(sc.get_player(p.id)) == ["One"]


def test_resolve_player_service_by_id_and_alias(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "Mamadou Bah")
    assert sc.resolve_player(user, player_id=p.id).player.id == p.id
    r = sc.resolve_player(user, name="mamadou bah", workspace_id=ws.id)
    assert r.found and r.player.id == p.id


def test_player_id_is_the_anchor_independent_of_dataset(ctx):
    """The persistent player_id resolves the same player regardless of which
    dataset is active - the dataset row is never the identity."""
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id)
    pid = p.id
    # activate a player-scouting dataset that also contains that name
    frame_csv = ("Player,Team,Goals per 90,xG per 90,Passes per 90\n"
                 "S. Mamadu bah,Sliema,0.4,0.3,30\n"
                 "Other Guy,Valletta,0.1,0.2,25\n").encode()
    ar = platform.datahub.analyze(frame_csv, "board.csv")
    ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name="Board",
                                                workspace_id=ws.id)
    platform.datahub.choose(user, ds.id)
    # the player record is still resolved by its persistent id, unchanged
    assert sc.resolve_player(user, player_id=pid).player.id == pid
    assert sc.get_player(pid).name == "S. Mamadu bah"


def test_ambiguous_identity_via_service(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    sc.create_player(user, "John Smith", workspace_id=ws.id)
    sc.create_player(user, "John Smith", workspace_id=ws.id)
    r = sc.resolve_player(user, name="John Smith", workspace_id=ws.id)
    assert not r.found and r.ambiguous and len(r.candidates) == 2
    assert len(sc.find_players_by_name(user, "John Smith", workspace_id=ws.id)) == 2


def test_recruitment_status_and_priority_persist_normalized(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "X", workspace_id=ws.id)
    sc.set_recruitment_status(user, p.id, "Shortlisted")
    sc.set_priority(user, p.id, "urgent")              # legacy -> critical
    reloaded = sc.get_player(p.id)
    assert reloaded.status == "shortlisted"
    assert reloaded.priority == "critical"


def test_event_join_uses_identity_keys(ctx):
    """The event lookup resolves the player by the same identity keys (name+alias),
    so an aliased name in an event dataset still joins."""
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "Mamadou Bah")
    ev = ("event_type,x,y,team,player,minute,match_id\n"
          "pass,10,20,Home,Mamadou Bah,1,M1\n"
          "shot,90,45,Home,Mamadou Bah,2,M1\n").encode()
    er = platform.datahub.analyze(ev, "match.csv")
    eds = platform.datahub.save_dataset(user, er.import_result, name="ev",
                                        workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, eds.id)
    frame = sc.player_event_frame(user, p.id)          # matched via alias
    assert frame is not None and len(frame) == 2
