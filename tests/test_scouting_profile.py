"""P4.3 - Professional player-profile data model + premium dashboard.

Age is DERIVED from DOB (never stored as truth); preferred foot is a controlled
vocabulary; height/weight/positions/nationality/secondary-nationalities/contract/
photo/club-logo/external-links persist through the EXISTING Player + document +
ImageStorage (no migration, no second model). Edit preserves player_id /
operational_id / links. The dashboard aggregates real data only - never fabricates.
"""
import os
os.environ["FAP_TEST"] = "1"
import datetime
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pandas as pd
import pytest

from fap.scouting import identity, player_profile
from fap.scouting.models import Player


# ================================================================ pure model
def test_derived_age_from_dob():
    today = datetime.date(2026, 8, 15)
    assert player_profile.derived_age("2000-03-15", today=today) == 26
    assert player_profile.derived_age("2000-12-31", today=today) == 25   # birthday not reached
    assert player_profile.derived_age("2030-01-01", today=today) is None  # future
    assert player_profile.derived_age("not-a-date") is None
    assert player_profile.derived_age("") is None


def test_foot_controlled_vocab():
    assert player_profile.normalize_foot("R") == "right"
    assert player_profile.normalize_foot("Left") == "left"
    assert player_profile.normalize_foot("two footed") == "both"
    assert player_profile.normalize_foot("garbage") == "unknown"
    assert player_profile.normalize_foot("") == "unknown"


def test_validation_warnings_not_silent_fix():
    w = player_profile.validate_profile({"height_cm": 250, "weight_kg": 20,
                                         "dob": "2999-01-01", "preferred_foot": "middle",
                                         "contract_expires": "bad"})
    assert len(w) == 5                                    # all flagged, nothing corrected


def test_snapshot_of_legacy_player_is_graceful():
    p = Player(id="x", name="Old Timer")                 # no profile fields at all
    snap = player_profile.player_snapshot(p)
    assert snap["age"] is None and snap["height_cm"] is None
    assert snap["preferred_foot"] == "unknown" and snap["positions"] == []


# ================================================================ integration
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


_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def _malta_like():
    metrics = ["Non-penalty goals per 90", "npxG per 90", "Progressive passes per 90",
               "xA per 90", "Shot assists per 90", "Touches in box per 90",
               "Aerial duels won, %", "Duels won, %"]
    rows = []
    names = ["S. Mamadu bah"] + [f"Player {i}" for i in range(32)]
    for i, nm in enumerate(names):
        r = {"Player": nm, "Team": "Sliema Wanderers" if i == 0 else f"Club {i}",
             "Age": 24, "League": "Malta Premier League 25-26", "Position": "CF"}
        for j, m in enumerate(metrics):
            r[m] = ((i * 7 + j * 3) % 100) / 100.0
        rows.append(r)
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _activate(platform, user, ws):
    ar = platform.datahub.analyze(_malta_like(), "Malta CF.csv")
    ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name="Malta CF.csv",
                                                workspace_id=ws.id)
    platform.datahub.choose(user, ds.id)
    return ds


# ---- ids + full profile persistence (1..15) ----
def test_full_profile_creation_persists(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(
        user, "Mamadu Bah", workspace_id=ws.id, player_type="first_team",
        dob="2001-05-05", nationality="United States", secondary_nationalities=["Gambia"],
        height=186, weight=80, foot="R", position="CF", secondary_positions=["RAMF", "AMF"],
        shirt_number=9, club="Sliema Wanderers", league="Malta PL", contract_until="2027-06-30",
        agent="XI Group")
    reloaded = sc.get_player(p.id)
    snap = player_profile.player_snapshot(reloaded)
    assert snap["operational_id"] == "CLB-000001"
    assert snap["age"] == player_profile.derived_age("2001-05-05")
    assert snap["preferred_foot"] == "right"
    assert snap["height_cm"] == 186 and snap["weight_kg"] == 80
    assert snap["positions"] == ["CF", "RAMF", "AMF"]
    assert snap["secondary_nationalities"] == ["Gambia"]
    assert snap["contract_expires"] == "2027-06-30" and snap["shirt_number"] == 9


def test_pathway_ids(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    assert identity.operational_id_of(sc.create_player(user, "A", workspace_id=ws.id)) == "CLB-000001"
    assert identity.operational_id_of(sc.create_player(user, "B", workspace_id=ws.id, player_type="academy")) == "ACD-000001"
    assert identity.operational_id_of(sc.create_player(user, "C", workspace_id=ws.id, player_type="trialist")) == "TRI-000001"


def test_photo_and_club_logo_persist(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "P", workspace_id=ws.id)
    sc.add_image(user, p.id, _PNG, "image/png", kind="profile")
    sc.set_club_logo(user, p.id, _PNG, "image/png")
    reloaded = sc.get_player(p.id)
    assert reloaded.profile_image_id and reloaded.club_logo_id
    assert sc.image_bytes(reloaded.profile_image_id) == _PNG
    assert sc.image_bytes(reloaded.club_logo_id) == _PNG


# ---- edit preserves identity (16/17) ----
def test_edit_preserves_ids_and_links(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    _activate(platform, user, ws)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id, foot="right", height=180)
    op = identity.operational_id_of(p)
    sc.link_dataset_identity(user, p.id, "S. Mamadu bah", method="manual")
    sc.add_alias(user, p.id, "MB")
    sc.update_profile(user, p.id, height=188, weight=82, foot="left",
                      contract_until="2028-06-30", nationality="Gambia")
    reloaded = sc.get_player(p.id)
    assert reloaded.id == p.id
    assert identity.operational_id_of(reloaded) == op
    assert identity.aliases_of(reloaded) == ["MB"]
    assert sc.dataset_link_status(user, p.id)["linked"] is True
    snap = player_profile.player_snapshot(reloaded)
    assert snap["height_cm"] == 188 and snap["preferred_foot"] == "left"


# ---- dataset matching intact + honest states (18/19/20) ----
def test_dataset_matching_and_metrics_state(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    _activate(platform, user, ws)
    linked = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id, club="Sliema Wanderers")
    unlinked = sc.create_player(user, "Totally Absent", workspace_id=ws.id)
    d1 = sc.player_dashboard(user, linked.id)
    d2 = sc.player_dashboard(user, unlinked.id)
    assert d1["dataset"]["linked"] is True and d1["dataset"]["metrics_available"] is True
    assert d1["strengths"]                                   # real percentile highlights
    assert d2["dataset"]["player_exists"] is True and d2["dataset"]["linked"] is False
    assert d2["dataset"]["metrics_available"] is False and d2["strengths"] == []


# ---- search (21/22/23) ----
def test_search_by_opid_position_nationality(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id, position="CF",
                         nationality="United States")
    op = identity.operational_id_of(p)
    assert [r["name"] for r in sc.player_registry(user, filters={"query": op}, workspace_id=ws.id)] == ["Mamadu Bah"]
    assert [r["name"] for r in sc.player_registry(user, filters={"position": "CF"}, workspace_id=ws.id)] == ["Mamadu Bah"]
    assert [r["name"] for r in sc.player_registry(user, filters={"nationality": "United States"}, workspace_id=ws.id)] == ["Mamadu Bah"]


# ---- pathway fields + old players render (24/25) ----
def test_academy_fields_and_legacy_dashboard(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    ac = sc.create_player(user, "Young", workspace_id=ws.id, player_type="academy", age_group="U17")
    sc.set_academy_profile(user, ac.id, stage="foundation", technical_potential=80)
    dash = sc.player_dashboard(user, ac.id)
    assert dash["academy"]["stage"] == "foundation" and dash["academy"]["technical_potential"] == 80
    legacy = Player(id="leg", name="Legacy", owner=user.email, workspace_id=ws.id)
    sc.players.save(legacy)
    d = sc.player_dashboard(user, "leg")                     # renders with no fields, no error
    assert d["snapshot"]["age"] is None and d["snapshot"]["operational_id"] == ""


# ---- audit still generated (26) ----
def test_audit_events_generated(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "P", workspace_id=ws.id)
    sc.update_profile(user, p.id, height=190)
    sc.add_link(user, p.id, "https://x.com", title="X")
    rows = platform.db.query("SELECT action FROM audit_log WHERE target_id = ?", (p.id,))
    actions = {r["action"] for r in rows}
    assert "scouting.player.create" in actions
    assert any(a.startswith("scouting.player") for a in actions)
    assert "scouting.player.link_add" in actions


# ---- external links + no second store (external links in document) ----
def test_external_links_crud(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "P", workspace_id=ws.id)
    l1 = sc.add_link(user, p.id, "https://transfermarkt.com/x", title="TM", category="profile")
    sc.add_link(user, p.id, "https://fbref.com/x", title="FBref")
    assert {l["title"] for l in sc.list_links(p.id)} == {"TM", "FBref"}
    sc.delete_link(user, p.id, l1["id"])
    assert {l["title"] for l in sc.list_links(p.id)} == {"FBref"}


# ---- event capability unchanged (28/29) ----
def test_event_capability_unchanged(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    _activate(platform, user, ws)
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    assert sc.player_event_frame(user, p.id) is None         # player-scouting -> no event lookup
    ev = ("event_type,x,y,team,player,minute,match_id\n"
          "pass,10,20,Home,Mamadu Bah,1,M1\nshot,90,45,Home,Mamadu Bah,2,M1\n").encode()
    er = platform.datahub.analyze(ev, "match.csv")
    eds = platform.datahub.save_dataset(user, er.import_result, name="ev",
                                        workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, eds.id)
    frame = sc.player_event_frame(user, p.id)
    assert frame is not None and len(frame) == 2
