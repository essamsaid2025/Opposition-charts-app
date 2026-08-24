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


def test_fc_masar_template_renders_all_tier_a_charts(platform):
    """The FC Masar single-game template: import via Data Hub → every delivery-level
    (Tier A) set-piece dataset is populated for both attacking and defending phases."""
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    data = (_AUDIT / "fc_masar_set_pieces.csv").read_bytes()
    _import_and_activate(platform, user, ws, data, "FC Masar Set Pieces")

    sps = platform.setpieces.search(user, workspace_id=ws.id)
    assert len(sps) == 50
    kinds = {}
    persp = {}
    for sp in sps:
        kinds[sp.type] = kinds.get(sp.type, 0) + 1
        persp[sp.perspective] = persp.get(sp.perspective, 0) + 1
    assert kinds == {"corner": 23, "free_kick": 13, "throw_in": 9, "penalty": 5}
    assert persp["own"] == 33 and persp["opposition"] == 17     # attacking AND defending

    # delivery-level detail survives ingestion (side/swing/box/first-contact)
    corner = next(sp for sp in sps if sp.type == "corner" and sp.side)
    assert corner.side in ("left", "right") and corner.delivery_type
    assert corner.players_in_box and corner.first_contact_team

    # every CSV-reachable (Tier A) dataset is non-empty
    for kind in ("delivery", "delivery_success", "delivery_trajectory", "occ_timeline",
                 "pen_outcome", "pen_shooter"):
        assert platform.setpieces.visual_dataset(user, kind, workspace_id=ws.id), kind


def test_real_world_setpiece_schema_classifies_and_filters_correctly(platform):
    """Regression for the reported bug: a real export where the type is in
    `set_piece` and a `Type` column means Attack/Defence. Free kicks / throw-ins
    must NOT collapse into 'corner', attack/defence must split, and the Inswing
    filter must return ONLY inswing (not outswing)."""
    from fap.setpieces import analysis as SPA
    from fap.setpieces.models import SetPieceFilter
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    raw = SPA.read_table((_AUDIT / "setpiece_schema_proxy_style.csv").read_bytes(), "px.csv")
    frame = SPA.to_event_frame(raw)                     # set-piece schema -> canonical
    _import_and_activate(platform, user, ws, frame.to_csv(index=False).encode(), "Proxy style")

    svc = platform.setpieces
    sps = svc.search(user, workspace_id=ws.id)
    types = {}
    for s in sps:
        types[s.type] = types.get(s.type, 0) + 1
    assert types == {"corner": 3, "free_kick": 2, "throw_in": 2, "penalty": 1}, types

    def n(**kw):
        return len(svc._filtered(user, SetPieceFilter(**kw), ws.id))
    # free kicks and throw-ins are present (were being lost as 'corner')
    assert n(type="free_kick") == 2 and n(type="throw_in") == 2
    # attack / defence split correct
    assert n(phase="defensive") == 2 and n(phase="offensive") == 6
    # THE reported bug: inswing filter returns only inswing
    assert n(delivery_type="inswing") == 3
    assert n(delivery_type="outswing") == 2
    assert n(type="corner", delivery_type="inswing") == 2   # PX1, PX3


def test_ported_delivery_charts_render_from_structure_columns(platform):
    """The charts ported from the standalone Set-Pieces app render from a rich export's
    delivery-structure columns (zones, first/second-ball wins, player counts, taker) —
    no manual position/contact tagging."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    from fap.core.types import RenderContext
    from fap.setpieces import analysis as SPA
    from fap.setpieces.models import SetPieceFilter
    from fap.themes import ThemeManager
    from fap.visuals import Renderer, visual_registry
    from fap.visuals.setpieces import load_setpiece_visuals

    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    raw = SPA.read_table((_AUDIT / "setpiece_schema_proxy_style.csv").read_bytes(), "px.csv")
    _import_and_activate(platform, user, ws, SPA.to_event_frame(raw).to_csv(index=False).encode(), "Px")
    load_setpiece_visuals()
    theme = ThemeManager("assets/themes").get("opta_light")

    rows = platform.setpieces.visual_dataset(user, "delivery_full", workspace_id=ws.id)
    assert rows and "first_contact_win" in rows[0] and "players_near_post" in rows[0]
    df = pd.DataFrame(rows)
    for vid in ("sp_delivery_zones", "sp_first_contact_win_zone", "sp_second_ball_map",
                "sp_target_zone_breakdown", "sp_taker_profile", "sp_defensive_structure"):
        assert vid in visual_registry, vid
        fig = Renderer().render(visual_registry.create(vid),
                                RenderContext(df=df, theme=theme, controls={}, meta={}))
        assert fig.axes and len(fig.axes[0].get_children()) > 0
        plt.close(fig)


def test_filter_options_come_from_the_active_dataset(platform):
    """Regression: the filter dropdowns must reflect the ACTIVE dataset (what the
    charts render), not a leftover persisted/demo store — otherwise selecting an
    option that isn't in the data makes filtering look broken."""
    from fap.setpieces import analysis as SPA
    user = _user()
    ws = platform.workspace_manager.ensure_workspace(user)
    raw = SPA.read_table((_AUDIT / "setpiece_schema_proxy_style.csv").read_bytes(), "px.csv")
    _import_and_activate(platform, user, ws, SPA.to_event_frame(raw).to_csv(index=False).encode(),
                         "Proxy style")
    opts = platform.setpieces.filter_options(user, workspace_id=ws.id)
    assert opts["team"] == ["Proxy FC"]                 # the active dataset's team, not a demo
    assert set(opts["type"]) == {"corner", "free_kick", "throw_in", "penalty"}
    assert set(opts["delivery_type"]) == {"inswing", "outswing"}
    assert "Demo FC" not in opts["team"]


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
