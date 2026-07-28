"""Player Visualization Workspace (Phase 13) - a SHARED, additive consumer UI.

It lets a user generate every map and chart for a player using the platform's
EXISTING visualization engine. It creates NO chart builders, NO themes, NO
filters, NO exporter and NO dataframe. It only drives what already exists:

* ``visual_registry``            - the chart/map plugins (categories + charts)
* ``fap.core.types.RenderContext`` + ``fap.visuals.Renderer`` - rendering
* ``fap.visuals.ExportEngine``   - PNG / SVG / PDF export
* ``fap.pipeline.FilterSet``     - the filter system
* the figure ``ThemeManager``    - the visualization themes

over the frame the module's ``player_event_frame`` already produced from
``WorkspaceManager.active_frame`` (the single canonical dataset). Players and
Scouting are pure consumers: they call this and pass their frame. No event data
is duplicated and no dataframe is cached here.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
from typing import Any

import streamlit as st

from fap.theme import components as C
from fap.theme import icon

_FAV_SCOPE = "viz_favorites"          # metadata only (reuses the user_state autosave tier)


# ---------------------------------------------------------------- registry / themes
def _registry():
    from fap.visuals.base import load_builtin_visuals, visual_registry
    load_builtin_visuals()
    return visual_registry


def _catalog(reg) -> list[dict[str, str]]:
    out = []
    for cls in reg:
        try:
            info = cls.info
            out.append({"id": info.id, "name": info.name,
                        "category": getattr(info, "category", "") or "General"})
        except Exception:
            continue
    return sorted(out, key=lambda v: (v["category"], v["name"]))


def _themes(shell):
    try:
        return shell.platform.services.get("themes")
    except Exception:
        return None


# ---------------------------------------------------------------- favorites (metadata only)
def _favorites(shell) -> list[str]:
    try:
        return list((shell.wm.load_autosave(shell.user, scope=_FAV_SCOPE) or {}).get("viz_ids", []))
    except Exception:
        return []


def _toggle_favorite(shell, viz_id: str) -> None:
    favs = _favorites(shell)
    favs.remove(viz_id) if viz_id in favs else favs.append(viz_id)
    try:
        shell.wm.autosave(shell.user, {"viz_ids": favs}, scope=_FAV_SCOPE)
    except Exception:
        pass


# ---------------------------------------------------------------- filters (reuse FilterSet)
def _filter_widgets(frame, key: str):
    from fap.pipeline.filters import FilterSet

    def opts(col: str) -> list[str]:
        if col not in frame.columns:
            return []
        return sorted(v for v in frame[col].astype(str).unique() if str(v).strip())

    a, b, c = st.columns(3)
    team = a.selectbox("Team", ["All", *opts("team")], key=f"{key}_f_team")
    opp = b.selectbox("Opponent", ["All", *opts("opponent")], key=f"{key}_f_opp")
    match = c.selectbox("Match", ["All", *opts("match_id")], key=f"{key}_f_match")
    comps = st.multiselect("Competition", opts("competition"), key=f"{key}_f_comp")
    seasons = st.multiselect("Season", opts("season"), key=f"{key}_f_season")
    events = st.multiselect("Event type", opts("event_type"), key=f"{key}_f_evt")
    outcomes = st.multiselect("Outcome", opts("outcome"), key=f"{key}_f_out")
    body = st.multiselect("Body part", opts("body_part"), key=f"{key}_f_body")
    setp = st.multiselect("Set piece", opts("set_piece"), key=f"{key}_f_sp")
    d, e = st.columns(2)
    half = d.selectbox("Half", ["All", "1", "2"], key=f"{key}_f_half")
    pressure = e.selectbox("Pressure", ["any", "under_pressure", "no_pressure"], key=f"{key}_f_press")
    minute = st.slider("Minute range", 0, 120, (0, 120), key=f"{key}_f_min")
    states = st.multiselect("Game state", ["winning", "drawing", "losing"], key=f"{key}_f_state")
    only_ok = st.checkbox("Only successful", key=f"{key}_f_ok")
    periods = () if half == "All" else (int(half),)
    return FilterSet(
        team=team, opponent=opp, match_id=match,
        competitions=tuple(comps), seasons=tuple(seasons), event_types=tuple(events),
        outcomes=tuple(outcomes), body_parts=tuple(body), set_pieces=tuple(setp),
        score_states=tuple(states), periods=periods,
        minute_range=(float(minute[0]), float(minute[1])),
        pressure_state=pressure, only_successful=only_ok)


def _signature(viz_id: str, controls: dict, filt, theme_id: str, frame) -> str:
    import dataclasses
    payload = json.dumps({"v": viz_id, "c": controls, "f": dataclasses.asdict(filt),
                          "t": theme_id, "n": int(len(frame))}, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- entry point
def render_visualization_workspace(shell, *, frame, player_name: str, key: str) -> None:
    """The workspace. ``frame`` is the player's event frame (from the module's
    ``player_event_frame`` over the active dataset); ``None``/empty triggers the
    Data-Hub-aware empty states. Consumes only existing engine services."""
    try:
        active = shell.wm.active_dataset(shell.user) if shell.wm is not None else None
    except Exception:
        active = None

    if active is None:
        go = C.render_empty_state(
            "No active dataset", "Open the Data Hub to activate a dataset. This workspace then "
            "renders every map and chart for the player from that dataset.",
            icon_name="datasets", action_label="Open Data Hub", key=f"{key}_dh")
        if go:
            shell.goto("data_hub")
        return
    if frame is None or getattr(frame, "empty", True):
        C.render_alert(f"No events found for {player_name} in the active dataset "
                       f"'{active.name}'.", "info")
        return

    reg = _registry()
    infos = _catalog(reg)
    if not infos:
        C.render_alert("No visualizations are registered.", "warning")
        return

    st.markdown(
        f'<div class="fap-viz-context">'
        f'<span>{icon("datasets", 14)} <b>{_html.escape(active.name)}</b></span>'
        f'<span>{icon("players", 14)} <b>{_html.escape(player_name)}</b></span>'
        f'<span>{len(frame):,} events</span></div>', unsafe_allow_html=True)

    # favorites quick-pick (metadata only)
    favs = _favorites(shell)
    fav_infos = [i for i in infos if i["id"] in favs]
    if fav_infos:
        st.caption("Favorites")
        cols = st.columns(min(4, len(fav_infos)))
        for i, fi in enumerate(fav_infos):
            if cols[i % len(cols)].button(fi["name"], key=f"{key}_fav_{fi['id']}",
                                          use_container_width=True):
                st.session_state[f"{key}_cat"] = fi["category"]
                st.session_state[f"{key}_viz"] = fi["id"]

    # Category -> Visualization
    cats = sorted({i["category"] for i in infos})
    cc = st.columns(2)
    cat = cc[0].selectbox("Visualization category", cats, key=f"{key}_cat")
    in_cat = [i for i in infos if i["category"] == cat]
    labels = {i["id"]: i["name"] for i in in_cat}
    viz_id = cc[1].selectbox("Visualization", [i["id"] for i in in_cat],
                             format_func=lambda x: labels.get(x, x), key=f"{key}_viz")
    try:
        viz = reg.create(viz_id)
    except Exception as exc:
        st.error(f"Could not load visualization: {exc}")
        return

    is_fav = viz_id in favs
    tcol, fcol = st.columns([3, 1])
    themes = _themes(shell)
    try:
        theme_ids = themes.ids() if themes else []
    except Exception:
        theme_ids = []
    theme_ids = theme_ids or ["opta_light", "opta_dark"]
    default_theme = theme_ids.index("opta_light") if "opta_light" in theme_ids else 0
    theme_id = tcol.selectbox("Theme", theme_ids, index=default_theme, key=f"{key}_theme")
    if fcol.button(("Unstar" if is_fav else "Star"), key=f"{key}_favtoggle",
                   use_container_width=True):
        _toggle_favorite(shell, viz_id)
        st.rerun()

    # Options (reuse controls system) + Filters (reuse FilterSet)
    with st.expander("Options", expanded=False):
        from fap.ui.components import render_controls
        controls = render_controls(getattr(viz, "all_controls", ()) or (),
                                   key_prefix=f"{key}_ctl_{viz_id}")
    if not controls.get("title"):
        controls["title"] = f"{player_name} - {labels.get(viz_id, viz_id)}"
    with st.expander("Filters", expanded=False):
        filt = _filter_widgets(frame, key)

    # Render on demand (reuse renderer caches); only render when config == last request
    signature = _signature(viz_id, controls, filt, theme_id, frame)
    if st.button("Render", type="primary", key=f"{key}_render", use_container_width=True):
        st.session_state[f"{key}_req"] = signature
    if st.session_state.get(f"{key}_req") != signature:
        st.caption("Choose a visualization, set options/filters, then click Render.")
        return

    _render_and_export(shell, viz, frame, controls, filt, theme_id, player_name, key,
                       themes)


def _render_and_export(shell, viz, frame, controls, filt, theme_id, player_name, key,
                       themes) -> None:
    from fap.core.types import RenderContext
    from fap.visuals.renderer import Renderer
    from fap.visuals.export import ExportEngine
    try:
        theme = themes.get(theme_id) if themes else None
        ctx = RenderContext(df=frame, theme=theme, controls=controls, meta={"filters": filt})
        cache = shell.platform.cache if getattr(shell, "platform", None) else None
        fig = Renderer(cache).render(viz, ctx)
    except Exception as exc:
        st.error(f"Could not render this visualization: {exc}")
        return
    st.pyplot(fig, use_container_width=True)
    try:
        export = ExportEngine()
        title = controls.get("title") or player_name
        ecols = st.columns(3)
        for col, fmt in zip(ecols, ("png", "svg", "pdf")):
            try:
                res = export.export(fig, title, fmt=fmt,
                                    dpi=controls.get("export_dpi", "standard"),
                                    transparent=bool(controls.get("transparent_bg")))
                col.download_button(fmt.upper(), data=res.data, file_name=res.filename,
                                    mime=res.mime, key=f"{key}_exp_{fmt}",
                                    use_container_width=True)
            except Exception:
                col.caption(f"{fmt.upper()} unavailable")
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)
