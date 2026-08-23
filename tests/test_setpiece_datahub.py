"""Set Piece is a first-class Data Hub consumer (mandatory architecture).

Proves the required flow with NO second import:
  Data Hub import -> classify/persist/activate -> Set Piece derives from the active
  frame -> corner/free-kick separation is correct -> survives re-resolution (rerun)
  -> a Tagging Studio set-piece CSV enters the SAME way.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import pytest

_AUDIT = pathlib.Path(__file__).resolve().parent.parent / "sample_data" / "audit"


def _settings(tmp_path):
    from dataclasses import replace
    from fap.config.settings import (AppSettings, CacheSettings, DatabaseSettings,
                                     StorageSettings)
    return replace(AppSettings(environment="development"),
                   user_data_dir=str(tmp_path / "ud"),
                   database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                   cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))


def _user():
    from fap.identity.models import User
    from fap.identity.roles import Role
    return User(email="analyst@club.com", name="A", role=Role.SUPER_ADMIN, provider_id="dev")


@pytest.fixture()
def platform(tmp_path):
    from fap.bootstrap import init_platform
    plat = init_platform(settings=_settings(tmp_path))
    yield plat
    try:
        plat.db.close()
    except Exception:
        pass


def _import_and_activate(platform, user, ws, data: bytes, name: str):
    """The ONE canonical ingestion path: Data Hub analyze -> save -> choose."""
    res = platform.datahub.analyze(data, name + ".csv")
    assert res.import_result is not None, "Data Hub did not ingest as an event dataset"
    ds = platform.datahub.save_dataset(user, res.import_result, name=name, workspace_id=ws.id)
    platform.datahub.choose(user, ds.id)
    return ds


def test_set_piece_dataset_flows_through_data_hub_only(platform):
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    data = (_AUDIT / "fap_visualization_audit_set_pieces.csv").read_bytes()

    # 1. Import via Data Hub (classified as an event dataset, persisted, activated)
    ds = _import_and_activate(platform, user, ws, data, "Set Pieces vs Rivals")
    assert platform.workspace_manager.active_dataset_id(user) == ds.id

    # 2. Set Piece resolves the SAME dataset — no second upload required
    sps = platform.setpieces.search(user, workspace_id=ws.id)
    types = {}
    for sp in sps:
        types.setdefault(sp.type, []).append(sp)
    assert len(types.get("corner", [])) == 3          # CRN001, CRN002, SPSHOT001(set_piece=corner)
    assert len(types.get("free_kick", [])) == 2       # FK001, FK002
    assert len(types.get("throw_in", [])) == 1
    assert len(types.get("penalty", [])) == 1

    # 3. NEGATIVE: a free kick is not a corner (no leakage)
    corner_takers = {sp.start_x for sp in types["corner"]}
    assert 65 not in corner_takers                    # FK001 origin x=65 must not be a corner

    # 4. Coordinates come from the canonical (Data Hub-normalized) frame
    crn = next(sp for sp in types["corner"] if sp.start_x == 100 and sp.start_y == 100)
    assert crn.start_x == 100 and crn.start_y == 100

    # 5. Persistence / rerun safety: re-resolving (new call, cache) still works
    again = platform.setpieces.search(user, workspace_id=ws.id)
    assert len([sp for sp in again if sp.type == "corner"]) == 3


def test_no_independent_import_needed_dashboard_populated(platform):
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    data = (_AUDIT / "fap_visualization_audit_set_pieces.csv").read_bytes()
    _import_and_activate(platform, user, ws, data, "SP")
    # the Set Piece dashboard sees the data purely from the active dataset
    assert platform.setpieces.has_active_dataset(user) is True
    assert platform.setpieces.dashboard(user)["total"] >= 6


def test_tagging_set_piece_csv_enters_through_data_hub(platform):
    """A Set Piece CSV produced by the Tagging Studio imports the SAME way and
    becomes available to Set Piece analysis — no Tagging->SetPiece special path."""
    from fap.tagging.export import session_to_csv
    from fap.tagging.models import TagEvent, TaggingSession
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    s = TaggingSession(match_id="Tagged corners")
    s.add_event(TagEvent(event_type="corner", coordinate_space="pitch",
                         x=100, y=100, x2=92, y2=48, team="Team A", outcome="Successful"))
    s.add_event(TagEvent(event_type="free_kick", coordinate_space="pitch",
                         x=65, y=15, x2=88, y2=50, team="Team A", outcome="Successful"))
    data = session_to_csv(s).encode("utf-8")

    _import_and_activate(platform, user, ws, data, "Tagged set pieces")
    sps = platform.setpieces.search(user, workspace_id=ws.id)
    kinds = {sp.type for sp in sps}
    assert "corner" in kinds and "free_kick" in kinds
    assert len([sp for sp in sps if sp.type == "corner"]) == 1
