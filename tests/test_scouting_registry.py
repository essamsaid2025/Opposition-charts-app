"""P4.2 - Player registry, pathways (Academy/First-Team), operational IDs,
promotion, recruitment profiles + fit, search, status/pathway history.

ONE canonical identity (immutable player_id), TWO pathways. Operational ids
(CLB-/ACD-/TRI-) are stable, never reused after deletion, and never the identity.
Promotion keeps the same player_id and all history. Profile fit is transparent and
only from metrics that exist. Everything is additive over the existing
ScoutingService/PlayerRepository/WorkspaceManager - no new tables.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pandas as pd
import pytest

from fap.scouting import identity, profiles, viz


# ---------------------------------------------------------------- fixtures
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


def _scouting_csv():
    metrics = ["Non-penalty goals per 90", "npxG per 90", "Progressive passes per 90",
               "Progressive runs per 90", "xA per 90", "Shot assists per 90",
               "Successful dribbles, %", "Touches in box per 90", "Duels won, %",
               "Aerial duels won, %", "PAdj Interceptions", "Passes per 90"]
    rows = []
    names = ["S. Mamadu bah"] + [f"Player {i}" for i in range(32)]
    for i, nm in enumerate(names):
        r = {"Player": nm, "Team": f"Club {i % 6}", "Age": 20 + i % 15,
             "League": "Malta Premier League 25-26", "Position": "CF"}
        for j, m in enumerate(metrics):
            r[m] = ((i * 7 + j * 3) % 100) / 100.0
        rows.append(r)
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _activate_scouting(platform, user, ws):
    ar = platform.datahub.analyze(_scouting_csv(), "board.csv")
    ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name="Malta CF",
                                                workspace_id=ws.id)
    platform.datahub.choose(user, ds.id)
    return ds


# ================================================================ 1/2/3 ID generation
def test_first_team_and_academy_id_generation(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    a = sc.create_player(user, "A", workspace_id=ws.id)                 # first_team default
    b = sc.create_player(user, "B", workspace_id=ws.id)
    c = sc.create_player(user, "C", workspace_id=ws.id, player_type="academy")
    d = sc.create_player(user, "D", workspace_id=ws.id, player_type="academy")
    assert identity.operational_id_of(a) == "CLB-000001"
    assert identity.operational_id_of(b) == "CLB-000002"
    assert identity.operational_id_of(c) == "ACD-000001"
    assert identity.operational_id_of(d) == "ACD-000002"


def test_operational_ids_unique_and_internal_ids_unique(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    players = [sc.create_player(user, f"P{i}", workspace_id=ws.id) for i in range(5)]
    ops = [identity.operational_id_of(p) for p in players]
    assert len(set(ops)) == 5
    assert len({p.id for p in players}) == 5


def test_ids_not_reused_after_deletion(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    a = sc.create_player(user, "A", workspace_id=ws.id)     # CLB-000001
    b = sc.create_player(user, "B", workspace_id=ws.id)     # CLB-000002
    sc.delete_player(user, b.id)                            # remove the max
    c = sc.create_player(user, "C", workspace_id=ws.id)     # must be CLB-000003, not reuse 000002
    assert identity.operational_id_of(c) == "CLB-000003"


# ================================================================ 4/5 immutable id + type persist
def test_internal_id_immutable_and_type_persists(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id, player_type="academy")
    pid = p.id
    sc.set_recruitment_status(user, pid, "shortlisted")
    sc.set_player_type(user, pid, "trialist", reassign_operational_id=True)
    reloaded = sc.get_player(pid)
    assert reloaded.id == pid                                # id never changes
    assert identity.player_type_of(reloaded) == "trialist"


# ================================================================ 6/7 promotion preserves everything
def test_promotion_preserves_player_id_and_history(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Youngster", workspace_id=ws.id, player_type="academy")
    pid = p.id
    old_op = identity.operational_id_of(p)
    sc.add_note(user, pid, "great potential")
    promoted = sc.promote_to_first_team(user, pid, note="ready")
    assert promoted.id == pid                                # SAME identity
    assert identity.player_type_of(promoted) == "first_team"
    new_op = identity.operational_id_of(promoted)
    assert new_op.startswith("CLB-") and new_op != old_op
    # history recorded + prior assets intact
    ph = sc.pathway_history(pid)
    assert ph and ph[-1]["from"] == "academy" and ph[-1]["to"] == "first_team"
    assert ph[-1]["operational_id_before"] == old_op
    assert len(sc.list_notes(pid)) == 1                      # note survived promotion


# ================================================================ 8/9/10 identity resolution
def test_alias_and_ambiguous_resolution(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "Mamadou Bah")
    assert sc.resolve_player(user, name="mamadou bah", workspace_id=ws.id).player.id == p.id
    sc.create_player(user, "John Smith", workspace_id=ws.id)
    sc.create_player(user, "John Smith", workspace_id=ws.id)
    r = sc.resolve_player(user, name="John Smith", workspace_id=ws.id)
    assert not r.found and r.ambiguous


# ================================================================ 11 search
def test_player_search_by_type_and_status(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    ft = sc.create_player(user, "FT One", workspace_id=ws.id, position="CF")
    sc.set_recruitment_status(user, ft.id, "target")
    sc.create_player(user, "Ac One", workspace_id=ws.id, player_type="academy")
    ft_rows = sc.player_registry(user, filters={"player_type": "first_team"}, workspace_id=ws.id)
    assert {r["name"] for r in ft_rows} == {"FT One"}
    ac_rows = sc.player_registry(user, filters={"player_type": "academy"}, workspace_id=ws.id)
    assert {r["name"] for r in ac_rows} == {"Ac One"}
    target_rows = sc.player_registry(user, filters={"status": "target"}, workspace_id=ws.id)
    assert {r["name"] for r in target_rows} == {"FT One"}


# ================================================================ 12/13 profile assignment + filter
def test_recruitment_profile_assignment_and_filter(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id, position="CF")
    sc.set_recruitment_profile(user, p.id, "false_9")
    assert identity.recruitment_profile_of(sc.get_player(p.id)) == "false_9"
    rows = sc.player_registry(user, filters={"recruitment_profile": "false_9"}, workspace_id=ws.id)
    assert {r["name"] for r in rows} == {"S. Mamadu bah"}


# ================================================================ 14/15 fit (and no fabrication)
def test_profile_fit_when_data_supports(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    _activate_scouting(platform, user, ws)
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id)
    fit = sc.profile_fit_for(user, p.id, "false_9")
    assert fit["available"] and isinstance(fit["score"], (int, float))
    assert fit["mode"] == "normalized" and len(fit["matched"]) >= 3


def test_fit_not_fabricated_when_metrics_missing(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    # a scouting dataset with only ONE non-goalkeeping metric -> GK profile can't fit
    frame = pd.DataFrame({"Player": ["S. Mamadu bah", "X"], "Team": ["A", "B"],
                          "Passes per 90": [0.4, 0.3]})
    ar = platform.datahub.analyze(frame.to_csv(index=False).encode(), "thin.csv")
    ds = platform.datahub.save_scouting_dataset(user, ar.scouting, name="thin", workspace_id=ws.id)
    platform.datahub.choose(user, ds.id)
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id)
    fit = sc.profile_fit_for(user, p.id, "sweeper_keeper")
    assert fit["available"] is False and fit["score"] is None and fit["reason"]


def test_fit_none_when_player_absent_from_dataset(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    _activate_scouting(platform, user, ws)
    p = sc.create_player(user, "Nobody In Data", workspace_id=ws.id)
    assert sc.profile_fit_for(user, p.id, "false_9") is None


# ================================================================ 16/17 academy vs first-team fields
def test_academy_specific_fields(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Young", workspace_id=ws.id, player_type="academy")
    sc.set_age_group(user, p.id, "U17")
    sc.set_academy_profile(user, p.id, stage="developing", technical_potential=80,
                           projection="", physical_potential=None)
    ac = identity.academy_profile_of(sc.get_player(p.id))
    assert identity.age_group_of(sc.get_player(p.id)) == "U17"
    assert ac["stage"] == "developing" and ac["technical_potential"] == 80
    assert "projection" not in ac and "physical_potential" not in ac   # empties dropped, not fabricated


# ================================================================ 18/19/20/21 media + links (reuse)
def test_photo_logo_media_and_links_persist(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "P", workspace_id=ws.id)
    m = sc.add_image(user, p.id, b"\x89PNG\r\n", "image/png", kind="profile")
    assert sc.get_player(p.id).profile_image_id == m.image_id       # photo persisted (ImageStorage)
    assert sc.image_bytes(m.image_id) == b"\x89PNG\r\n"
    v = sc.add_external_video(user, p.id, "https://youtube.com/watch?v=x", title="Highlights")
    assert v.player_id == p.id and v.provider == "youtube"
    a = sc.add_attachment(user, p.id, b"data", "report.pdf", "application/pdf")
    assert a.player_id == p.id and len(sc.list_attachments(p.id)) == 1


# ================================================================ 22/23/24 status/priority + history
def test_status_history_and_priority(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "P", workspace_id=ws.id)
    sc.set_recruitment_status(user, p.id, "shortlisted")
    sc.set_recruitment_status(user, p.id, "shortlisted")            # unchanged -> no dup history
    sc.set_recruitment_status(user, p.id, "target", note="strong")
    sc.set_priority(user, p.id, "urgent")                          # legacy -> critical
    hist = sc.status_history(p.id)
    assert [(h["from"], h["to"]) for h in hist] == [("watching", "shortlisted"),
                                                    ("shortlisted", "target")]
    assert hist[-1]["note"] == "strong"
    assert sc.get_player(p.id).priority == "critical"


# ================================================================ 25/26 dataset-independent + integration
def test_identity_dataset_independent(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id)
    pid = p.id
    _activate_scouting(platform, user, ws)                          # dataset also contains that name
    assert sc.resolve_player(user, player_id=pid).player.id == pid  # id resolves regardless
    ctx2 = sc.active_scouting_dataset(user)
    assert ctx2 is not None and len(ctx2["players"]) == 33          # dataset discovered by metadata


# ================================================================ 27/28/29 event evidence + alias
def test_event_evidence_alias_and_capability(ctx):
    platform, user, ws = ctx
    sc = platform.scouting
    p = sc.create_player(user, "S. Mamadu bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "Mamadou Bah")
    # player-scouting active -> NO event lookup
    _activate_scouting(platform, user, ws)
    assert sc.player_event_frame(user, p.id) is None
    # event dataset active -> alias-matched events resolve
    ev = ("event_type,x,y,team,player,minute,match_id\n"
          "pass,10,20,Home,Mamadou Bah,1,M1\n"
          "shot,90,45,Home,Mamadou Bah,2,M1\n").encode()
    er = platform.datahub.analyze(ev, "match.csv")
    eds = platform.datahub.save_dataset(user, er.import_result, name="ev",
                                        workspace_id=ws.id, metadata={})
    platform.datahub.choose(user, eds.id)
    frame = sc.player_event_frame(user, p.id)
    assert frame is not None and len(frame) == 2


# ================================================================ pure profile engine
def test_profiles_are_position_aware_and_data_bound():
    assert profiles.get_profile("false_9").name == "False 9"
    cf = {p.id for p in profiles.profiles_for_position("CF, RAMF, AMF")}
    assert "false_9" in cf and "target_man" in cf
    gk = {p.id for p in profiles.profiles_for_position("GK")}
    assert "sweeper_keeper" in gk


def test_profile_fit_deterministic_and_normalized_not_double_scaled():
    # a normalized dataset -> fit uses value*100, never re-ranked
    frame = pd.DataFrame({"Player": ["S. Mamadu bah", "Y", "Z"], "Team": ["A", "B", "C"],
                          "Progressive passes per 90": [0.8, 0.2, 0.5],
                          "xA per 90": [0.9, 0.1, 0.4], "Shot assists per 90": [0.7, 0.3, 0.6],
                          "Key passes per 90": [0.6, 0.2, 0.5]})
    schema = {"id_field": "Player", "value_scale": "normalized",
              "dimensions": {"player": "Player", "team": "Team"},
              "metrics": [{"source": c, "name": c, "unit": "per_90"}
                          for c in frame.columns if c not in ("Player", "Team")]}
    v = viz.build_view(frame, schema, ["S. Mamadu bah"])
    a = profiles.profile_fit(v, profiles.get_profile("false_9"))
    b = profiles.profile_fit(v, profiles.get_profile("false_9"))
    assert a == b and a["available"] and a["mode"] == "normalized"
