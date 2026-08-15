"""P4.5 - a linked video's action list is DATASET-INDEPENDENT.

Once a video is linked to (dataset_id, match_id), its events come from that
persisted dataset via WorkspaceManager.dataset_frame - NEVER the active dataset.
Switching the active dataset (even to a non-event player-scouting dataset) must not
change or empty the action list. Legacy videos (no dataset_id) require explicit
linking - never a silent active-dataset fallback. Reuses P4.4 event_rows +
event_video_time; no second event/seek system.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pytest

from fap.ui.builtin import video_sync as VS


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
        yield platform, user, ws, tmp_path
    finally:
        try:
            platform.db.close()
        except Exception:
            pass


def _event_csv(match, n):
    rows = "event_type,x,y,team,player,minute,second,match_id\n"
    for i in range(n):
        rows += f"pass,{10 + i},20,Home,S. Mamadu bah,{i},{(i * 3) % 60},{match}\n"
    return rows.encode()


def _import_event(platform, user, ws, match, n, name):
    er = platform.datahub.analyze(_event_csv(match, n), name + ".csv")
    return platform.datahub.save_dataset(user, er.import_result, name=name, workspace_id=ws.id,
                                         metadata={})


def _n(sc, user, p, v):
    ev = sc.video_events(user, p.id, sc.videos_repo.get(v.id))
    return None if ev is None else int(len(ev))


def test_mandatory_video_dataset_switch(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    d1 = _import_event(platform, user, ws, "M1", 3, "Malta CF MD7")     # E1,E2,E3
    d3 = _import_event(platform, user, ws, "M3", 5, "Other event ds")
    ps = platform.datahub.save_scouting_dataset(
        user, platform.datahub.analyze(b"Player,Team,Goals per 90\nS. Mamadu bah,S,0.4\nX,Y,0.2\n",
                                        "ps.csv").scouting, name="metrics", workspace_id=ws.id)
    v = sc.add_external_video(user, p.id, "https://youtu.be/abc123XYZ00")
    platform.datahub.choose(user, d1.id)
    sc.link_video_to_match(user, v.id, d1.id, "M1")
    sc.set_video_sync(user, v.id, "M1", 200.0)                          # kickoff at 200s

    # 1. active D1 -> V1 shows E1/E2/E3
    assert _n(sc, user, p, v) == 3
    # 2. click E1 -> 200 + 0*60 + 0 = 200
    ev = sc.video_events(user, p.id, sc.videos_repo.get(v.id)).reset_index(drop=True)
    assert VS.event_video_time(200.0, ev.iloc[0]["minute"], ev.iloc[0]["second"]) == 200.0
    # 3-5. switch active to D2 (player_scouting, no events) -> STILL 3
    platform.datahub.choose(user, ps.id)
    assert _n(sc, user, p, v) == 3
    assert VS.event_video_time(200.0, ev.iloc[1]["minute"], ev.iloc[1]["second"]) == 263.0
    # 6-7. switch to unrelated event dataset D3 -> STILL 3
    platform.datahub.choose(user, d3.id)
    assert _n(sc, user, p, v) == 3
    # 8-9. back to D1 -> STILL 3
    platform.datahub.choose(user, d1.id)
    assert _n(sc, user, p, v) == 3


def test_persists_across_reload(ctx):
    platform, user, ws, tmp_path = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    d1 = _import_event(platform, user, ws, "M1", 3, "D1")
    v = sc.add_external_video(user, p.id, "https://youtu.be/abc123XYZ00")
    platform.datahub.choose(user, d1.id)
    sc.link_video_to_match(user, v.id, d1.id, "M1")
    platform.db.close()
    # reopen the SAME database
    from fap.config.settings import (
        AppSettings, CacheSettings, DatabaseSettings, StorageSettings)
    from fap.bootstrap import init_platform
    from fap.identity.models import User
    from fap.identity.roles import Role
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))
    p2 = init_platform(settings=settings)
    try:
        u2 = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
        v2 = p2.scouting.videos_repo.get(v.id)
        assert v2.dataset_id == d1.id and v2.match_id == "M1"          # persisted
        ev = p2.scouting.video_events(u2, p.id, v2)
        assert ev is not None and len(ev) == 3
    finally:
        p2.db.close()


def test_legacy_video_without_dataset_id_requires_explicit_link(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    _import_event(platform, user, ws, "M1", 3, "D1")
    v = sc.add_external_video(user, p.id, "https://youtu.be/legacy00000")
    sc.videos_repo.set_sync(v.id, "M1", 100.0)                          # old style: no dataset_id
    # NO silent active-dataset fallback -> None (UI shows "Dataset not linked")
    assert sc.video_events(user, p.id, sc.videos_repo.get(v.id)) is None


def test_two_videos_keep_their_own_datasets(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    d1 = _import_event(platform, user, ws, "M1", 3, "D1")
    d2 = _import_event(platform, user, ws, "M2", 7, "D2")
    v1 = sc.add_external_video(user, p.id, "https://youtu.be/aaaaaaaaaaa")
    v2 = sc.add_external_video(user, p.id, "https://youtu.be/bbbbbbbbbbb")
    sc.link_video_to_match(user, v1.id, d1.id, "M1")
    sc.link_video_to_match(user, v2.id, d2.id, "M2")
    for active in (d1.id, d2.id):
        platform.datahub.choose(user, active)
        assert _n(sc, user, p, v1) == 3            # V1 always D1/M1
        assert _n(sc, user, p, v2) == 7            # V2 always D2/M2


def test_link_registers_p44_evidence_and_unlink_clears(ctx):
    platform, user, ws, _ = ctx
    sc = platform.scouting
    p = sc.create_player(user, "Mamadu Bah", workspace_id=ws.id)
    sc.add_alias(user, p.id, "S. Mamadu bah")
    d1 = _import_event(platform, user, ws, "M1", 3, "D1")
    v = sc.add_external_video(user, p.id, "https://youtu.be/abc123XYZ00")
    sc.link_video_to_match(user, v.id, d1.id, "M1")
    # reuse P4.4: the evidence registry now also knows M1
    assert any(m["match_id"] == "M1" for m in sc.player_matches(user, p.id))
    # clearing the match unlinks the dataset binding too
    sc.set_video_sync(user, v.id, "", None)
    assert sc.videos_repo.get(v.id).dataset_id == ""
    assert sc.video_events(user, p.id, sc.videos_repo.get(v.id)) is None
