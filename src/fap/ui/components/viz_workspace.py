"""Player Visualization Workspace (Phase 13 + 13.1 polish) - a SHARED consumer UI.

One workspace, reused by Players and Scouting, that generates every map and chart
for a player using the platform's EXISTING visualization engine. It creates NO
chart builder, theme, filter, exporter or dataframe. It only drives what exists:

* ``visual_registry``            - the chart/map plugins (catalog, search)
* ``RenderContext`` + ``Renderer`` - rendering (byte-cached, on demand)
* ``ExportEngine``               - PNG / SVG / PDF export
* ``FilterSet``                  - filtering
* the figure ``ThemeManager``    - themes

over the frame ``player_event_frame`` produced from ``WorkspaceManager.active_frame``
(the single canonical dataset). Phase 13.1 adds, ALL as lightweight metadata in the
existing user_state autosave tier (no DB change, no figures stored): a card catalog
browser, instant search, saved templates, recent items, extended favorites, filter
presets and a render-scope switch (player events vs whole match).
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import logging
import uuid
from typing import Any

import streamlit as st

logger = logging.getLogger(__name__)

# The only charts that offer the optional interactive (Plotly) preview. Kept in
# sync with fap.visuals.charts.comparisons_interactive.INTERACTIVE_CHART_IDS.
_INTERACTIVE_CHART_IDS = frozenset({
    "player_percentile_radar", "player_comparison_bars", "team_radar", "rolling_form_trend"})

from fap.theme import components as C
from fap.theme import icon

# metadata scopes (user_state autosave) - never store rendered figures
FAV_SCOPE = "viz_favorites"
TPL_SCOPE = "viz_templates"
RECENT_SCOPE = "viz_recent"
PRESET_SCOPE = "viz_filter_presets"

# category slug -> an icon from the existing registry (metadata-derived thumbnail)
_SECTION_ICON = {
    "passing": "arrow-right", "shooting": "target", "possession": "layers",
    "touches": "grid", "carrying": "arrow-up", "receiving": "download",
    "defending": "shield", "goalkeeping": "cross-medical", "physical": "pulse",
    "set pieces": "setpiece", "set piece": "setpiece", "comparison": "list",
    "summary": "grid", "custom": "star", "general": "grid",
}

# Built-in templates + filter presets: METADATA only. viz_id is optional/best-effort
# (resolved against the live registry on apply) so nothing is hardcoded that could
# reference a missing plugin; they mainly set theme + a filter focus + scope.
_BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {"id": "tpl_scout", "name": "Scout Report", "builtin": True, "theme": "opta_light",
     "scope": "player", "viz_id": "", "controls": {}, "filters": {}},
    {"id": "tpl_winger", "name": "Attacking Winger", "builtin": True, "theme": "opta_dark",
     "scope": "player", "viz_id": "", "controls": {},
     "filters": {"custom": [["x", "gte", 66.666]]}},
    {"id": "tpl_cf", "name": "Centre Forward", "builtin": True, "theme": "opta_dark",
     "scope": "player", "viz_id": "", "controls": {},
     "filters": {"event_types": ["shot"]}},
    {"id": "tpl_playmaker", "name": "Playmaker", "builtin": True, "theme": "opta_light",
     "scope": "player", "viz_id": "", "controls": {},
     "filters": {"event_types": ["pass"]}},
    {"id": "tpl_cm", "name": "Central Midfielder", "builtin": True, "theme": "opta_light",
     "scope": "player", "viz_id": "", "controls": {}, "filters": {}},
    {"id": "tpl_fb", "name": "Full Back", "builtin": True, "theme": "opta_light",
     "scope": "player", "viz_id": "", "controls": {}, "filters": {}},
    {"id": "tpl_cb", "name": "Centre Back", "builtin": True, "theme": "opta_dark",
     "scope": "player", "viz_id": "", "controls": {},
     "filters": {"custom": [["x", "lte", 50.0]]}},
    {"id": "tpl_gk", "name": "Goalkeeper", "builtin": True, "theme": "opta_dark",
     "scope": "whole", "viz_id": "", "controls": {}, "filters": {}},
]

_BUILTIN_PRESETS: list[dict[str, Any]] = [
    {"id": "fp_open", "name": "Open Play", "builtin": True,
     "filters": {"custom": [["set_piece", "eq", ""]]}},
    {"id": "fp_set", "name": "Set Pieces", "builtin": True,
     "filters": {"custom": [["set_piece", "ne", ""]]}},
    {"id": "fp_final", "name": "Final Third", "builtin": True,
     "filters": {"custom": [["x", "gte", 66.666]]}},
    {"id": "fp_att", "name": "Attacking Third", "builtin": True,
     "filters": {"custom": [["x", "gte", 66.666]]}},
    {"id": "fp_def", "name": "Defensive Third", "builtin": True,
     "filters": {"custom": [["x", "lte", 33.333]]}},
    {"id": "fp_shots", "name": "Shots", "builtin": True, "filters": {"event_types": ["shot"]}},
    {"id": "fp_succ", "name": "Successful", "builtin": True, "filters": {"only_successful": True}},
]


# ---------------------------------------------------------------- metadata store
def _load(shell, scope: str, default: dict) -> dict:
    try:
        return shell.wm.load_autosave(shell.user, scope=scope) or dict(default)
    except Exception:
        return dict(default)


def _save(shell, scope: str, doc: dict) -> None:
    try:
        shell.wm.autosave(shell.user, doc, scope=scope)
    except Exception:
        # autosave of favorites/layout/filter presets - fails silently otherwise,
        # so the user's saved state just never persists with no clue why.
        logger.exception("workspace autosave failed for scope %r", scope)


def _favorites(shell) -> dict[str, list[str]]:
    doc = _load(shell, FAV_SCOPE, {})
    return {"viz": list(doc.get("viz", doc.get("viz_ids", []))),   # migrate legacy viz_ids
            "template": list(doc.get("template", [])),
            "theme": list(doc.get("theme", [])),
            "preset": list(doc.get("preset", []))}


def _toggle_favorite(shell, kind: str, item_id: str) -> None:
    fav = _favorites(shell)
    lst = fav.setdefault(kind, [])
    lst.remove(item_id) if item_id in lst else lst.append(item_id)
    _save(shell, FAV_SCOPE, fav)


def _recent(shell) -> list[str]:
    return list(_load(shell, RECENT_SCOPE, {}).get("viz_ids", []))


def _push_recent(shell, viz_id: str) -> None:
    ids = [viz_id] + [v for v in _recent(shell) if v != viz_id]
    _save(shell, RECENT_SCOPE, {"viz_ids": ids[:8]})


def _user_templates(shell) -> list[dict]:
    return list(_load(shell, TPL_SCOPE, {}).get("items", []))


def _all_templates(shell) -> list[dict]:
    return [*_BUILTIN_TEMPLATES, *_user_templates(shell)]


def _save_user_templates(shell, items: list[dict]) -> None:
    _save(shell, TPL_SCOPE, {"items": items})


def _user_presets(shell) -> list[dict]:
    return list(_load(shell, PRESET_SCOPE, {}).get("items", []))


def _all_presets(shell) -> list[dict]:
    return [*_BUILTIN_PRESETS, *_user_presets(shell)]


def _save_user_presets(shell, items: list[dict]) -> None:
    _save(shell, PRESET_SCOPE, {"items": items})


# ---------------------------------------------------------------- catalog (pure)
def _registry():
    from fap.visuals.base import load_builtin_visuals, visual_registry
    load_builtin_visuals()
    return visual_registry


def _events_of(cls) -> list[str]:
    for attr in ("event_types", "supported_events"):
        val = getattr(cls.info, attr, None) or getattr(cls, attr, None)
        if val:
            return [str(v) for v in val][:6]
    return []


def _catalog(reg) -> list[dict[str, Any]]:
    out = []
    for cls in reg:
        try:
            info = cls.info
            out.append({"id": info.id, "name": info.name,
                        "category": getattr(info, "category", "") or "General",
                        "description": getattr(info, "description", "") or "",
                        "events": _events_of(cls)})
        except Exception:
            continue
    return sorted(out, key=lambda v: (v["category"], v["name"]))


def search_catalog(infos: list[dict], query: str) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return infos
    return [i for i in infos
            if q in i["name"].lower() or q in i["category"].lower()
            or q in (i.get("description") or "").lower()]


def group_catalog(infos: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for i in infos:
        groups.setdefault(i["category"], []).append(i)
    return dict(sorted(groups.items()))


def _section_icon(category: str) -> str:
    return _SECTION_ICON.get((category or "").strip().lower(), "grid")


# ---------------------------------------------------------------- filters / scope
def _filter_widgets(frame, key: str):
    from fap.pipeline.filters import FilterSet

    def opts(col: str) -> list[str]:
        return sorted(v for v in frame[col].astype(str).unique() if str(v).strip()) \
            if col in frame.columns else []

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


def _filterset_from_dict(data: dict):
    from fap.pipeline.filters import FilterSet
    try:
        return FilterSet.from_dict(data or {})
    except Exception:
        return FilterSet()


def _scope_frame(shell, scope: str, player_frame):
    """The dataframe passed to the engine. 'whole' uses the WHOLE active frame (team
    context, e.g. passing networks) WITHOUT player filtering; 'player' uses the
    player's frame. Never creates a dataset - both come from active_frame."""
    if scope == "whole":
        try:
            return shell.wm.active_frame(shell.user)
        except Exception:
            return player_frame
    return player_frame


def _needs_team_context(info: dict) -> bool:
    text = f"{info.get('name','')} {info.get('category','')}".lower()
    return "network" in text or "passing network" in text


def _signature(viz_id: str, controls: dict, filt, theme_id: str, frame, scope: str = "player") -> str:
    import dataclasses
    payload = json.dumps({"v": viz_id, "c": controls, "f": dataclasses.asdict(filt),
                          "t": theme_id, "s": scope, "n": int(len(frame))},
                         sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- entry point
def render_visualization_workspace(shell, *, frame, player_name: str, key: str,
                                   on_assign=None, curate=None, event_filter=None,
                                   dataset_context=None) -> None:
    """Render the player visualization workspace.

    ``on_assign`` (optional): a callback ``(png_bytes, title, viz_id) -> None``. When
    given, each rendered chart shows an "Assign to player report" button that hands
    the exact PNG to the callback (Scouting persists it to the player). Keeps this
    shared component decoupled - it never imports scouting/players, only calls back.

    ``curate`` (optional): a callable ``list[catalog_dict] -> list[catalog_dict]`` that
    filters/re-groups the registry catalog for a caller-specific presentation (Scouting
    passes ``fap.scouting.catalog.curate_for_scouting`` to hide team/tactical visuals and
    file the rest under player-centric headings). Default ``None`` = the full registry
    catalog, unchanged — so First-Team and Open Play behave exactly as before.

    ``dataset_context`` (optional): an explicit ``(dataset_id, dataset_name)`` for the
    dataset the ``frame`` was read from. When given, the workspace renders that frame
    WITHOUT requiring (or changing) the globally active dataset — so a caller that reads
    a dataset BY ID (e.g. a team's linked opposition data, Teams) shows the same charts
    regardless of what is active in the Data Hub. Default ``None`` = use the active
    dataset, unchanged.
    """
    if dataset_context is not None:
        from types import SimpleNamespace
        active = SimpleNamespace(id=dataset_context[0], name=dataset_context[1])
    else:
        try:
            active = shell.wm.active_dataset(shell.user) if shell.wm is not None else None
        except Exception:
            # a lookup error would otherwise render as the legitimate "No active dataset"
            # empty state below, hiding a real backend failure - log the real cause.
            logger.exception("active dataset lookup failed in viz workspace")
            active = None

    # --- empty states (Data Hub aware) ---
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
                       f"'{active.name}'. The dataset has no events for this player "
                       f"(the name may differ in the data).", "info")
        return

    reg = _registry()
    infos = _catalog(reg)
    if curate is not None:                    # caller-specific curation (e.g. Scouting player catalog)
        try:
            infos = curate(infos)
        except Exception:
            logger.exception("catalog curation failed; falling back to full registry catalog")
    if not infos:
        C.render_alert("No visualizations are registered.", "warning")
        return
    labels = {i["id"]: i["name"] for i in infos}

    # ================= context bar (player · dataset · events · scope) =========
    scope = st.session_state.get(f"{key}_scope", "player")
    st.markdown(
        f'<div class="fap-viz-context">'
        f'<span>{icon("players", 14)} <b>{_html.escape(player_name)}</b></span>'
        f'<span>{icon("datasets", 14)} <b>{_html.escape(active.name)}</b></span>'
        f'<span>{len(frame):,} player events</span></div>', unsafe_allow_html=True)
    sc1, sc2 = st.columns([1, 3], vertical_alignment="center")
    scope = sc1.radio("Render scope", ["player", "whole"], horizontal=True,
                      format_func=lambda s: "Player events" if s == "player" else "Whole match",
                      index=0 if scope == "player" else 1, key=f"{key}_scope")
    sc2.caption("Whole match feeds the whole active dataset (team context, e.g. Passing Networks) "
                "without player filtering - still the same active_frame, no new dataset.")

    # ================= search · recent · favorites · templates =================
    query = st.text_input("Search visualizations", key=f"{key}_search",
                          placeholder="heat, pass, shot, pizza, radar…")
    _quick_rows(shell, key, infos, labels)
    _templates_bar(shell, key, infos)

    # ================= catalog browser (cards, grouped, searchable) ============
    visible = search_catalog(infos, query)
    favs = _favorites(shell)
    st.markdown('<div class="fap-rail-head">Visualization catalog</div>', unsafe_allow_html=True)
    if not visible:
        C.render_alert(f"No visualization matches '{query}'.", "info")
    for section, items in group_catalog(visible).items():
        with st.expander(f"{section}  ·  {len(items)}", expanded=bool(query)):
            _cards(shell, key, section, items, favs["viz"])

    # ================= selected visualization: settings · preview · export =====
    sel = st.session_state.get(f"{key}_sel_viz")
    if not sel or sel not in labels:
        st.caption("Select a visualization from the catalog to configure and render it.")
        return
    _selected_workspace(shell, reg, key, sel, labels, frame, player_name, scope, infos, on_assign,
                        event_filter=event_filter, dataset_name=getattr(active, "name", ""))


# ---------------------------------------------------------------- quick rows
def _chip_row(title: str, ids: list[str], labels: dict, key: str, on_click_key: str) -> None:
    picks = [i for i in ids if i in labels][:6]
    if not picks:
        return
    st.caption(title)
    cols = st.columns(min(6, len(picks)))
    for i, vid in enumerate(picks):
        if cols[i % len(cols)].button(labels[vid], key=f"{key}_{on_click_key}_{vid}",
                                      use_container_width=True):
            st.session_state[f"{key}_sel_viz"] = vid
            st.rerun()


def _quick_rows(shell, key: str, infos: list[dict], labels: dict) -> None:
    _chip_row("Recent", _recent(shell), labels, key, "recent")
    _chip_row("Favorites", _favorites(shell)["viz"], labels, key, "favq")


def _templates_bar(shell, key: str, infos: list[dict]) -> None:
    templates = _all_templates(shell)
    valid_ids = {i["id"] for i in infos}
    with st.expander("Templates & filter presets", expanded=False):
        tcol, pcol = st.columns(2)
        with tcol:
            st.caption("Templates (visualization configuration only)")
            names = {t["id"]: t["name"] for t in templates}
            tid = st.selectbox("Template", list(names), format_func=lambda i: names[i],
                               key=f"{key}_tpl_sel")
            b1, b2, b3 = st.columns(3)
            if b1.button("Apply", key=f"{key}_tpl_apply", use_container_width=True):
                tpl = next((t for t in templates if t["id"] == tid), None)
                if tpl:
                    _apply_template(key, tpl, valid_ids)
                    st.rerun()
            if b2.button("Duplicate", key=f"{key}_tpl_dup", use_container_width=True):
                src = next((t for t in templates if t["id"] == tid), None)
                if src:
                    items = _user_templates(shell)
                    items.append({**{k: v for k, v in src.items() if k != "builtin"},
                                  "id": f"tpl_{uuid.uuid4().hex[:8]}",
                                  "name": f"{src['name']} (copy)"})
                    _save_user_templates(shell, items)
                    st.rerun()
            if b3.button("Delete", key=f"{key}_tpl_del", use_container_width=True):
                _save_user_templates(shell, [t for t in _user_templates(shell) if t["id"] != tid])
                st.rerun()
            new_name = st.text_input("Save current as template", key=f"{key}_tpl_name",
                                     placeholder="Template name")
            if st.button("Save template", key=f"{key}_tpl_save", use_container_width=True) \
                    and new_name.strip():
                cfg = _current_config(key)
                items = _user_templates(shell)
                items.append({"id": f"tpl_{uuid.uuid4().hex[:8]}", "name": new_name.strip(), **cfg})
                _save_user_templates(shell, items)
                st.toast(f"Saved template '{new_name.strip()}'")
                st.rerun()
        with pcol:
            st.caption("Filter presets (metadata only)")
            presets = _all_presets(shell)
            pnames = {p["id"]: p["name"] for p in presets}
            pid = st.selectbox("Preset", list(pnames), format_func=lambda i: pnames[i],
                               key=f"{key}_fp_sel")
            p1, p2 = st.columns(2)
            if p1.button("Apply preset", key=f"{key}_fp_apply", use_container_width=True):
                pr = next((p for p in presets if p["id"] == pid), None)
                if pr:
                    st.session_state[f"{key}_active_filters"] = dict(pr.get("filters") or {})
                    st.session_state[f"{key}_active_filter_name"] = pr["name"]
                    st.rerun()
            if p2.button("Delete preset", key=f"{key}_fp_del", use_container_width=True):
                _save_user_presets(shell, [p for p in _user_presets(shell) if p["id"] != pid])
                st.rerun()
            pname = st.text_input("Save current filters as preset", key=f"{key}_fp_name",
                                  placeholder="Preset name")
            if st.button("Save preset", key=f"{key}_fp_save", use_container_width=True) \
                    and pname.strip():
                import dataclasses
                filt = st.session_state.get(f"{key}_last_filters") or {}
                items = _user_presets(shell)
                items.append({"id": f"fp_{uuid.uuid4().hex[:8]}", "name": pname.strip(),
                              "filters": filt})
                _save_user_presets(shell, items)
                st.rerun()


def _apply_template(key: str, tpl: dict, valid_ids: set) -> None:
    if tpl.get("viz_id") and tpl["viz_id"] in valid_ids:
        st.session_state[f"{key}_sel_viz"] = tpl["viz_id"]
    st.session_state[f"{key}_scope"] = tpl.get("scope", "player")
    st.session_state[f"{key}_applied_theme"] = tpl.get("theme", "")
    st.session_state[f"{key}_applied_controls"] = dict(tpl.get("controls") or {})
    filters = dict(tpl.get("filters") or {})
    st.session_state[f"{key}_active_filters"] = filters or None
    st.session_state[f"{key}_active_filter_name"] = tpl["name"] if filters else ""


def _current_config(key: str) -> dict:
    return {"viz_id": st.session_state.get(f"{key}_sel_viz", ""),
            "theme": st.session_state.get(f"{key}_theme", ""),
            "scope": st.session_state.get(f"{key}_scope", "player"),
            "controls": dict(st.session_state.get(f"{key}_last_controls") or {}),
            "filters": dict(st.session_state.get(f"{key}_last_filters") or {})}


# ---------------------------------------------------------------- cards
def _cards(shell, key: str, section: str, items: list[dict], fav_ids: list[str]) -> None:
    ic = _section_icon(section)
    cols = st.columns(2)
    for i, info in enumerate(items):
        with cols[i % 2]:
            star = icon("star", 13) if info["id"] in fav_ids else ""
            events = (" · " + ", ".join(info["events"])) if info.get("events") else ""
            desc = info.get("description") or ""
            st.markdown(
                f'<div class="fap-viz-card"><div class="h">{icon(ic, 15)} '
                f'<b>{_html.escape(info["name"])}</b> {star}</div>'
                f'<div class="d">{_html.escape(desc)}</div>'
                f'<div class="e">{_html.escape(info["category"])}{_html.escape(events)}</div></div>',
                unsafe_allow_html=True)
            a, b = st.columns([3, 1])
            if a.button("Open", key=f"{key}_open_{info['id']}", use_container_width=True):
                st.session_state[f"{key}_sel_viz"] = info["id"]
                _push_recent(shell, info["id"])
                st.rerun()
            fav = info["id"] in fav_ids
            if b.button("Unstar" if fav else "Star", key=f"{key}_star_{info['id']}",
                        use_container_width=True):
                _toggle_favorite(shell, "viz", info["id"])
                st.rerun()


# ---------------------------------------------------------------- selected viz
def _selected_workspace(shell, reg, key, sel, labels, player_frame, player_name, scope, infos,
                        on_assign=None, event_filter=None, dataset_name="") -> None:
    info = next((i for i in infos if i["id"] == sel), {"id": sel, "name": labels.get(sel, sel)})
    try:
        viz = reg.create(sel)
    except Exception as exc:
        st.error(f"Could not load visualization: {exc}")
        return

    st.divider()
    hcol, fcol = st.columns([4, 1], vertical_alignment="center")
    hcol.markdown(f"#### {_html.escape(labels.get(sel, sel))}")
    is_fav = sel in _favorites(shell)["viz"]
    if fcol.button("Unstar" if is_fav else "Star", key=f"{key}_selstar", use_container_width=True):
        _toggle_favorite(shell, "viz", sel)
        st.rerun()

    render_frame = _scope_frame(shell, scope, player_frame)
    if render_frame is None or getattr(render_frame, "empty", True):
        C.render_alert("No events available for the selected render scope.", "info")
        return
    # Scouting Map Studio opt-in (C4): a caller-supplied event_filter renders the SEMANTIC map
    # controls for THIS map and returns the filtered player-event frame (via fap.scouting.map_filters).
    # First-Team / Open Play pass no event_filter, so this is a no-op for them. Player scope only.
    if event_filter is not None and scope == "player":
        render_frame = event_filter(sel, render_frame, key)
        if render_frame is None or getattr(render_frame, "empty", True):
            C.render_alert("No events match these filters. Reset filters or broaden the zone.", "info")
            return
    if _needs_team_context(info) and scope != "whole":
        C.render_alert("This visualization needs whole-match (team) context. Switch Render "
                       "scope to 'Whole match' above.", "warning")

    # theme picker (reuse figure ThemeManager)
    themes = _theme_manager(shell)
    try:
        theme_ids = themes.ids() if themes else []
    except Exception:
        theme_ids = []
    theme_ids = theme_ids or ["opta_light", "opta_dark"]
    applied_theme = st.session_state.pop(f"{key}_applied_theme", "") if \
        st.session_state.get(f"{key}_applied_theme") else ""
    if applied_theme in theme_ids:
        st.session_state[f"{key}_theme"] = applied_theme
    default_idx = theme_ids.index("opta_light") if "opta_light" in theme_ids else 0
    tcol, dcol = st.columns([2, 1])
    theme_id = tcol.selectbox("Theme", theme_ids, index=default_idx, key=f"{key}_theme")
    dpi = dcol.selectbox("Export DPI", ["screen", "standard", "print", "ultra"], index=1,
                         key=f"{key}_dpi")

    # OPTIONAL interactive Plotly preview - only for the four comparison charts, and
    # OFF by default so nothing about the existing static-render/export path changes.
    interactive_preview = False
    if sel in _INTERACTIVE_CHART_IDS:
        interactive_preview = st.checkbox(
            "Interactive preview (Plotly)", value=False, key=f"{key}_interactive_{sel}",
            help="Adds an interactive Plotly copy below the static chart. Downloads and "
                 "report assignment still use the static image.")

    # settings: Display + Options + Filters as tabs (single level - no nested expanders)
    set_tabs = st.tabs(["Display", "Options", "Filters"])
    saved_ctl = dict(st.session_state.get(f"{key}_applied_controls") or {})
    with set_tabs[0]:
        # Strict capability-gated presentation toggles (Phase 2) + the note preview.
        from fap.ui.components.display_panel import render_display_controls
        caps = getattr(viz, "capabilities", None)
        disp_defaults = getattr(viz, "display_defaults", {}) or {}
        display_vals = render_display_controls(
            caps, saved_ctl, key=f"{key}_disp_{sel}", defaults=disp_defaults) \
            if caps is not None else {}
    with set_tabs[1]:
        # styling controls EXCLUDING the display toggles (owned by the Display tab)
        from fap.ui.components import render_controls
        from fap.visuals.display import DISPLAY_KEYS
        controls = render_controls(getattr(viz, "all_controls", ()) or (),
                                   saved=saved_ctl, key_prefix=f"{key}_ctl_{sel}",
                                   exclude=DISPLAY_KEYS)
    controls.update(display_vals)
    controls["export_dpi"] = dpi
    if not controls.get("title"):
        controls["title"] = f"{player_name} - {labels.get(sel, sel)}"
    with set_tabs[2]:
        active_filters = st.session_state.get(f"{key}_active_filters")
        if active_filters:
            name = st.session_state.get(f"{key}_active_filter_name") or "preset"
            st.markdown(f"Filter preset **{_html.escape(name)}** is active.")
            if st.button("Clear preset / customize", key=f"{key}_fp_clear"):
                st.session_state.pop(f"{key}_active_filters", None)
                st.session_state.pop(f"{key}_active_filter_name", None)
                st.rerun()
            filt = _filterset_from_dict(active_filters)
        else:
            filt = _filter_widgets(render_frame, key)

    # remember current config for template/preset saving (metadata only)
    import dataclasses
    st.session_state[f"{key}_last_controls"] = dict(controls)
    st.session_state[f"{key}_last_filters"] = dataclasses.asdict(filt)

    # on-demand render (reuse renderer caches)
    signature = _signature(sel, controls, filt, theme_id, render_frame, scope)
    if st.button("Render", type="primary", key=f"{key}_render", use_container_width=True):
        st.session_state[f"{key}_req"] = signature
        _push_recent(shell, sel)
    if st.session_state.get(f"{key}_req") != signature:
        st.caption("Adjust options/filters, then click Render.")
        return
    scope_label = f"Player · {player_name}" if scope == "player" else "Whole match"
    _render_and_export(shell, viz, render_frame, controls, filt, theme_id, player_name, key, themes,
                       on_assign=on_assign, viz_id=sel, interactive=interactive_preview,
                       dataset_name=dataset_name, scope_label=scope_label)


def _theme_manager(shell):
    try:
        return shell.platform.services.get("themes")
    except Exception:
        return None


def note_fields_for(viz, frame) -> list[str]:
    """The canonical fields a visualization genuinely consumes: its declared
    ``requires`` present in the frame, plus capability-implied fields (xG when the
    map encodes xG, outcome when it splits on outcome, end coords for vector maps).
    Honest at the visualization level — never 'every column in the dataframe'."""
    cols = set(getattr(frame, "columns", []))
    fields = [c for c in getattr(viz, "requires", ()) if c in cols]
    caps = getattr(viz, "capabilities", None)
    if caps is not None:
        for cond, col in ((caps.xg, "xg"), (caps.outcome, "outcome")):
            if cond and col in cols and col not in fields:
                fields.append(col)
    return fields


def _render_note(viz, ctx, controls, *, dataset_name: str, scope_label: str, key: str) -> None:
    """Render the Data & Methodology note for a fap.visuals plugin from its live
    render context (fields/filters/metric/coords/scope) — reused by every consumer."""
    from fap.ui.components.display_panel import render_methodology_note
    from fap.visuals.methodology import build_note
    pitch_based = bool(getattr(viz, "pitch_based", True))
    length = width = None
    spec_label = ""
    if pitch_based:
        try:
            from fap.visuals.pitch import get_spec
            spec = get_spec(controls.get("pitch_spec"))
            length = getattr(spec, "length", None)
            width = getattr(spec, "width", None)
        except Exception:
            length = width = None
        spec_label = str(controls.get("pitch_spec") or "").upper()
    note = build_note(
        dataset=dataset_name or "events", fields=note_fields_for(viz, ctx.df),
        filters=ctx.meta.get("filters"), metric=getattr(viz.info, "name", ""),
        pitch_based=pitch_based, length=length, width=width, spec_label=spec_label,
        scope=scope_label)
    render_methodology_note(note, key=key)


def _prepare_frame(frame):
    """Chart-ready frame: adds the derived columns the visualization engine and
    FilterSet expect (time_min, thirds, progressive, …), REUSING Open Play's
    existing transform - exactly how Opponent Analysis prepares its frame for the
    same engine. Not a new pipeline and not a duplicated source: the active_frame
    stays canonical; this is the standard on-render preparation step."""
    try:
        from fap.openplay.transforms import add_derived_columns
        out = add_derived_columns(frame)
    except Exception:
        out = frame.copy()
    if "time_min" not in out.columns:
        import pandas as pd
        out = out.copy()
        out["time_min"] = (pd.to_numeric(out.get("minute", 0), errors="coerce").fillna(0)
                           + pd.to_numeric(out.get("second", 0), errors="coerce").fillna(0) / 60)
    return out


def _render_plotly_preview(viz_id, ctx, filt, key) -> None:
    """Opt-in interactive (Plotly) copy of a comparison chart, rendered BELOW the
    static one. It never touches the matplotlib figure used for export/assign, and
    any failure degrades to a caption - it can never break the static path."""
    try:
        from fap.core.types import RenderContext
        from fap.visuals.charts import comparisons_interactive as CI
        df = ctx.df
        try:                                    # match the static chart's filtered data
            if filt is not None:
                df = filt.apply(ctx.df)
        except Exception:
            df = ctx.df
        pctx = RenderContext(df=df, theme=ctx.theme, controls=ctx.controls, meta=ctx.meta)
        fig = CI.build(viz_id, pctx)
        if fig is None:
            return
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Interactive preview (Plotly) - downloads and report assignment use the "
                   "static chart above.")
    except Exception:
        logger.exception("Interactive (Plotly) preview failed for %r", viz_id)
        st.caption("Interactive preview unavailable.")


def _render_and_export(shell, viz, frame, controls, filt, theme_id, player_name, key, themes,
                       on_assign=None, viz_id: str = "", interactive: bool = False,
                       dataset_name: str = "", scope_label: str = "") -> None:
    from fap.core.types import RenderContext
    from fap.visuals.renderer import Renderer
    from fap.visuals.export import ExportEngine
    try:
        theme = themes.get(theme_id) if themes else None
        ctx = RenderContext(df=_prepare_frame(frame), theme=theme, controls=controls,
                            meta={"filters": filt})
        cache = shell.platform.cache if getattr(shell, "platform", None) else None
        fig = Renderer(cache).render(viz, ctx)
    except Exception as exc:
        st.error(f"Could not render this visualization: {exc}")
        return
    st.pyplot(fig, use_container_width=True)
    _render_note(viz, ctx, controls, dataset_name=dataset_name, scope_label=scope_label,
                 key=f"{key}_method")
    # Additive, default-off: an interactive copy shown alongside the static chart.
    # The matplotlib `fig` remains the ONLY source for the export/assign flow below.
    if interactive and viz_id in _INTERACTIVE_CHART_IDS:
        _render_plotly_preview(viz_id, ctx, filt, key)
    try:
        export = ExportEngine()
        title = controls.get("title") or player_name
        png_bytes = None
        ecols = st.columns(3)
        for col, fmt in zip(ecols, ("png", "svg", "pdf")):
            try:
                res = export.export(fig, title, fmt=fmt,
                                    dpi=controls.get("export_dpi", "standard"),
                                    transparent=bool(controls.get("transparent_bg")))
                if fmt == "png":
                    png_bytes = res.data
                col.download_button(fmt.upper(), data=res.data, file_name=res.filename,
                                    mime=res.mime, key=f"{key}_exp_{fmt}", use_container_width=True)
            except Exception:
                # Keep the UI graceful, but never swallow the cause silently - an
                # empty exporter registry (the class of bug this guards) must be
                # visible in the logs.
                logger.exception("Export to %s failed for %r", fmt, viz_id or title)
                col.caption(f"{fmt.upper()} unavailable")

        # assign the exact rendered chart to the player's report (Scouting/Players)
        if on_assign is not None:
            if png_bytes is None:
                try:
                    png_bytes = export.export(fig, title, fmt="png").data
                except Exception:
                    logger.exception("PNG export for report assignment failed for %r",
                                     viz_id or title)
                    png_bytes = None
            if png_bytes and st.button("Assign to player report", key=f"{key}_assign",
                                       type="primary", use_container_width=True):
                try:
                    on_assign(png_bytes, title, viz_id)
                    st.toast("Chart assigned to the player report")
                except Exception as exc:
                    st.error(f"Could not assign this chart: {exc}")
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)
