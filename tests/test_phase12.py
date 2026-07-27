"""Phase 12 - Universal Data Hub (Import Center).

Verifies the Data Hub orchestrates the EXISTING engine end to end (import ->
validate -> clean -> map -> normalize -> quality -> save -> library) and adds
health, per-module compatibility, lineage, versioning, profiles and preview -
while reusing the ImportService + WorkspaceManager (no duplicated engine, storage
or repository) and leaving every other module intact.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from dataclasses import replace

import pytest

from fap.config.settings import AppSettings, CacheSettings, DatabaseSettings, StorageSettings
from fap.bootstrap import init_platform
from fap.datahub.preview import PreviewRequest
from fap.identity.models import User
from fap.identity.roles import Role

CSV = (b"event_type,x,y,team,player,minute,match_id,set_piece\n"
       b"pass,10,20,Home,Salah,1,M1,\n"
       b"shot,90,45,Home,Salah,2,M1,\n"
       b",40,10,Home,Mane,3,M1,\n"
       b"corner,99,50,Home,Trent,4,M1,corner\n"
       b"blorp,30,30,Away,X,5,M1,\n")


@pytest.fixture()
def hub_ctx(tmp_path):
    settings = replace(AppSettings(environment="development"),
                       user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"),
                       storage=StorageSettings(backend="local"))
    platform = init_platform(settings=settings)
    user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
    ws = platform.workspace_manager.ensure_workspace(user)
    try:
        yield platform, platform.datahub, user, ws
    finally:
        platform.db.close()


def _saved(hub, user, ws):
    result = hub.run_import(CSV, "match.csv")
    return hub.save_dataset(user, result, name="vs Rival", workspace_id=ws.id,
                            metadata={"competition": "EPL", "season": "25/26",
                                      "opponent": "Rival", "tags": ["scout"]})


def test_import_engine_is_reused(hub_ctx):
    _, hub, _, _ = hub_ctx
    prev = hub.inspect(CSV, "match.csv")
    assert prev.provider_id
    result = hub.run_import(CSV, "match.csv")
    assert len(result.frame) == 5
    assert 0 <= result.quality.overall <= 100
    assert hasattr(result.validation, "issues")


def test_save_creates_dataset_frame_lineage_version(hub_ctx):
    _, hub, user, ws = hub_ctx
    ds = _saved(hub, user, ws)
    assert ds.name == "vs Rival" and ds.document.get("quality") is not None
    assert hub.repo.frame(ds.id) is not None and len(hub.repo.frame(ds.id)) == 5
    assert any(d.id == ds.id for d in hub.list_datasets(workspace_id=ws.id))
    stages = [e["stage"] for e in hub.lineage(ds.id)]
    assert "imported" in stages and "saved" in stages
    assert any(v["version"] == 1 for v in hub.versions(ds.id))


def test_preview_highlights(hub_ctx):
    _, hub, user, ws = hub_ctx
    ds = _saved(hub, user, ws)
    pv = hub.preview(ds.id, PreviewRequest(page=1, page_size=25))
    assert pv.total == 5
    assert any(f.get("event_type") == "error" for f in pv.flags)      # empty event
    assert any(f.get("event_type") == "warning" for f in pv.flags)    # unknown event
    assert not any("end_x" in f for f in pv.flags)                    # optional -> no noise
    assert hub.preview(ds.id, PreviewRequest(search="Away")).total == 1


def test_health_and_compatibility(hub_ctx):
    _, hub, user, ws = hub_ctx
    ds = _saved(hub, user, ws)
    health = hub.health(ds.id)
    keys = {a.key for a in health.axes}
    assert {"coordinates", "players", "teams", "matches", "events",
            "setpiece", "penalty", "tracking", "gps"} <= keys
    compat = {c.module: c for c in hub.compatibility(ds.id)}
    assert compat["Open Play"].ready and compat["Players"].ready and compat["Reports"].ready
    assert compat["Set Pieces"].ready                                 # corner tagged
    assert not compat["Tracking"].ready and "tracking" in compat["Tracking"].reason.lower()


def test_versioning_restore(hub_ctx):
    _, hub, user, ws = hub_ctx
    ds = _saved(hub, user, ws)
    hub.update_metadata(user, ds.id, opponent="Rival FC")
    assert any(v["version"] == 2 for v in hub.versions(ds.id))
    hub.restore_version(user, ds.id, 1)
    assert hub.get(ds.id).opponent == "Rival"


def test_choose_sets_active_dataset_seam(hub_ctx):
    platform, hub, user, ws = hub_ctx
    ds = _saved(hub, user, ws)
    hub.choose(user, ds.id)
    wm = platform.workspace_manager
    assert wm.active_dataset_id(user) == ds.id
    assert wm.active_frame(user) is not None and len(wm.active_frame(user)) == 5


def test_profiles_include_builtins(hub_ctx):
    _, hub, user, _ = hub_ctx
    names = {p.name for p in hub.profiles.list(user)}
    assert {"StatsBomb", "Opta", "WyScout", "Manual"} <= names


def test_page_registers_and_others_intact():
    from fap.ui.page import load_builtin_pages, page_registry
    load_builtin_pages()
    ids = set(page_registry.ids())
    assert "data_hub" in ids
    assert {"dashboard", "opponent_analysis", "players", "scouting", "reports", "datasets"} <= ids
