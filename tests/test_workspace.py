"""Workspace & Data Management layer (Phase 3B).

Backend is pure (no Streamlit): the hierarchy, data manager, presets, version
history, auto-save, permissions, audit and search are all tested from the
service facade against a real (temp) database - the same platform database,
migrated, never a second one.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from fap.core.exceptions import AuthError
from fap.db.engine import Database
from fap.db.models import Project
from fap.db.repositories import ProjectRepository, WorkspaceRepository
from fap.identity.models import User
from fap.identity.roles import Role
from fap.workspaces import Capability, WorkspaceManager, can, require
from fap.workspaces.service import WorkspaceService
from fap.core.events import EventBus


def _user(role: Role, email="u@club.com") -> User:
    return User(email=email, name=email.split("@")[0], role=role, provider_id="dev")


ADMIN = _user(Role.SUPER_ADMIN, "admin@club.com")
CLUB_ADMIN = _user(Role.CLUB_ADMIN, "clubadmin@club.com")
ANALYST = _user(Role.PERFORMANCE_ANALYST, "analyst@club.com")
READER = _user(Role.READ_ONLY, "reader@club.com")


@pytest.fixture()
def wm(tmp_path) -> WorkspaceManager:
    return WorkspaceManager(Database(tmp_path / "w.sqlite3"))


@pytest.fixture()
def db(tmp_path) -> Database:
    return Database(tmp_path / "d.sqlite3")


# ---------------------------------------------------------------- migration / db reuse
def test_migration_adds_tables_without_a_second_database(db):
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"org_nodes", "datasets", "presets", "project_versions", "audit_log",
            "user_state", "user_items"} <= tables
    # original tables still present (same database)
    assert {"projects", "workspaces", "mapping_templates"} <= tables


def test_project_columns_added_are_backward_compatible(db):
    cols = {r["name"] for r in db.query("PRAGMA table_info(projects)")}
    assert {"owner_id", "status", "tags", "contributors"} <= cols


# ---------------------------------------------------------------- hierarchy
def test_club_hierarchy_builds_and_lists(wm):
    club = wm.create_club(ADMIN, "Example FC")
    season = wm.add_child(ADMIN, club.id, "season", "2025/26")
    comp = wm.add_child(ADMIN, season.id, "competition", "Premier League")
    team = wm.add_child(ADMIN, comp.id, "team", "First Team")
    opp = wm.add_child(ADMIN, team.id, "opponent", "Rival FC")
    assert [n.name for n in wm.children(club.id)] == ["2025/26"]
    assert [n.name for n in wm.children(team.id)] == ["Rival FC"]
    assert opp.kind == "opponent"


def test_delete_club_cascades_to_descendants(wm):
    club = wm.create_club(ADMIN, "FC")
    season = wm.add_child(ADMIN, club.id, "season", "S")
    wm.delete_node(ADMIN, club.id)
    assert wm.children(club.id) == [] and wm._org.get(season.id) is None


def test_move_node_reparents(wm):
    club = wm.create_club(ADMIN, "FC")
    s1 = wm.add_child(ADMIN, club.id, "season", "S1")
    s2 = wm.add_child(ADMIN, club.id, "season", "S2")
    comp = wm.add_child(ADMIN, s1.id, "competition", "C")
    wm.move_node(ADMIN, comp.id, s2.id)
    assert [n.name for n in wm.children(s2.id)] == ["C"]
    assert wm.children(s1.id) == []


# ---------------------------------------------------------------- data manager (CRUD)
def test_dataset_crud_and_metadata(wm):
    ds = wm.register_dataset(ANALYST, name="vs Rival", provider_id="statsbomb", rows=900,
                             season="2025/26", competition="PL", opponent="Rival",
                             match_date="2026-01-10", document={"players": ["A"]})
    assert wm.get_dataset(ds.id).rows == 900
    wm.rename_dataset(ANALYST, ds.id, "vs Rival (H)")
    assert wm.get_dataset(ds.id).name == "vs Rival (H)"
    dup = wm.duplicate_dataset(ANALYST, ds.id)
    assert dup.id != ds.id and dup.name.endswith("(copy)") and dup.opponent == "Rival"
    exported = wm.export_dataset(ANALYST, ds.id)
    assert exported["provider"] == "statsbomb" and exported["players"] == ["A"]


def test_dataset_archive_hides_from_active_list(wm):
    ds = wm.register_dataset(ANALYST, name="d")
    wm.archive_dataset(ANALYST, ds.id)
    assert wm.list_datasets() == []
    assert len(wm.list_datasets(include_archived=True)) == 1
    wm.archive_dataset(ANALYST, ds.id, archived=False)
    assert len(wm.list_datasets()) == 1


def test_dataset_move_and_delete(wm):
    ds = wm.register_dataset(ANALYST, name="d")
    wm.move_dataset(ANALYST, ds.id, workspace_id="ws1", node_id="n1")
    moved = wm.get_dataset(ds.id)
    assert moved.workspace_id == "ws1" and moved.node_id == "n1"
    wm.delete_dataset(ANALYST, ds.id)
    assert wm.get_dataset(ds.id) is None


# ---------------------------------------------------------------- presets / templates
def test_preset_crud_all_kinds(wm):
    for kind in ("chart", "filter", "export", "dashboard"):
        wm.save_preset(ANALYST, kind=kind, name=f"{kind} preset", document={"k": kind})
    assert {p.kind for p in wm.list_presets(ANALYST)} == {"chart", "filter", "export", "dashboard"}
    charts = wm.list_presets(ANALYST, kind="chart")
    assert len(charts) == 1 and charts[0].document == {"k": "chart"}
    wm.delete_preset(ANALYST, charts[0].id)
    assert wm.list_presets(ANALYST, kind="chart") == []


def test_club_scope_presets_visible_to_other_users(wm):
    wm.save_preset(CLUB_ADMIN, kind="dashboard", name="Club layout",
                   document={}, scope="club")
    # another user sees club-scoped presets even though they do not own them
    assert any(p.name == "Club layout" for p in wm.list_presets(ANALYST))


# ---------------------------------------------------------------- version history
def test_version_snapshot_restore_and_compare(wm, tmp_path):
    WorkspaceService(WorkspaceRepository(wm._db), EventBus()).create("WS")  # FK parent
    ws_id = WorkspaceRepository(wm._db).list_all()[0].id
    projects = ProjectRepository(wm._db)
    projects.save(Project(id="p1", workspace_id=ws_id, name="P",
                          document={"visual_id": "pass_map", "filters": {"team": "A"}}))
    v1 = wm.snapshot_project(ANALYST, "p1", note="baseline")
    # change the project, snapshot again
    proj = projects.get("p1"); proj.document["visual_id"] = "shot_map"; projects.save(proj)
    v2 = wm.snapshot_project(ANALYST, "p1")
    assert [v.version for v in wm.list_versions("p1")] == [2, 1]

    diff = wm.compare_versions("p1", v1.version, v2.version)
    assert "visual_id" in diff.changed

    wm.restore_version(ANALYST, "p1", v1.version)
    assert projects.get("p1").document["visual_id"] == "pass_map"
    # restore is itself reversible: it snapshotted current state first
    assert len(wm.list_versions("p1")) == 3


# ---------------------------------------------------------------- auto-save
def test_autosave_roundtrip_per_user(wm):
    state = {"filters": {"team": "A"}, "provider": "statsbomb", "visual_id": "pass_map",
             "theme": "Dark", "page": "Analysis", "last_project": "p1"}
    wm.autosave(ANALYST, state)
    assert wm.load_autosave(ANALYST) == state
    # another user has their own state
    assert wm.load_autosave(READER) == {}


def test_pins_favorites_recents(wm):
    wm.pin(ANALYST, "project", "p1")
    wm.favorite(ANALYST, "dataset", "d1")
    wm.touch_recent(ANALYST, "project", "p1")
    wm.touch_recent(ANALYST, "project", "p2")
    assert ("project", "p1") in wm.pinned(ANALYST)
    assert ("dataset", "d1") in wm.favorites(ANALYST)
    assert wm.recents(ANALYST)[0] == ("project", "p2")   # most recent first
    wm.unpin(ANALYST, "project", "p1")
    assert wm.pinned(ANALYST) == []


# ---------------------------------------------------------------- permissions
def test_permission_matrix():
    assert can(Role.SUPER_ADMIN, Capability.DELETE_WORKSPACE)
    assert not can(Role.CLUB_ADMIN, Capability.DELETE_WORKSPACE)
    assert can(Role.CLUB_ADMIN, Capability.MANAGE_CLUB)
    assert not can(Role.PERFORMANCE_ANALYST, Capability.MANAGE_CLUB)
    assert can(Role.PERFORMANCE_ANALYST, Capability.EDIT)
    assert not can(Role.READ_ONLY, Capability.EDIT)
    assert can(Role.READ_ONLY, Capability.VIEW)


def test_read_only_cannot_modify(wm):
    with pytest.raises(AuthError):
        wm.register_dataset(READER, name="x")
    with pytest.raises(AuthError):
        wm.create_club(READER, "FC")
    with pytest.raises(AuthError):
        wm.save_preset(READER, kind="chart", name="x", document={})


def test_only_super_admin_deletes_a_club(wm):
    club = wm.create_club(ADMIN, "FC")
    with pytest.raises(AuthError):
        wm.delete_node(CLUB_ADMIN, club.id)          # club admin cannot delete a whole club
    wm.delete_node(ADMIN, club.id)                    # super admin can
    assert wm._org.get(club.id) is None


def test_club_admin_manages_branches_but_analyst_cannot(wm):
    club = wm.create_club(ADMIN, "FC")
    season = wm.add_child(CLUB_ADMIN, club.id, "season", "S")   # club admin OK
    with pytest.raises(AuthError):
        wm.add_child(ANALYST, club.id, "season", "S2")          # analyst cannot manage hierarchy


# ---------------------------------------------------------------- audit
def test_audit_records_every_important_action(wm):
    club = wm.create_club(ADMIN, "FC")
    ds = wm.register_dataset(ANALYST, name="d")
    wm.delete_dataset(ANALYST, ds.id)
    actions = [e.action for e in wm.audit_trail()]
    assert {"org.create", "dataset.import", "dataset.delete"} <= set(actions)
    entry = wm.audit_trail(action="dataset.import")[0]
    assert entry.actor == "analyst@club.com" and entry.actor_role == "performance_analyst"


def test_audit_is_filterable_by_actor(wm):
    wm.create_club(ADMIN, "FC")
    wm.register_dataset(ANALYST, name="d")
    assert all(e.actor == "admin@club.com" for e in wm.audit_trail(actor="admin@club.com"))


# ---------------------------------------------------------------- search
def test_global_search_across_entities(wm):
    club = wm.create_club(ADMIN, "Example FC")
    wm.add_child(ADMIN, club.id, "opponent", "Rival United")
    wm.register_dataset(ANALYST, name="Match vs Rival", opponent="Rival United",
                        document={"players": ["Zidane"]})
    wm.save_preset(ANALYST, kind="chart", name="Rival press map", document={})
    types = {h.type for h in wm.search("rival")}
    assert "dataset" in types and "opponent" in types and "preset:chart" in types
    assert any(h.type == "dataset" for h in wm.search("zidane"))   # player search
    assert wm.search("   ") == []                                   # blank query


# ---------------------------------------------------------------- backward compatibility
def test_existing_workspace_service_still_works(db):
    svc = WorkspaceService(WorkspaceRepository(db), EventBus())
    ws = svc.create("Legacy WS")
    assert svc.get(ws.id).name == "Legacy WS"


def test_old_project_without_new_columns_still_loads(db):
    # simulate a project saved before Phase 3B (no owner/status/tags set explicitly)
    ws = WorkspaceService(WorkspaceRepository(db), EventBus()).create("WS")
    repo = ProjectRepository(db)
    repo.save(Project(id="old", workspace_id=ws.id, name="Old Project",
                      document={"visual_id": "pass_map"}))
    loaded = repo.get("old")
    assert loaded is not None and loaded.name == "Old Project"
    row = db.query("SELECT status, tags FROM projects WHERE id='old'")[0]
    assert row["status"] == "active" and row["tags"] == "[]"    # defaults applied


# ------------------------------------------------ active dataset (one source of truth)
def _cached_wm(tmp_path) -> WorkspaceManager:
    from fap.cache import CacheManager
    from fap.config.settings import CacheSettings
    return WorkspaceManager(Database(tmp_path / "a.sqlite3"),
                            cache=CacheManager(CacheSettings(backend="memory")))


def test_workspace_manager_owns_the_active_dataset(tmp_path):
    import pandas as pd
    wm = _cached_wm(tmp_path)
    frame = pd.DataFrame({"event_type": ["pass"], "x": [10.0], "y": [20.0]})
    ds = wm.register_dataset(ANALYST, name="vs Rival", provider_id="generic_csv", rows=1)

    assert wm.active_dataset(ANALYST) is None          # nothing active yet
    wm.set_active_dataset(ANALYST, ds.id, frame=frame)

    assert wm.active_dataset_id(ANALYST) == ds.id
    assert wm.active_dataset(ANALYST).name == "vs Rival"
    pd.testing.assert_frame_equal(wm.active_frame(ANALYST), frame)


def test_every_screen_consumes_the_same_active_frame(tmp_path):
    """Opponent Analysis activates; Reports/Scouting/Match read the SAME object."""
    import pandas as pd
    wm = _cached_wm(tmp_path)
    frame = pd.DataFrame({"event_type": ["pass", "shot"], "x": [1.0, 2.0], "y": [3.0, 4.0]})
    ds = wm.register_dataset(ANALYST, name="d", rows=2)
    wm.set_active_dataset(ANALYST, ds.id, frame=frame)      # Opponent Analysis

    reports_df = wm.active_frame(ANALYST)                   # Reports
    scouting_df = wm.active_frame(ANALYST)                  # Scouting
    match_df = wm.active_frame(ANALYST)                     # Match Analysis
    for other in (scouting_df, match_df):
        pd.testing.assert_frame_equal(reports_df, other)
    assert len(reports_df) == 2


def test_active_dataset_is_per_user_and_clearable(tmp_path):
    import pandas as pd
    wm = _cached_wm(tmp_path)
    ds = wm.register_dataset(ANALYST, name="d")
    wm.set_active_dataset(ANALYST, ds.id, frame=pd.DataFrame({"x": [1]}))
    assert wm.active_dataset_id(READER) is None             # other users unaffected
    wm.clear_active_dataset(ANALYST)
    assert wm.active_dataset_id(ANALYST) is None


def test_active_frame_none_without_cache_but_pointer_survives(tmp_path):
    """No cache injected -> pointer still works, frame simply unavailable."""
    wm = WorkspaceManager(Database(tmp_path / "n.sqlite3"))   # no cache
    ds = wm.register_dataset(ANALYST, name="d")
    wm.set_active_dataset(ANALYST, ds.id)
    assert wm.active_dataset_id(ANALYST) == ds.id
    assert wm.active_frame(ANALYST) is None


# ------------------------------------------------ persistent dataset storage
def _persistent_wm(tmp_path, cache=None):
    """WorkspaceManager with real persistent storage (+ optional cache)."""
    from fap.storage import ParquetDatasetStorage
    return WorkspaceManager(Database(tmp_path / "p.sqlite3"), cache=cache,
                            storage=ParquetDatasetStorage(tmp_path / "datasets"))


def _frame():
    import pandas as pd
    return pd.DataFrame({
        "event_type": ["pass", "shot"], "x": [10.0, 90.0], "y": [20.0, 50.0],
        "is_forward": [True, False],
        "start_third": pd.Categorical(["Defensive Third", "Final Third"]),
    })


def test_dataset_frame_survives_cache_expiry(tmp_path):
    """The cache is only an accelerator - clearing it must not lose data."""
    import pandas as pd
    from fap.cache import CacheManager
    from fap.config.settings import CacheSettings
    cache = CacheManager(CacheSettings(backend="memory"))
    wm = _persistent_wm(tmp_path, cache=cache)
    ds = wm.register_dataset(ANALYST, name="d", rows=2)
    wm.set_active_dataset(ANALYST, ds.id, frame=_frame())

    cache.clear()                                    # simulate TTL expiry
    frame = wm.active_frame(ANALYST)                 # must still resolve
    assert frame is not None
    pd.testing.assert_frame_equal(frame, _frame())
    # and the cache was re-warmed transparently
    assert cache.get(wm._frame_key(ds.id)) is not None


def test_dataset_frame_survives_restart(tmp_path):
    """A brand-new manager (new process/deploy) re-opens the stored frame."""
    import pandas as pd
    wm = _persistent_wm(tmp_path)
    ds = wm.register_dataset(ANALYST, name="d", rows=2)
    wm.set_active_dataset(ANALYST, ds.id, frame=_frame())

    reborn = _persistent_wm(tmp_path)                # fresh objects, same disk
    pd.testing.assert_frame_equal(reborn.active_frame(ANALYST), _frame())


def test_storage_is_dtype_exact_no_import_rerun(tmp_path):
    import pandas as pd
    from fap.storage import ParquetDatasetStorage
    store = ParquetDatasetStorage(tmp_path / "s")
    original = _frame()
    store.save("abc", original)
    loaded = store.load("abc")
    pd.testing.assert_frame_equal(loaded, original)          # dtypes preserved
    assert str(loaded["start_third"].dtype) == "category"
    assert store.exists("abc") and store.size_bytes("abc") > 0


def test_storage_load_missing_returns_none(tmp_path):
    from fap.storage import ParquetDatasetStorage
    store = ParquetDatasetStorage(tmp_path / "s")
    assert store.load("never-saved") is None and not store.exists("never-saved")


def test_deleting_dataset_removes_stored_frame(tmp_path):
    wm = _persistent_wm(tmp_path)
    ds = wm.register_dataset(ANALYST, name="d")
    wm.set_active_dataset(ANALYST, ds.id, frame=_frame())
    assert wm._storage.exists(ds.id)
    wm.delete_dataset(ANALYST, ds.id)
    assert not wm._storage.exists(ds.id)


def test_consumers_call_active_frame_unchanged(tmp_path):
    """Reports/Scouting/Match/SetPiece/Dashboard use the same one-arg call."""
    import inspect
    sig = inspect.signature(WorkspaceManager.active_frame)
    assert list(sig.parameters) == ["self", "user"]
    wm = _persistent_wm(tmp_path)
    ds = wm.register_dataset(ANALYST, name="d")
    wm.set_active_dataset(ANALYST, ds.id, frame=_frame())
    assert len(wm.active_frame(ANALYST)) == 2


def test_storage_optional_backward_compatible(tmp_path):
    """WorkspaceManager(db) with no cache and no storage still works."""
    wm = WorkspaceManager(Database(tmp_path / "b.sqlite3"))
    ds = wm.register_dataset(ANALYST, name="d")
    wm.set_active_dataset(ANALYST, ds.id, frame=_frame())     # nowhere to put it
    assert wm.active_dataset_id(ANALYST) == ds.id             # pointer still works
    assert wm.active_frame(ANALYST) is None
