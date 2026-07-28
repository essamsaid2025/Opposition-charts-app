"""Phase 13.1 - Player Visualization Workspace polish (additive, metadata-only).

Verifies the new catalog/search/grouping, the metadata CRUD (favorites, recent,
templates, filter presets) via the existing WorkspaceManager autosave tier, that
every built-in filter preset applies cleanly to a chart-ready frame, and the
render-scope frame selection. No engine, pipeline, dataframe or DB changes.
"""
import os
os.environ["FAP_TEST"] = "1"
import sys
import pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from fap.pipeline import schema
from fap.pipeline.filters import FilterSet
from fap.ui.components import viz_workspace as W
from fap.visuals.base import load_builtin_visuals, visual_registry

load_builtin_visuals()

_FRAME = W._prepare_frame(schema.coerce_schema(pd.DataFrame({
    "event_type": ["pass", "shot", "corner", "pass", "carry", "pass", "free_kick", "pass", "shot", "pass"],
    "x": [10, 90, 99, 70, 60, 20, 30, 80, 88, 44], "y": [20, 45, 50, 40, 50, 80, 30, 45, 50, 32],
    "team": ["Home"] * 10, "opponent": ["Away"] * 10, "player": ["Salah"] * 10,
    "minute": list(range(1, 11)), "match_id": ["M1"] * 10,
    "outcome": (["successful"] * 7 + ["unsuccessful"] * 3),
    "set_piece": ["", "", "corner", "", "", "", "free_kick", "", "", ""]})))


def test_prepared_frame_has_time_min():
    assert "time_min" in _FRAME.columns


def test_catalog_search_and_grouping():
    cat = W._catalog(visual_registry)
    assert all({"id", "name", "category", "description", "events"} <= set(v) for v in cat)
    assert len(W.search_catalog(cat, "")) == len(cat)
    assert all("pass" in (i["name"] + i["category"] + i["description"]).lower()
               for i in W.search_catalog(cat, "pass"))
    grp = W.group_catalog(cat)
    assert sum(len(v) for v in grp.values()) == len(cat) and len(grp) >= 3
    assert W._section_icon("Passing") == "arrow-right" and W._section_icon("zzz") == "grid"


def test_signature_backward_compatible_and_scope_sensitive():
    fr = pd.DataFrame({"x": [1]})
    assert isinstance(W._signature("a", {}, FilterSet(), "t", fr), str)          # 5-arg (Phase 13)
    assert W._signature("a", {}, FilterSet(), "t", fr, "whole") != \
        W._signature("a", {}, FilterSet(), "t", fr, "player")


def test_all_builtin_presets_and_templates_apply():
    for pr in W._BUILTIN_PRESETS + [{"filters": t.get("filters", {})} for t in W._BUILTIN_TEMPLATES]:
        assert isinstance(W._filterset_from_dict(pr["filters"]).apply(_FRAME), pd.DataFrame)
    open_play = W._filterset_from_dict(
        next(p["filters"] for p in W._BUILTIN_PRESETS if p["name"] == "Open Play")).apply(_FRAME)
    assert (open_play["set_piece"].astype(str).str.strip() == "").all() and len(open_play) == 8
    final = W._filterset_from_dict(
        next(p["filters"] for p in W._BUILTIN_PRESETS if p["name"] == "Final Third")).apply(_FRAME)
    assert (final["x"] >= 66.666).all()


@pytest.fixture()
def shell(tmp_path):
    from dataclasses import replace
    from fap.config.settings import AppSettings, CacheSettings, DatabaseSettings, StorageSettings
    from fap.bootstrap import init_platform
    from fap.identity.models import User
    from fap.identity.roles import Role
    settings = replace(AppSettings(environment="development"), user_data_dir=str(tmp_path / "ud"),
                       database=DatabaseSettings(path=str(tmp_path / "ud" / "fap.sqlite3")),
                       cache=CacheSettings(backend="memory"), storage=StorageSettings(backend="local"))
    platform = init_platform(settings=settings)
    user = User(email="a@club.com", name="Ana", role=Role.SUPER_ADMIN, provider_id="dev")
    try:
        yield SimpleNamespace(wm=platform.workspace_manager, user=user, _p=platform)
    finally:
        platform.db.close()


def test_favorites_metadata_extended_and_legacy(shell):
    shell.wm.autosave(shell.user, {"viz_ids": ["old"]}, scope="viz_favorites")
    assert W._favorites(shell)["viz"] == ["old"]                     # legacy migration
    W._toggle_favorite(shell, "theme", "opta_dark")
    W._toggle_favorite(shell, "viz", "hm")
    fav = W._favorites(shell)
    assert "hm" in fav["viz"] and "opta_dark" in fav["theme"]
    W._toggle_favorite(shell, "viz", "hm")
    assert "hm" not in W._favorites(shell)["viz"]


def test_recent_and_templates_and_presets(shell):
    for v in ["a", "b", "c"]:
        W._push_recent(shell, v)
    assert W._recent(shell)[:3] == ["c", "b", "a"]
    for v in range(12):
        W._push_recent(shell, f"r{v}")
    assert len(W._recent(shell)) == 8                                 # capped

    assert len(W._all_templates(shell)) >= 8
    items = W._user_templates(shell)
    items.append({"id": "tpl_x", "name": "Mine", "theme": "opta_dark", "scope": "player",
                  "viz_id": "", "controls": {}, "filters": {}})
    W._save_user_templates(shell, items)
    assert any(t["name"] == "Mine" for t in W._all_templates(shell))
    W._save_user_templates(shell, [t for t in W._user_templates(shell) if t["id"] != "tpl_x"])
    assert not any(t["name"] == "Mine" for t in W._all_templates(shell))
    assert len(W._all_presets(shell)) >= 7


def test_render_scope_selects_frame_without_new_dataset(shell):
    ds = shell.wm.register_dataset(shell.user, name="whole", workspace_id=None)
    shell.wm.set_active_dataset(shell.user, ds.id, frame=_FRAME)
    player = _FRAME[_FRAME["player"] == "Salah"]
    assert W._scope_frame(shell, "player", player) is player
    whole = W._scope_frame(shell, "whole", player)
    assert whole is not None and len(whole) == len(_FRAME)
    assert W._needs_team_context({"name": "Passing Network", "category": "Possession"}) is True
