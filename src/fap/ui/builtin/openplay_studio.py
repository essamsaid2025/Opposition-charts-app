"""Open Play Studio (Phase 16A) — a professional desktop workspace around the LOCKED
Open Play engine.

This is a PRESENTATION/WORKSPACE layer only. It owns no analytics state: the engine
(``fap.openplay.engine``, injected by app.py at startup) is the single source of truth
for the chart registry, the default render context, the shared filter apply and export;
the active dataset/frame come from ``WorkspaceManager``. The Studio never imports app.py
at runtime — it resolves the engine via ``get_engine()`` and degrades to a professional
empty state if it is not connected.

Layout is modular: every region is filled from a PANELS registry, so future panels
(Video, GPS, Tracking, AI, Reports, Tactical Board) can plug in without touching the
shell. Charts are produced by the exact same engine + context as ``run_app`` (curated
controls override ``default_ctx``; unset keys keep the engine defaults), so output is
byte-identical. Renders are cached by a context signature so nothing regenerates on a
plain rerun.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.openplay.engine import get_engine
from fap.theme import components as C
from fap.theme import icon
from fap.ui.nav import icon_css
from fap.ui.page import Page, page_registry

# ---- session keys (UI state only; analysis state lives in engine + WorkspaceManager) ----
K = "_ops_"
SEL = K + "selections"       # filter selections dict
VIZ = K + "viz"              # current visualization name
CAT = K + "cat"              # current category
CTRL = K + "controls"        # curated control overrides (nested groups)
THEME = K + "theme"          # visualization theme name
REQ = K + "req_sig"          # signature the user asked to render
CACHE = K + "cache"          # {sig: {"png": bytes, "meta": {...}}}
HIST = K + "history"         # [ {sig, meta, ts} ] newest last
MSG = K + "messages"         # [ str ] session log
COLLAPSE = K + "collapse"    # {"left": bool, "right": bool, "bottom": bool}
RATIO = K + "ratio"          # layout ratio preset
FULL = K + "full"            # fullscreen (hide side panels)
VIEW = K + "active_view"     # active saved-view id (for status)

VIEW_KIND = "openplay_view"      # WorkspaceManager preset kind (metadata only)
FAV_SCOPE = "openplay_favorites"  # WorkspaceManager autosave scope
RECENT_SCOPE = "openplay_recent_views"
MODE = K + "mode"                # "home" | "workspace"


def _recent_view_ids(shell) -> list[str]:
    try:
        return [str(x) for x in (shell.wm.load_autosave(shell.user, scope=RECENT_SCOPE).get("ids") or [])]
    except Exception:
        return []


def _push_recent_view(shell, view_id: str) -> None:
    ids = [view_id] + [x for x in _recent_view_ids(shell) if x != view_id]
    try:
        shell.wm.autosave(shell.user, {"ids": ids[:8]}, scope=RECENT_SCOPE)
    except Exception:
        pass

_RATIOS = {"Balanced": (2.4, 6.0, 2.6), "Wide stage": (1.8, 7.4, 1.8), "Focus": (1.4, 8.2, 1.4)}


# ================================================================ workspace context
@dataclass
class Studio:
    """Everything a panel needs. Presentation only — no owned analytics."""
    shell: Any
    engine: Any
    can_edit: bool
    dataset: Any = None
    frame: Any = None            # derived (add_derived_columns) active frame
    filtered: Any = None         # after apply_filters (before pitch transform)
    render_frame: Any = None     # after apply_pitch_transforms (what render() gets)
    df_all: Any = None           # whole frame pitch-transformed (ctx.aux.df_all)
    spec: Any = None
    vt: dict | None = None
    ctx: dict | None = None
    signature: str = ""


# ---- session helpers --------------------------------------------------------------
def _ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default() if callable(default) else default
    return st.session_state[key]


def _selections() -> dict:
    return _ss(SEL, dict)


def _controls() -> dict:
    return _ss(CTRL, dict)


def _collapse() -> dict:
    return _ss(COLLAPSE, lambda: {"left": False, "right": False, "bottom": False})


def _log(msg: str) -> None:
    msgs = _ss(MSG, list)
    msgs.append(msg)
    del msgs[:-30]


# ---- favorites (WorkspaceManager autosave scope) ----------------------------------
def _favorites(shell) -> dict[str, list[str]]:
    try:
        doc = shell.wm.load_autosave(shell.user, scope=FAV_SCOPE) or {}
    except Exception:
        doc = {}
    return {"viz": list(doc.get("viz", [])), "filter": list(doc.get("filter", [])),
            "view": list(doc.get("view", []))}


def _toggle_favorite(shell, kind: str, item: str) -> None:
    fav = _favorites(shell)
    lst = fav.setdefault(kind, [])
    lst.remove(item) if item in lst else lst.append(item)
    try:
        shell.wm.autosave(shell.user, fav, scope=FAV_SCOPE)
    except Exception:
        pass


# ================================================================ signature & prep
def _signature(w: Studio) -> str:
    payload = json.dumps({
        "viz": st.session_state.get(VIZ), "theme": st.session_state.get(THEME),
        "sel": _selections(), "ctl": _controls(),
        "n": int(len(w.frame)) if w.frame is not None else 0,
    }, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


# PitchSpec fields the Inspector may set (pitch + thirds live in one spec)
_SPEC_FIELDS = ("orientation", "view", "custom_crop", "mirror", "flip_y", "stripes",
                "thirds_mode", "thirds_positions", "thirds_color", "thirds_width",
                "thirds_alpha", "thirds_labels", "lane_lines")


def _build_spec(w: Studio):
    """PitchSpec from Inspector pitch+thirds controls; unset -> engine defaults."""
    pitch = {**_controls().get("pitch", {}), **_controls().get("thirds", {})}
    kw = {k: pitch[k] for k in _SPEC_FIELDS if k in pitch}
    return w.engine.pitch_spec_cls(**kw)


def _build_ctx(w: Studio) -> dict:
    """Every Inspector control override on top of the engine's single-source default_ctx.
    Unset keys keep the engine default, so output matches run_app exactly."""
    ctl = _controls()
    viz = st.session_state.get(VIZ) or ""
    overrides: dict[str, Any] = {"aux": {**dict(ctl.get("aux") or {}), "df_all": w.df_all}}
    for k in ("title", "show_title", "title_size", "label_size", "legend_size", "respect_filter"):
        if k in ctl:
            overrides[k] = ctl[k]
    overrides["title"] = ctl.get("title") or viz          # default title = viz name (as run_app)
    for group in ("marker", "arrow", "labels", "legend", "heat", "colors"):
        if ctl.get(group):
            overrides[group] = dict(ctl[group])
    if _selections().get("event_types"):                  # event filter toggles respect_filter (run_app)
        overrides["respect_filter"] = True
    return w.engine.default_ctx(w.vt, w.spec, **overrides)


# ---- theme resolution (named + Club/Custom + font) — mirrors run_app's theme block ----
def _resolve_theme(w: Studio) -> dict:
    themes = w.engine.metadata.get("themes", {})
    name = st.session_state.get(THEME) or next(iter(themes), "")
    tctl = _controls().setdefault("theme_custom", {})
    if name == "Club Theme":
        base = themes.get("Dark Professional" if tctl.get("club_dark", True) else "Light Professional",
                          next(iter(themes.values()), {}))
        vt = dict(base, accent=tctl.get("primary", "#B00020"), accent2=tctl.get("secondary", "#FFD700"),
                  danger=tctl.get("primary", "#B00020"), warning=tctl.get("secondary", "#FFD700"))
    elif name == "Custom Theme":
        vt = dict(themes.get("Light Professional", next(iter(themes.values()), {})))
        for k in ("bg", "pitch", "line", "text", "accent", "accent2"):
            if tctl.get(k):
                vt[k] = tctl[k]
        if tctl.get("panel"):
            vt["panel"] = vt["card_face"] = vt["legend_face"] = tctl["panel"]
        vt["stripe"] = vt.get("pitch", vt.get("stripe"))
    else:
        vt = dict(themes.get(name, next(iter(themes.values()), {})))
    font = _controls().get("font")
    if font and font != "Theme default":
        vt["font"] = {"Monospace": "DejaVu Sans Mono"}.get(font, font)
    return vt


def _prepare_pre(w: Studio) -> None:
    """Before the input panels: derived frame + theme + spec, so the Filters panel has its
    options and the Inspector can read its defaults. Filtering/ctx happen after inputs."""
    from fap.openplay import add_derived_columns
    st.session_state[K + "ds_name"] = getattr(w.dataset, "name", "")
    w.frame = add_derived_columns(w.shell.wm.active_frame(w.shell.user))
    w.spec = _build_spec(w)
    w.vt = _resolve_theme(w)


def _prepare(w: Studio) -> None:
    """After the input panels: apply the CURRENT selections/controls exactly as run_app
    (active -> derived -> filter -> pitch) and build the render context + signature."""
    if w.frame is None:
        _prepare_pre(w)
    w.spec = _build_spec(w)                       # recompute with current pitch/thirds
    w.vt = _resolve_theme(w)                      # recompute with current theme
    w.filtered = w.engine.apply_filters(w.frame, _selections())
    w.df_all = w.engine.apply_pitch_transforms(w.frame, w.spec)
    w.render_frame = w.engine.apply_pitch_transforms(w.filtered, w.spec)
    w.ctx = _build_ctx(w)
    w.signature = _signature(w)


# ================================================================ toolbar
def _toolbar(w: Studio) -> None:
    ds_name = getattr(w.dataset, "name", "—")
    viz = st.session_state.get(VIZ) or "No visualization"
    with st.container(key="ops_toolbar"):
        st.markdown(
            f'<div class="ops-tb-title"><span class="chip">{icon("analysis",16)}</span>'
            f'<div><div class="t">{_html.escape(str(viz))}</div>'
            f'<div class="s">{icon("datasets",11)} {_html.escape(str(ds_name))}</div></div></div>',
            unsafe_allow_html=True)
        cols = st.columns(12, gap="small")
        hist = _ss(HIST, list)
        specs = [
            ("ops_undo", "chevron-left", "Previous render", lambda: _history_step(-1), not hist),
            ("ops_redo", "chevron-right", "Next render", lambda: _history_step(1), not hist),
            ("ops_refresh", "refresh", "Refresh (re-render current)",
             lambda: st.session_state.update({REQ: None}), False),
            ("ops_savews", "check", "Save workspace", lambda: _save_workspace(w), not w.can_edit),
            ("ops_saveview", "plus", "Save view", lambda: st.session_state.update({K + "show_saveview": True}), not w.can_edit),
            ("ops_fav", "star", "Favorite this visualization",
             lambda: _toggle_favorite(w.shell, "viz", st.session_state.get(VIZ) or ""), not st.session_state.get(VIZ)),
            ("ops_compare", "layers", "Compare (Phase 16B)", lambda: _log("Quick Compare arrives in Phase 16B."), True),
            ("ops_full", "grid", "Toggle fullscreen stage", lambda: _toggle(FULL), False),
        ]
        for col, (key, ic, tip, cb, disabled) in zip(cols, specs):
            col.button("", key=key, help=tip, on_click=cb, disabled=disabled, use_container_width=True)
        with cols[8]:
            st.button("", key="ops_home", help="Home dashboard",
                      on_click=lambda: st.session_state.update({MODE: "home"}), use_container_width=True)
        with cols[9]:
            st.session_state[RATIO] = st.selectbox(
                "layout", list(_RATIOS), index=list(_RATIOS).index(st.session_state.get(RATIO, "Balanced")),
                key="ops_ratio_sel", label_visibility="collapsed")
        with cols[10]:
            co = _collapse()
            if st.button("", key="ops_tgl_left", help="Toggle left panel", use_container_width=True):
                co["left"] = not co["left"]; st.rerun()
        with cols[11]:
            if st.button("", key="ops_tgl_right", help="Toggle right panel", use_container_width=True):
                co["right"] = not co["right"]; st.rerun()
    st.markdown(icon_css([("ops_undo", "chevron-left"), ("ops_redo", "chevron-right"),
                          ("ops_refresh", "refresh"), ("ops_savews", "check"), ("ops_saveview", "plus"),
                          ("ops_fav", "star"), ("ops_compare", "layers"), ("ops_full", "grid"),
                          ("ops_home", "dashboard"), ("ops_tgl_left", "sliders"),
                          ("ops_tgl_right", "sliders")]),
                unsafe_allow_html=True)


def _toggle(flag: str) -> None:
    st.session_state[flag] = not st.session_state.get(flag, False)


def _history_step(delta: int) -> None:
    hist = _ss(HIST, list)
    if not hist:
        return
    cur = st.session_state.get(K + "hist_pos", len(hist) - 1)
    nxt = max(0, min(len(hist) - 1, cur + delta))
    st.session_state[K + "hist_pos"] = nxt
    _restore(hist[nxt]["meta"])


# ================================================================ LEFT panels
def _panel_datasets(w: Studio) -> None:
    st.markdown('<div class="ops-h">Datasets</div>', unsafe_allow_html=True)
    if w.dataset is None:
        if C.render_empty_state("No active dataset", "Activate one in the Data Hub to start.",
                                icon_name="datasets", action_label="Open Data Hub", key="ops_ds_dh"):
            w.shell.goto("data_hub")
        return
    rows = len(w.frame) if w.frame is not None else 0
    st.markdown(f'<div class="ops-ds"><b>{_html.escape(str(w.dataset.name))}</b>'
                f'<span>{rows:,} events</span></div>', unsafe_allow_html=True)
    if st.button("Switch dataset", key="ops_ds_switch", use_container_width=True):
        w.shell.goto("data_hub")


def _panel_filters(w: Studio) -> None:
    st.markdown('<div class="ops-h">Filters</div>', unsafe_allow_html=True)
    if w.frame is None or getattr(w.frame, "empty", True):
        C.render_empty_state("No events", "Filters appear once a dataset is active.", icon_name="sliders")
        return
    sel = _selections()
    frame = w.frame

    def opts(col):
        return sorted(str(v) for v in frame[col].astype(str).unique() if str(v).strip()) \
            if col in frame.columns else []

    for fdef in w.engine.filters:
        fid, label, kind, col = fdef["id"], fdef["label"], fdef["kind"], fdef["column"]
        key = f"ops_f_{fid}"
        if kind == "select":
            options = ["All", *opts(col)]
            cur = sel.get(fid, "All")
            sel[fid] = st.selectbox(label, options, index=options.index(cur) if cur in options else 0, key=key)
        elif kind == "multiselect":
            # apply_filters matches event_type/phase case-insensitively (str.lower().isin)
            # but players EXACTLY (isin). Mirror run_app: lowercase the former's options,
            # keep players in their real casing — else a lowercased pick never matches.
            lower = fid in ("event_types", "phases")
            if col in frame.columns:
                vals = frame[col].astype(str)
                options = sorted({(str(v).lower() if lower else str(v)) for v in vals})
            else:
                options = []
            options = [o for o in options if o.strip()]
            sel[fid] = st.multiselect(label, options,
                                      default=[o for o in sel.get(fid, []) if o in options], key=key)
        elif kind == "range":
            sel[fid] = tuple(st.slider(label, 0, 120, tuple(sel.get(fid, (0, 95))), key=key))
        elif kind == "bool":
            sel[fid] = st.checkbox(label, value=bool(sel.get(fid, False)), key=key)
    c1, c2 = st.columns(2)
    if c1.button("Reset", key="ops_f_reset", use_container_width=True):
        st.session_state[SEL] = {}
        for fdef in w.engine.filters:
            st.session_state.pop(f"ops_f_{fdef['id']}", None)
        st.rerun()
    n_active = _active_filter_count(sel)
    c2.caption(f"{n_active} active")


def _active_filter_count(sel: dict) -> int:
    n = 0
    n += sum(1 for k in ("team", "opponent", "match") if sel.get(k, "All") not in ("All", None))
    n += sum(1 for k in ("event_types", "phases", "players") if sel.get(k))
    if sel.get("only_success"):
        n += 1
    if tuple(sel.get("minute_range", (0, 95))) != (0, 95):
        n += 1
    return n


def _panel_saved_views(w: Studio) -> None:
    st.markdown('<div class="ops-h">Saved Views</div>', unsafe_allow_html=True)
    if st.session_state.pop(K + "show_saveview", False):
        st.session_state[K + "_sv_open"] = True
    try:
        views = w.shell.wm.list_presets(w.shell.user, kind=VIEW_KIND)
    except Exception:
        views = []
    if w.can_edit:
        with st.expander("Save current as view", expanded=st.session_state.pop(K + "_sv_open", False)):
            name = st.text_input("View name", key="ops_sv_name", placeholder="e.g. Home final third",
                                 label_visibility="collapsed")
            if st.button("Save view", key="ops_sv_save", use_container_width=True) and name.strip():
                _save_view(w, name.strip())
                st.rerun()
    if not views:
        C.render_empty_state("No saved views", "Save the current visualization, filters and theme "
                             "as a reusable view.", icon_name="star")
        return
    favs = _favorites(w.shell)["view"]
    for pr in views:
        cols = st.columns([5, 1, 1])
        star = "★ " if pr.id in favs else ""
        if cols[0].button(f"{star}{pr.name}", key=f"ops_sv_open_{pr.id}", use_container_width=True):
            _apply_view(pr.document)
            st.session_state[VIEW] = pr.id
            _push_recent_view(w.shell, pr.id)
            st.rerun()
        if cols[1].button("☆", key=f"ops_sv_fav_{pr.id}", help="Favorite"):
            _toggle_favorite(w.shell, "view", pr.id); st.rerun()
        if w.can_edit and cols[2].button("🗑", key=f"ops_sv_del_{pr.id}", help="Delete"):
            try:
                w.shell.wm.delete_preset(w.shell.user, pr.id)
            except Exception:
                pass
            st.rerun()
    if w.can_edit and views:
        with st.expander("Manage (rename / duplicate)"):
            names = {p.id: p.name for p in views}
            pid = st.selectbox("View", list(names), format_func=lambda i: names[i], key="ops_sv_mng")
            nn = st.text_input("New name", key="ops_sv_rename")
            b1, b2 = st.columns(2)
            if b1.button("Rename", key="ops_sv_rn", use_container_width=True) and nn.strip():
                src = next((p for p in views if p.id == pid), None)
                if src:
                    w.shell.wm.save_preset(w.shell.user, kind=VIEW_KIND, name=nn.strip(),
                                           document=src.document, preset_id=pid)
                    st.rerun()
            if b2.button("Duplicate", key="ops_sv_dup", use_container_width=True):
                src = next((p for p in views if p.id == pid), None)
                if src:
                    w.shell.wm.save_preset(w.shell.user, kind=VIEW_KIND, name=f"{src.name} (copy)",
                                           document=src.document)
                    st.rerun()


def _panel_favorites(w: Studio) -> None:
    st.markdown('<div class="ops-h">Favorites</div>', unsafe_allow_html=True)
    fav = _favorites(w.shell)
    viz_favs = [v for v in fav["viz"] if v in w.engine.viz_registry]
    if not viz_favs:
        C.render_empty_state("No favorites yet", "Star a visualization to pin it here.", icon_name="star")
        return
    for v in viz_favs[:12]:
        if st.button(v, key=f"ops_favopen_{v}", use_container_width=True):
            st.session_state[VIZ] = v
            st.rerun()


# ================================================================ CENTER: stage
def _panel_stage(w: Studio) -> None:
    viz = st.session_state.get(VIZ)
    if not viz:
        C.render_empty_state("Choose a visualization", "Pick a chart in the Properties panel "
                             "(right), set filters, then Render.", icon_name="analysis")
        return
    if w.render_frame is None or getattr(w.render_frame, "empty", True):
        C.render_alert("No events match the current filters. Adjust or Reset filters (left).", "info")
        return
    cache = _ss(CACHE, dict)
    sig = w.signature
    rendered = st.session_state.get(REQ) == sig and sig in cache
    left, right = st.columns([6, 1], vertical_alignment="center")
    left.markdown(f'<div class="ops-stage-title">{_html.escape(str(viz))}</div>', unsafe_allow_html=True)
    if right.button("Render", key="ops_render", type="primary", use_container_width=True):
        _render_current(w)
        rendered = True
    if not rendered:
        if sig in cache:
            st.image(cache[sig]["png"], use_container_width=True)
            st.caption("Cached — adjust options then Render to update.")
        else:
            C.render_empty_state("Ready to render", "Click Render to draw this visualization with the "
                                 "current filters and options.", icon_name="analysis")
        return
    st.image(cache[sig]["png"], use_container_width=True)
    st.caption("Rendered with the Open Play engine — identical to Opponent Analysis for the same options.")


def _render_current(w: Studio) -> None:
    import matplotlib.pyplot as plt
    cache = _ss(CACHE, dict)
    sig = w.signature
    viz = st.session_state.get(VIZ)
    if sig in cache:                                    # reuse — no regeneration
        st.session_state[REQ] = sig
        _push_history(w, sig)
        return
    import time
    t0 = time.perf_counter()
    try:
        fig = w.engine.render(viz, w.render_frame, w.ctx)
        png = w.engine.export(fig, "png", 150, False)
        plt.close(fig)
    except Exception as exc:
        _log(f"Render error: {exc}")
        st.error(f"Could not render '{viz}': {exc}")
        return
    st.session_state[K + "render_ms"] = int((time.perf_counter() - t0) * 1000)
    cache[sig] = {"png": png, "meta": _current_meta()}
    if len(cache) > 40:                                 # cap session cache
        for k in list(cache)[:len(cache) - 40]:
            cache.pop(k, None)
    st.session_state[REQ] = sig
    _push_history(w, sig)
    _log(f"Rendered {viz}.")


def _current_meta() -> dict:
    return {"viz": st.session_state.get(VIZ), "theme": st.session_state.get(THEME),
            "category": st.session_state.get(CAT, "All"), "dataset": st.session_state.get(K + "ds_name", ""),
            "selections": dict(_selections()), "controls": dict(_controls())}


def _push_history(w: Studio, sig: str) -> None:
    hist = _ss(HIST, list)
    if hist and hist[-1].get("sig") == sig:
        return
    import datetime as _dt
    hist.append({"sig": sig, "meta": _current_meta(),
                 "ts": _dt.datetime.now().strftime("%H:%M:%S")})
    del hist[:-30]
    st.session_state[K + "hist_pos"] = len(hist) - 1


# ================================================================ RIGHT: properties/inspector/export
def _sel(label, options, current, key, help=None):
    """Selectbox that tolerates an out-of-range current value."""
    idx = options.index(current) if current in options else 0
    return st.selectbox(label, options, index=idx, key=key, help=help)


def _panel_inspector(w: Studio) -> None:
    """The professional Inspector: every run_app option, grouped. Defaults are read from
    the engine's single-source default_ctx / PitchSpec, so an untouched control produces
    the exact run_app value (byte-identical). Full feature parity with Opponent Analysis."""
    st.markdown('<div class="ops-h">Inspector</div>', unsafe_allow_html=True)
    eng, ctl = w.engine, _controls()
    d = eng.default_ctx(w.vt, w.spec)            # single source of ctx defaults
    sd = eng.pitch_spec_cls()                     # single source of spec defaults
    md = eng.metadata

    def grp(name):
        return ctl.setdefault(name, {})

    # ---- Visualization ------------------------------------------------------------
    with st.expander("Visualization", expanded=True):
        cats = ["All", *eng.categories()]
        st.session_state[CAT] = _sel("Category", cats, st.session_state.get(CAT, "All"), "ops_cat")
        names = eng.viz_names(st.session_state[CAT])
        if not names:
            C.render_alert("No visualizations in this category.", "info")
        else:
            st.session_state[VIZ] = _sel("Visualization", names, st.session_state.get(VIZ), "ops_viz")
        themes = list(md.get("themes", {})) + list(md.get("club_custom_names", []))
        st.session_state[THEME] = _sel("Theme", themes, st.session_state.get(THEME), "ops_theme")
        tname = st.session_state[THEME]
        tc = grp("theme_custom")
        if tname == "Club Theme":
            c1, c2 = st.columns(2)
            tc["primary"] = c1.color_picker("Primary", tc.get("primary", "#B00020"), key="ops_club_p")
            tc["secondary"] = c2.color_picker("Secondary", tc.get("secondary", "#FFD700"), key="ops_club_s")
            tc["club_dark"] = st.checkbox("Dark background", value=tc.get("club_dark", True), key="ops_club_d")
        elif tname == "Custom Theme":
            c1, c2 = st.columns(2)
            for lbl, k, col in [("Background", "bg", c1), ("Pitch", "pitch", c2), ("Pitch lines", "line", c1),
                                ("Text", "text", c2), ("Accent", "accent", c1), ("Accent 2", "accent2", c2)]:
                tc[k] = col.color_picker(lbl, tc.get(k, w.vt.get(k, "#ffffff")), key=f"ops_cust_{k}")
            tc["panel"] = st.color_picker("Panel / cards", tc.get("panel", w.vt.get("panel", "#ffffff")), key="ops_cust_panel")
        ctl["font"] = _sel("Font", ["Theme default", "DejaVu Sans", "DejaVu Serif", "Monospace"],
                           ctl.get("font", "Theme default"), "ops_font")
        ctl["title"] = st.text_input("Title", value=ctl.get("title", ""), key="ops_title",
                                     placeholder=st.session_state.get(VIZ, ""))
        ctl["show_title"] = st.checkbox("Show title", value=ctl.get("show_title", d["show_title"]), key="ops_showtitle")
        c1, c2, c3 = st.columns(3)
        ctl["title_size"] = c1.slider("Title", 12, 32, int(ctl.get("title_size", d["title_size"])), key="ops_tsize")
        ctl["label_size"] = c2.slider("Labels", 7, 18, int(ctl.get("label_size", d["label_size"])), key="ops_lsize")
        ctl["legend_size"] = c3.slider("Legend", 7, 16, int(ctl.get("legend_size", d["legend_size"])), key="ops_lgsize")

    # ---- Pitch --------------------------------------------------------------------
    with st.expander("Pitch", expanded=True):
        p = grp("pitch")
        p["orientation"] = _sel("Orientation", ["Horizontal", "Vertical", "Auto"],
                                p.get("orientation", sd.orientation), "ops_orient")
        views = md.get("pitch_views", ["Full Pitch"])
        p["view"] = _sel("View", views, p.get("view", sd.view), "ops_view")
        if p["view"] == "Custom Crop":
            cx = st.slider("Crop length (x)", 0, 100, tuple(p.get("crop_x", (50, 100))), key="ops_cropx")
            cy = st.slider("Crop width (y)", 0, 100, tuple(p.get("crop_y", (0, 100))), key="ops_cropy")
            p["crop_x"], p["crop_y"] = tuple(cx), tuple(cy)
            p["custom_crop"] = (float(cx[0]), float(cx[1]), float(cy[0]), float(cy[1]))
        c1, c2, c3 = st.columns(3)
        p["mirror"] = c1.checkbox("Mirror X", value=p.get("mirror", sd.mirror), key="ops_mirror")
        p["flip_y"] = c2.checkbox("Flip Y", value=p.get("flip_y", sd.flip_y), key="ops_flipy")
        p["stripes"] = c3.checkbox("Stripes", value=p.get("stripes", sd.stripes), key="ops_stripes")

    # ---- Markers ------------------------------------------------------------------
    with st.expander("Markers", expanded=True):
        m = grp("marker")
        shapes = list(md.get("marker_shapes", {"Circle": "o"}))
        m["shape"] = _sel("Shape", shapes, m.get("shape", d["marker"]["shape"]), "ops_mshape")
        c1, c2 = st.columns(2)
        m["size"] = c1.slider("Size", 25, 320, int(m.get("size", d["marker"]["size"])), key="ops_msize")
        m["alpha"] = c2.slider("Opacity", 0.2, 1.0, float(m.get("alpha", d["marker"]["alpha"])), key="ops_malpha")
        with st.expander("More marker options"):
            m["edge_width"] = st.slider("Border width", 0.0, 4.0, float(m.get("edge_width", d["marker"]["edge_width"])), key="ops_medgew")
            m["edge_color"] = st.color_picker("Border color", m.get("edge_color", d["marker"]["edge_color"]), key="ops_medgec")
            m["rotation"] = st.slider("Rotation", 0, 315, int(m.get("rotation", d["marker"]["rotation"])), step=45, key="ops_mrot")
            m["jitter"] = st.slider("Jitter", 0.0, 2.0, float(m.get("jitter", d["marker"]["jitter"])), key="ops_mjit")
            m["zorder"] = st.slider("Z-order", 3, 12, int(m.get("zorder", d["marker"]["zorder"])), key="ops_mz")
            m["shadow"] = st.checkbox("Shadow", value=m.get("shadow", d["marker"]["shadow"]), key="ops_msh")
            m["glow"] = st.checkbox("Glow", value=m.get("glow", d["marker"]["glow"]), key="ops_mgl")
            m["glow_color"] = st.color_picker("Glow color", m.get("glow_color", d["marker"]["glow_color"]), key="ops_mglc")

    # ---- Arrows -------------------------------------------------------------------
    with st.expander("Arrows", expanded=True):
        a = grp("arrow")
        kinds = ["Straight", "Curved", "Bezier", "Dashed", "Dotted", "Double Arrow", "Comet", "Gradient Comet"]
        a["kind"] = _sel("Style", kinds, a.get("kind", d["arrow"]["kind"]), "ops_akind")
        c1, c2 = st.columns(2)
        a["width"] = c1.slider("Width", 0.5, 6.0, float(a.get("width", d["arrow"]["width"])), key="ops_awidth")
        a["head"] = c2.slider("Head size", 4, 26, int(a.get("head", d["arrow"]["head"])), key="ops_ahead")
        a["curvature"] = st.slider("Curvature", 0.02, 0.6, float(a.get("curvature", d["arrow"]["curvature"])), key="ops_acurv")
        with st.expander("More arrow options"):
            a["alpha"] = st.slider("Opacity", 0.2, 1.0, float(a.get("alpha", d["arrow"]["alpha"])), key="ops_aalpha")
            a["linecap"] = _sel("Line cap", ["round", "butt", "projecting"], a.get("linecap", d["arrow"]["linecap"]), "ops_acap")
            a["shadow"] = st.checkbox("Shadow", value=a.get("shadow", d["arrow"]["shadow"]), key="ops_ash")
            a["glow"] = st.checkbox("Glow", value=a.get("glow", d["arrow"]["glow"]), key="ops_agl")
            a["cmap"] = _sel("Gradient colormap", md.get("heat_cmaps", ["viridis"]),
                             a.get("cmap", d["arrow"]["cmap"]), "ops_acmap")

    # ---- Labels -------------------------------------------------------------------
    with st.expander("Labels", expanded=False):
        lb = grp("labels")
        c1, c2 = st.columns(2)
        lb["show"] = c1.checkbox("Enable labels", value=lb.get("show", d["labels"]["show"]), key="ops_lbshow")
        lb["show_players"] = c2.checkbox("Player labels", value=lb.get("show_players", d["labels"]["show_players"]), key="ops_lbpl")
        lb["smart"] = c1.checkbox("Smart positioning", value=lb.get("smart", d["labels"]["smart"]), key="ops_lbsmart")
        lb["hide_overlapping"] = c2.checkbox("Hide overlapping", value=lb.get("hide_overlapping", d["labels"]["hide_overlapping"]), key="ops_lbhide")
        lb["halo"] = c1.checkbox("Halo", value=lb.get("halo", d["labels"]["halo"]), key="ops_lbhalo")
        lb["box"] = c2.checkbox("Background box", value=lb.get("box", d["labels"]["box"]), key="ops_lbbox")
        lb["leader_lines"] = st.checkbox("Leader lines", value=lb.get("leader_lines", d["labels"]["leader_lines"]), key="ops_lblead")
        lb["size"] = st.slider("Font size", 6, 16, int(lb.get("size", d["labels"]["size"])), key="ops_lbsize")
        lb["offset"] = st.slider("Offset", 0.5, 5.0, float(lb.get("offset", d["labels"]["offset"])), key="ops_lboff")
        lb["rotation"] = st.slider("Rotation", 0, 90, int(lb.get("rotation", d["labels"]["rotation"])), key="ops_lbrot")
        lb["max_labels"] = st.slider("Max labels (0 = all)", 0, 60, int(lb.get("max_labels", d["labels"]["max_labels"])), key="ops_lbmax")

    # ---- Heatmap ------------------------------------------------------------------
    with st.expander("Heatmap", expanded=True):
        h = grp("heat")
        h["type"] = _sel("Type", md.get("heat_types", ["Gaussian KDE"]), h.get("type", d["heat"]["type"]), "ops_htype")
        h["cmap"] = _sel("Palette", md.get("heat_cmaps", ["Greens"]), h.get("cmap", d["heat"]["cmap"]), "ops_hcmap")
        h["alpha"] = st.slider("Alpha", 0.15, 0.95, float(h.get("alpha", d["heat"]["alpha"])), key="ops_halpha")
        with st.expander("More heatmap options"):
            h["preset"] = _sel("Data preset", md.get("heat_presets", ["All selected events"]),
                               h.get("preset", d["heat"]["preset"]), "ops_hpreset")
            h["bandwidth"] = st.slider("Radius / bandwidth (KDE)", 0.5, 8.0, float(h.get("bandwidth", d["heat"]["bandwidth"])), key="ops_hbw")
            h["levels"] = st.slider("Contour levels", 4, 24, int(h.get("levels", d["heat"]["levels"])), key="ops_hlev")
            h["bins"] = st.slider("Histogram bins", 5, 30, int(h.get("bins", d["heat"]["bins"])), key="ops_hbins")
            h["gridsize"] = st.slider("Hexbin grid", 8, 40, int(h.get("gridsize", d["heat"]["gridsize"])), key="ops_hgrid")
            h["cell_size"] = st.slider("Cell size", 5, 25, int(h.get("cell_size", d["heat"]["cell_size"])), key="ops_hcell")
            h["interpolation"] = _sel("Interpolation", ["bilinear", "nearest", "bicubic", "gaussian"],
                                      h.get("interpolation", d["heat"]["interpolation"]), "ops_hinterp")
            h["normalization"] = _sel("Normalization", ["Count", "Percent"], h.get("normalization", d["heat"]["normalization"]), "ops_hnorm")
            h["threshold"] = st.slider("Threshold percentile", 0, 90, int(h.get("threshold", d["heat"]["threshold"])), key="ops_hthr")
            h["percentile_scale"] = st.checkbox("Percentile scale", value=h.get("percentile_scale", d["heat"]["percentile_scale"]), key="ops_hpctl")
            h["log_scale"] = st.checkbox("Log scale", value=h.get("log_scale", d["heat"]["log_scale"]), key="ops_hlog")
            h["cell_labels"] = st.checkbox("Cell count labels", value=h.get("cell_labels", d["heat"]["cell_labels"]), key="ops_hcl")

    # ---- Legend -------------------------------------------------------------------
    with st.expander("Legend", expanded=False):
        lg = grp("legend")
        lg["position"] = _sel("Position", md.get("legend_positions", ["Bottom"]), lg.get("position", d["legend"]["position"]), "ops_lgpos")
        c1, c2 = st.columns(2)
        lg["show"] = c1.checkbox("Show legend", value=lg.get("show", d["legend"]["show"]), key="ops_lgshow")
        lg["frame"] = c2.checkbox("Frame", value=lg.get("frame", d["legend"]["frame"]), key="ops_lgframe")
        lg["orientation"] = _sel("Orientation", ["Horizontal", "Vertical"], lg.get("orientation", d["legend"]["orientation"]), "ops_lgor")
        with st.expander("Legend items"):
            lg["title"] = st.text_input("Legend title", value=lg.get("title", d["legend"]["title"]), key="ops_lgtitle")
            lg["renames"] = st.text_input("Rename (old=new; …)", value=lg.get("renames", d["legend"]["renames"]), key="ops_lgren")
            lg["hide"] = st.text_input("Hide (comma-separated)", value=lg.get("hide", d["legend"]["hide"]), key="ops_lghide")
            lg["order"] = st.text_input("Order (comma-separated)", value=lg.get("order", d["legend"]["order"]), key="ops_lgord")

    # ---- Advanced: thirds, colors, chart-data (aux) -------------------------------
    with st.expander("Advanced — Thirds", expanded=False):
        th = grp("thirds")
        modes = ["None", "Length thirds (lines)", "Width lanes (lines)", "Length thirds + lanes",
                 "Highlight final third", "Highlight middle third", "Highlight defensive third",
                 "Highlight attacking half", "Highlight defensive half", "Custom positions"]
        th["thirds_mode"] = _sel("Mode", modes, th.get("thirds_mode", sd.thirds_mode), "ops_thmode")
        if th["thirds_mode"] == "Custom positions":
            th["thirds_positions"] = st.text_input("Positions (0-100)", value=th.get("thirds_positions", "25, 50, 75"), key="ops_thpos")
        th["thirds_color"] = st.color_picker("Color", th.get("thirds_color", w.vt.get("warning", "#E3B341")), key="ops_thcol")
        th["thirds_width"] = st.slider("Line width", 0.5, 4.0, float(th.get("thirds_width", sd.thirds_width)), key="ops_thw")
        th["thirds_alpha"] = st.slider("Opacity", 0.1, 1.0, float(th.get("thirds_alpha", sd.thirds_alpha)), key="ops_tha")
        th["thirds_labels"] = st.checkbox("Show labels", value=th.get("thirds_labels", sd.thirds_labels), key="ops_thlab")
        th["lane_lines"] = st.checkbox("Always show lanes", value=th.get("lane_lines", sd.lane_lines), key="ops_thlane")

    with st.expander("Advanced — Colors", expanded=False):
        co = grp("colors")
        pairs = [("Successful arrow", "arrow"), ("Unsuccessful", "unsuccess"), ("Start event", "start"),
                 ("End event", "end"), ("Shot (no goal)", "shot"), ("Goal", "goal"), ("Zone", "zone"),
                 ("Bar", "bar"), ("Line", "line"), ("Trend", "trend"), ("Carry", "carry"), ("Cross", "cross")]
        cc = st.columns(2)
        for i, (lbl, k) in enumerate(pairs):
            co[k] = cc[i % 2].color_picker(lbl, co.get(k, d["colors"][k]), key=f"ops_col_{k}")
        ax = grp("aux")
        ax["line_width"] = st.slider("Line chart width", 1.0, 5.0, float(ax.get("line_width", d["aux"]["line_width"])), key="ops_linew")

    with st.expander("Advanced — Chart data", expanded=False):
        ax = grp("aux")
        ax["top_n"] = st.slider("Top N players", 3, 25, int(ax.get("top_n", d["aux"]["top_n"])), key="ops_topn")
        ax["zone_mode"] = _sel("Zone percentage mode", ["Pitch Thirds", "Lanes"], ax.get("zone_mode", d["aux"]["zone_mode"]), "ops_zmode")
        ax["start_end_event"] = _sel("Start/End event", ["pass", "carry", "cross", "dribble"], ax.get("start_end_event", d["aux"]["start_end_event"]), "ops_seev")
        events = sorted({str(v).lower() for v in w.frame["event_type"].astype(str)}) if (w.frame is not None and "event_type" in w.frame) else []
        ax["timeline_focus"] = _sel("Timeline event", ["All", *events], ax.get("timeline_focus", d["aux"]["timeline_focus"]), "ops_tlf")
        ax["trend_metric"] = _sel("Trend metric", ["All Events", "Shots", "Final third entries", "Box entries"], ax.get("trend_metric", d["aux"]["trend_metric"]), "ops_trend")
        ax["sequence_mode"] = _sel("Sequence mode", ["Specific sequence", "Latest shot sequence", "Latest goal sequence", "Longest sequence"], ax.get("sequence_mode", d["aux"]["sequence_mode"]), "ops_seqm")
        ax["show_sequence_numbers"] = st.checkbox("Sequence order numbers", value=ax.get("show_sequence_numbers", d["aux"]["show_sequence_numbers"]), key="ops_seqn")

    st.caption("Every option mirrors Opponent Analysis; untouched controls keep the engine "
               "default, so rendered output is byte-identical.")


def _panel_export(w: Studio) -> None:
    st.markdown('<div class="ops-h">Export</div>', unsafe_allow_html=True)
    cache = _ss(CACHE, dict)
    sig = w.signature
    if sig not in cache:
        C.render_empty_state("Nothing to export", "Render a visualization first, then export it as "
                             "PNG, SVG or PDF.", icon_name="download")
        return
    st.image(cache[sig]["png"], use_container_width=True)
    safe = (st.session_state.get(VIZ) or "chart").lower().replace(" ", "_").replace("/", "_")
    # professional export drawer — all via the existing engine export (fig_to_bytes)
    formats = [("PNG", "png", 240, False), ("SVG", "svg", 240, False), ("PDF", "pdf", 240, False),
               ("PNG Hi-Res", "png", 400, False), ("PNG Transparent", "png", 240, True)]
    for i in range(0, len(formats), 3):
        cols = st.columns(3)
        for col, (label, fmt, dpi, transp) in zip(cols, formats[i:i + 3]):
            try:
                data = _export_current(w, fmt, dpi=dpi, transparent=transp)
                mime = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}[fmt]
                suffix = label.lower().replace(" ", "_")
                col.download_button(label, data=data, file_name=f"{safe}_{suffix}.{fmt}", mime=mime,
                                    key=f"ops_exp_{suffix}", use_container_width=True)
            except Exception:
                col.caption(f"{label} n/a")
    st.button("Copy to clipboard", key="ops_send_clip", use_container_width=True, disabled=True,
              help="Copy to clipboard — future placeholder")
    st.divider()
    st.caption("Add to report (reuses the report pipeline)")
    _report_actions(w, cache[sig]["png"])


def _report_actions(w: Studio, png: bytes) -> None:
    """Add the rendered chart to a report via the EXISTING report pipeline (upload_image +
    image_block) — no duplicated export. Degrades to a note if the reports engine is absent."""
    reports = getattr(getattr(w.shell, "platform", None), "reports", None)
    title = st.session_state.get(VIZ) or "Open Play chart"
    if reports is None:
        C.render_alert("Report integration needs the Reports engine (open the Reports page once "
                       "to initialise it).", "info")
    else:
        from fap.reports import image_block, add_block
        c1, c2 = st.columns(2)
        # --- Add to a NEW report ---
        if c1.button("Add to Report", key="ops_rep_new", use_container_width=True):
            try:
                rec = reports.create(w.shell.user, template="professional",
                                     df=w.filtered, title=f"Open Play — {title}",
                                     workspace_id=getattr(w.shell, "workspace_id", None),
                                     dataset_id=getattr(w.dataset, "id", None))
                _attach_png_to_report(reports, w.shell.user, rec.id, png, title, image_block, add_block)
                _log(f"Created report '{rec.title}' with {title}.")
                st.toast("Added to a new report")
            except Exception as exc:
                _log(f"Add to Report failed: {exc}")
                st.error(f"Could not create report: {exc}")
        # --- Add to an EXISTING report ---
        try:
            existing = reports.list(w.shell.user, workspace_id=getattr(w.shell, "workspace_id", None))
        except Exception:
            existing = []
        if existing:
            names = {r.id: r.title for r in existing}
            rid = c2.selectbox("Existing report", list(names), format_func=lambda i: names[i],
                               key="ops_rep_pick", label_visibility="collapsed")
            if c2.button("Add to Existing", key="ops_rep_add", use_container_width=True):
                try:
                    _attach_png_to_report(reports, w.shell.user, rid, png, title, image_block, add_block)
                    _log(f"Added {title} to '{names[rid]}'.")
                    st.toast("Added to existing report")
                except Exception as exc:
                    st.error(f"Could not add to report: {exc}")
        else:
            c2.caption("No existing reports yet.")
    # --- Scouting report (best-effort: needs the scouting service + a player) ---
    scouting = getattr(getattr(w.shell, "platform", None), "scouting", None)
    if scouting is not None:
        with st.expander("Add to Scouting Report"):
            try:
                players = scouting.list_players(w.shell.user)
            except Exception:
                players = []
            if not players:
                C.render_empty_state("No scouting players", "Create a scouting player first.",
                                     icon_name="players")
            else:
                pnames = {p.id: p.name for p in players}
                pid = st.selectbox("Player", list(pnames), format_func=lambda i: pnames[i],
                                   key="ops_scout_pick")
                if st.button("Assign chart to player", key="ops_scout_add", use_container_width=True):
                    try:
                        scouting.assign_chart(w.shell.user, pid, png, title=title,
                                              viz_id=st.session_state.get(VIZ, ""))
                        st.toast("Assigned to scouting report")
                    except Exception as exc:
                        st.error(f"Could not assign: {exc}")


def _attach_png_to_report(reports, user, report_id, png, title, image_block, add_block) -> None:
    """Upload the PNG through the report image store and append an image block."""
    img = reports.upload_image(user, png, f"openplay_{title[:24]}.png", "image/png")
    doc = reports.document(report_id)
    add_block(doc, image_block(img.id, caption=title))
    reports.save_document(user, report_id, doc)


def _export_current(w: Studio, fmt: str, *, dpi: int = 240, transparent: bool = False) -> bytes:
    """Render once on demand for the requested format (default PNG served from cache)."""
    cache = _ss(CACHE, dict)
    if fmt == "png" and dpi == 240 and not transparent and w.signature in cache:
        return cache[w.signature]["png"]
    import matplotlib.pyplot as plt
    fig = w.engine.render(st.session_state.get(VIZ), w.render_frame, w.ctx)
    try:
        return w.engine.export(fig, fmt, dpi, transparent)
    finally:
        plt.close(fig)


# ================================================================ BOTTOM panels
def _panel_history(w: Studio) -> None:
    hist = _ss(HIST, list)
    if not hist:
        C.render_empty_state("No history yet", "Every render this session is listed here to restore.",
                             icon_name="refresh"); return
    for i, item in enumerate(reversed(hist[-12:])):
        meta = item["meta"]
        nfilt = _active_filter_count(meta.get("selections") or {})
        ds = meta.get("dataset", "")
        label = (f"{item['ts']} · {meta.get('viz','')} · {meta.get('theme','')}"
                 + (f" · {ds}" if ds else "") + (f" · {nfilt} filters" if nfilt else ""))
        if st.button(label, key=f"ops_hist_{i}_{item['sig']}", use_container_width=True):
            _restore(meta)
            st.rerun()


def _panel_insights(w: Studio) -> None:
    if w.filtered is None or getattr(w.filtered, "empty", True):
        C.render_empty_state("No insights", "Insights appear once events match the filters.",
                             icon_name="analysis"); return
    try:
        for ins in w.engine.build_insights(w.filtered)[:8]:
            st.markdown(f"- {ins}")
    except Exception:
        C.render_alert("Insights unavailable for this selection.", "info")


def _panel_selection(w: Studio) -> None:
    C.render_empty_state("No selection", "Selected chart elements will show here (Phase 16B).",
                         icon_name="target")


def _panel_messages(w: Studio) -> None:
    msgs = _ss(MSG, list)
    if not msgs:
        C.render_empty_state("No messages", "Studio activity and notices appear here.", icon_name="list")
        return
    for m in reversed(msgs[-10:]):
        st.markdown(f'<div class="ops-msg">{_html.escape(m)}</div>', unsafe_allow_html=True)


# ================================================================ status bar
def _status_bar(w: Studio) -> None:
    cache = _ss(CACHE, dict)
    rows = len(w.render_frame) if w.render_frame is not None else 0
    saved = "saved" if st.session_state.get(VIEW) else "unsaved"
    cached = "hit" if w.signature in cache else "miss"
    rms = st.session_state.get(K + "render_ms")
    items = [
        (icon("datasets", 12), getattr(w.dataset, "name", "—")),
        ("Rows", f"{rows:,}"),
        ("Filters", str(_active_filter_count(_selections()))),
        ("Viz", st.session_state.get(VIZ) or "—"),
        ("Theme", st.session_state.get(THEME) or "—"),
        ("Workspace", saved),
        ("Cache", cached),
        ("Render", f"{rms} ms" if rms is not None else "—"),
        ("Saved", st.session_state.get(K + "last_save", "—")),
    ]
    chips = "".join(f'<span class="ops-sb-item"><b>{lbl}</b> {_html.escape(str(val))}</span>'
                    for lbl, val in items)
    st.markdown(f'<div class="ops-statusbar">{chips}</div>', unsafe_allow_html=True)


# ================================================================ views / restore
def _current_view_doc() -> dict:
    return {"viz": st.session_state.get(VIZ), "theme": st.session_state.get(THEME),
            "category": st.session_state.get(CAT, "All"),
            "selections": dict(_selections()), "controls": dict(_controls()),
            "layout": {"ratio": st.session_state.get(RATIO, "Balanced"), "collapse": dict(_collapse())}}


def _stamp_saved() -> None:
    import datetime as _dt
    st.session_state[K + "last_save"] = _dt.datetime.now().strftime("%H:%M:%S")


def _save_view(w: Studio, name: str) -> None:
    try:
        pr = w.shell.wm.save_preset(w.shell.user, kind=VIEW_KIND, name=name, document=_current_view_doc())
        st.session_state[VIEW] = pr.id
        _stamp_saved()
        _log(f"Saved view '{name}'.")
    except Exception as exc:
        _log(f"Save view failed: {exc}")


def _apply_view(doc: dict) -> None:
    _restore(doc)
    layout = doc.get("layout") or {}
    if layout.get("ratio") in _RATIOS:
        st.session_state[RATIO] = layout["ratio"]
    if isinstance(layout.get("collapse"), dict):
        st.session_state[COLLAPSE] = dict(layout["collapse"])


def _restore(meta: dict) -> None:
    """Restore EVERYTHING (viz, theme, category, filters, all Inspector values). Clearing
    the widget states forces every panel to re-read the restored values (else Streamlit's
    persisted widget state would overwrite them — the stale-widget trap)."""
    st.session_state[VIZ] = meta.get("viz")
    if meta.get("theme"):
        st.session_state[THEME] = meta["theme"]
    if meta.get("category"):
        st.session_state[CAT] = meta["category"]
    st.session_state[SEL] = dict(meta.get("selections") or {})
    st.session_state[CTRL] = dict(meta.get("controls") or {})
    # every Studio widget key is prefixed "ops_" (state keys use "_ops_"); drop them all
    for k in list(st.session_state):
        if k.startswith("ops_"):
            st.session_state.pop(k, None)


def _save_workspace(w: Studio) -> None:
    """Persist the whole workspace (as a special view) so it reopens where you left off."""
    try:
        w.shell.wm.autosave(w.shell.user, _current_view_doc(), scope="openplay_workspace")
        _stamp_saved()
        _log("Workspace saved.")
    except Exception as exc:
        _log(f"Workspace save failed: {exc}")


def _restore_workspace(shell) -> None:
    if st.session_state.get(K + "_ws_loaded"):
        return
    st.session_state[K + "_ws_loaded"] = True
    try:
        doc = shell.wm.load_autosave(shell.user, scope="openplay_workspace") or {}
    except Exception:
        doc = {}
    if doc.get("viz"):
        _apply_view(doc)


# ================================================================ modular panel registry
# Region -> ordered [(id, title, render_fn, phase)]. Future panels (Video, GPS, Tracking,
# AI, Reports, Tactical Board) plug in by appending here — no shell/layout changes needed.
# ``phase``: "input" panels write selections/options and run BEFORE the frame+ctx are
# prepared; "view" panels consume the prepared state and run after — so the stage always
# reflects the current selections in the SAME run (no one-rerun lag).
PANELS: dict[str, list[tuple[str, str, Callable[[Studio], None], str]]] = {
    "left": [("datasets", "Datasets", _panel_datasets, "view"),
             ("filters", "Filters", _panel_filters, "input"),
             ("views", "Saved Views", _panel_saved_views, "view"),
             ("favorites", "Favorites", _panel_favorites, "view")],
    "center": [("stage", "Stage", _panel_stage, "view")],
    "right": [("inspector", "Inspector", _panel_inspector, "input"),
              ("export", "Export", _panel_export, "view")],
    "bottom": [("history", "History", _panel_history, "view"),
               ("insights", "Insights", _panel_insights, "view"),
               ("selection", "Selection", _panel_selection, "view"),
               ("messages", "Messages", _panel_messages, "view")],
}


def _seed_defaults(w: Studio) -> None:
    """Ensure a category/viz/theme are chosen before the stage reads them (first load)."""
    st.session_state.setdefault(CAT, "All")
    if not st.session_state.get(VIZ):
        names = w.engine.viz_names(st.session_state.get(CAT, "All"))
        if names:
            st.session_state[VIZ] = names[0]
    if not st.session_state.get(THEME):
        themes = list(w.engine.metadata.get("themes", {}))
        if themes:
            st.session_state[THEME] = themes[0]


def _region_containers(col, region: str) -> dict:
    """Create each panel's container in visual order inside ``col`` (or {} if collapsed)."""
    if col is None:
        return {}
    out = {}
    with col:
        for pid, _t, _fn, _ph in PANELS.get(region, []):
            out[pid] = st.container(key=f"ops_panel_{pid}")
    return out


def _fill_region(containers: dict, region: str, phase: str, w: Studio) -> None:
    for pid, _t, fn, ph in PANELS.get(region, []):
        if ph == phase and pid in containers:
            with containers[pid]:
                fn(w)


def _render_region(region: str, w: Studio, *, phase: str | None = None, as_tabs: bool = False) -> None:
    panels = [p for p in PANELS.get(region, []) if phase is None or p[3] == phase]
    if not panels:
        return
    if as_tabs:
        tabs = st.tabs([t for _, t, _, _ in panels])
        for tab, (_pid, _title, fn, _ph) in zip(tabs, panels):
            with tab:
                fn(w)
    else:
        for pid, _title, fn, _ph in panels:
            with st.container(key=f"ops_panel_{pid}"):
                fn(w)


# ================================================================ Home Dashboard (16A.2)
# Presentation only — reads WorkspaceManager metadata + describes the active frame. No
# analytics, no engine calls beyond the read-only registry/metadata already exposed.
def _enter_workspace(*, viz: str | None = None) -> None:
    """Leave the dashboard for the workspace, optionally opening a specific visualization."""
    st.session_state[MODE] = "workspace"
    if viz:
        st.session_state[VIZ] = viz
        st.session_state[CAT] = "All"
    st.rerun()


def _uniq(frame, col) -> int:
    return int(frame[col].astype(str).replace("", None).dropna().nunique()) \
        if (frame is not None and col in getattr(frame, "columns", [])) else 0


def _pct_valid(frame, cols) -> float | None:
    if frame is None or getattr(frame, "empty", True) or not all(c in frame.columns for c in cols):
        return None
    return round(frame[cols].dropna().shape[0] / max(1, len(frame)) * 100, 1)


def _dash_card(container, icon_name: str, title: str, rows: list[tuple[str, Any]],
               empty: str | None = None) -> None:
    body = "".join(f'<div class="r"><span>{_html.escape(str(l))}</span>'
                   f'<b>{_html.escape(str(v))}</b></div>' for l, v in rows)
    if not rows and empty:
        body = f'<div class="empty">{_html.escape(empty)}</div>'
    container.markdown(
        f'<div class="ops-dash-card"><div class="hd">{icon(icon_name, 15)} '
        f'{_html.escape(title)}</div><div class="rows">{body}</div></div>', unsafe_allow_html=True)


def _suggested_charts(w: Studio) -> list[str]:
    """Suggest existing registry vizs that fit the event types present — pure name matching,
    no analytics. Returns viz names that exist in the engine registry."""
    reg = w.engine.viz_registry
    present = set()
    if w.frame is not None and "event_type" in w.frame.columns:
        present = {str(v).lower() for v in w.frame["event_type"].astype(str)}
    kw = ["overview", "heat", "touch"]                       # always-useful
    if {"pass"} & present:
        kw += ["pass"]
    if {"shot"} & present:
        kw += ["shot"]
    if {"carry", "dribble"} & present:
        kw += ["carry", "dribble"]
    if {"cross"} & present:
        kw += ["cross"]
    if {"tackle", "interception", "recovery", "clearance", "block", "duel"} & present:
        kw += ["defensive", "recovery", "press", "tackle"]
    out: list[str] = []
    for name in reg:
        low = name.lower()
        if any(k in low for k in kw) and name not in out:
            out.append(name)
        if len(out) >= 8:
            break
    return out or list(reg)[:6]


def _home_dashboard(w: Studio) -> None:
    shell, frame = w.shell, w.frame
    # ---- header ----
    hi, hbtn = st.columns([5, 2], vertical_alignment="center")
    hi.markdown(
        f'<div class="ops-dash-hero"><div class="t">Open Play Studio</div>'
        f'<div class="s">{icon("datasets", 13)} '
        f'{_html.escape(getattr(w.dataset, "name", "No active dataset"))}</div></div>',
        unsafe_allow_html=True)
    if hbtn.button("Open Workspace  ›", key="ops_home_open", type="primary",
                   use_container_width=True, disabled=w.dataset is None):
        st.session_state[MODE] = "workspace"
        st.rerun()

    if w.dataset is None:
        go = C.render_empty_state(
            "No active dataset", "Activate a dataset in the Data Hub — the Studio then opens on a "
            "professional dashboard with match info, health and suggested charts.",
            icon_name="datasets", action_label="Open Data Hub", key="ops_home_dh")
        if go:
            shell.goto("data_hub")

    # ---- row 1: dataset summary · match info · statistics ----
    r1 = st.columns(3, gap="small")
    _dash_card(r1[0], "datasets", "Current Dataset", [
        ("Events", f"{len(frame):,}" if frame is not None else "—"),
        ("Columns", len(frame.columns) if frame is not None else "—"),
        ("Matches", _uniq(frame, "match_id")),
        ("Players", _uniq(frame, "player")),
        ("Teams", _uniq(frame, "team")),
    ] if frame is not None else [])
    _dash_card(r1[1], "analysis", "Match Information", [
        ("Matches", _uniq(frame, "match_id")),
        ("Teams", _uniq(frame, "team")),
        ("Opponents", _uniq(frame, "opponent")),
        ("Competitions", _uniq(frame, "competition")),
        ("Seasons", _uniq(frame, "season")),
    ] if frame is not None else [], empty="No active dataset.")
    ev_rows: list[tuple[str, Any]] = []
    if frame is not None and "event_type" in frame.columns:
        vc = frame["event_type"].astype(str).str.lower().value_counts().head(6)
        ev_rows = [(k.title(), f"{int(v):,}") for k, v in vc.items()]
    _dash_card(r1[2], "grid", "Dataset Statistics", ev_rows, empty="No events.")

    # ---- row 2: dataset health · workspace statistics ----
    r2 = st.columns([2, 1], gap="small")
    with r2[0]:
        _dataset_health(w)
    with r2[1]:
        try:
            views = shell.wm.list_presets(shell.user, kind=VIEW_KIND)
        except Exception:
            views = []
        fav = _favorites(shell)
        _dash_card(r2[1], "layers", "Workspace Statistics", [
            ("Saved workspaces", len(views)),
            ("Favorite views", len(fav["view"])),
            ("Favorite charts", len(fav["viz"])),
            ("Renders this session", len(_ss(HIST, list))),
            ("Cached charts", len(_ss(CACHE, dict))),
        ])

    # ---- row 3: quick actions · suggested charts ----
    r3 = st.columns([1, 2], gap="small")
    with r3[0]:
        st.markdown('<div class="ops-h">Quick Actions</div>', unsafe_allow_html=True)
        if st.button("＋  New workspace", key="ops_qa_new", use_container_width=True):
            _new_workspace(); st.session_state[MODE] = "workspace"; st.rerun()
        if st.button("▦  Open workspace", key="ops_qa_open", use_container_width=True,
                     disabled=w.dataset is None):
            st.session_state[MODE] = "workspace"; st.rerun()
        if st.button("⭳  Import data", key="ops_qa_import", use_container_width=True):
            shell.goto("data_hub")
        if st.button("▤  Reports", key="ops_qa_reports", use_container_width=True):
            shell.goto("reports")
        if st.button("↻  Opponent Analysis (legacy)", key="ops_qa_legacy", use_container_width=True):
            shell.goto("opponent_analysis")
    with r3[1]:
        st.markdown('<div class="ops-h">Suggested Charts</div>', unsafe_allow_html=True)
        sugg = _suggested_charts(w) if w.dataset is not None else []
        if not sugg:
            C.render_empty_state("No suggestions yet", "Activate a dataset to see charts matched to "
                                 "your event types.", icon_name="analysis")
        else:
            cols = st.columns(2)
            for i, name in enumerate(sugg):
                if cols[i % 2].button(name, key=f"ops_sugg_{i}", use_container_width=True):
                    _enter_workspace(viz=name)

    # ---- row 4: recent workspaces · favorite views ----
    r4 = st.columns(2, gap="small")
    with r4[0]:
        st.markdown('<div class="ops-h">Recent Workspaces</div>', unsafe_allow_html=True)
        _views_list(w, _recent_view_ids(shell), "recent",
                    "No recent workspaces", "Open a saved workspace to see it here.")
    with r4[1]:
        st.markdown('<div class="ops-h">Favorite Views</div>', unsafe_allow_html=True)
        _views_list(w, _favorites(shell)["view"], "fav",
                    "No favorite views", "Star a saved view to pin it here.")


def _views_list(w: Studio, ids: list[str], tag: str, empty_title: str, empty_sub: str) -> None:
    try:
        views = {p.id: p for p in w.shell.wm.list_presets(w.shell.user, kind=VIEW_KIND)}
    except Exception:
        views = {}
    picks = [views[i] for i in ids if i in views][:6]
    if not picks:
        C.render_empty_state(empty_title, empty_sub, icon_name="star")
        return
    for pr in picks:
        doc = getattr(pr, "document", {}) or {}
        meta = f"{doc.get('viz', '')}"
        if doc.get("theme"):
            meta += f" · {doc['theme']}"
        if st.button(f"{pr.name} {meta}", key=f"ops_{tag}_{pr.id}", use_container_width=True):
            _apply_view(doc)
            st.session_state[VIEW] = pr.id
            _push_recent_view(w.shell, pr.id)
            st.session_state[MODE] = "workspace"
            st.rerun()


def _dataset_health(w: Studio) -> None:
    st.markdown('<div class="ops-h">Dataset Health</div>', unsafe_allow_html=True)
    frame = w.frame
    if frame is None or getattr(frame, "empty", True):
        C.render_empty_state("No data to check", "Health checks appear once a dataset is active.",
                             icon_name="shield")
        return
    checks: list[tuple[str, str, str]] = []

    def band(pct):
        return "good" if pct is not None and pct >= 90 else ("warn" if pct is not None and pct >= 60 else "bad")

    xy = _pct_valid(frame, ["x", "y"])
    if xy is not None:
        checks.append(("Valid X/Y coordinates", f"{xy}%", band(xy)))
    xy2 = _pct_valid(frame, ["x2", "y2"])
    if xy2 is not None:
        checks.append(("Valid end coordinates (X2/Y2)", f"{xy2}%", band(xy2)))
    if "player" in frame.columns:
        named = round(frame["player"].astype(str).str.strip().replace("nan", "").astype(bool).mean() * 100, 1)
        checks.append(("Named players", f"{named}%", band(named)))
    if "outcome" in frame.columns:
        oc = round(frame["outcome"].astype(str).str.strip().replace("nan", "").astype(bool).mean() * 100, 1)
        checks.append(("Events with outcome", f"{oc}%", band(oc)))
    required = ["team", "player", "event_type", "x", "y"]
    missing = [c for c in required if c not in frame.columns]
    checks.append(("Required columns present", "all" if not missing else ", ".join(missing),
                   "good" if not missing else "bad"))
    rows = "".join(
        f'<div class="hr"><span class="dot {b}"></span><span class="l">{_html.escape(l)}</span>'
        f'<b>{_html.escape(str(v))}</b></div>' for l, v, b in checks)
    st.markdown(f'<div class="ops-dash-card"><div class="rows">{rows}</div></div>', unsafe_allow_html=True)


def _new_workspace() -> None:
    st.session_state[SEL] = {}
    st.session_state[CTRL] = {}
    st.session_state[VIEW] = None
    for k in list(st.session_state):
        if k.startswith("ops_"):
            st.session_state.pop(k, None)


# ================================================================ page
@page_registry.register
class OpenPlayStudioPage(Page):
    info = PluginInfo(id="open_play_studio", name="Open Play Studio", category="page")
    section = "Analysis"
    icon = "analysis"
    order = 5
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        self._inject_css()
        C.render_section_title("Open Play Studio", eyebrow="Analysis", icon_name="analysis",
                               subtitle="A professional desktop workspace over the Open Play engine.")
        engine = get_engine()
        if engine is None:
            C.render_empty_state(
                "Open Play engine not connected", "The Open Play visualization engine is not "
                "available in this session. Open 'Opponent Analysis' once to initialise it, then return.",
                icon_name="analysis", action_label="Open Opponent Analysis", key="ops_no_engine") \
                and shell.goto("opponent_analysis")
            return

        can_edit = shell.user.role >= Role.PERFORMANCE_ANALYST
        w = Studio(shell=shell, engine=engine, can_edit=can_edit)
        try:
            w.dataset = shell.wm.active_dataset(shell.user)
        except Exception:
            w.dataset = None

        _restore_workspace(shell)

        # frame + theme + spec are needed by both the dashboard (stats/health/suggestions)
        # and the workspace input panels; prepare them once when a dataset is active
        if w.dataset is not None:
            _seed_defaults(w)
            _prepare_pre(w)

        # Home Dashboard is the landing view — a professional overview, one click from work
        if st.session_state.get(MODE, "home") == "home":
            _home_dashboard(w)
            return

        if w.dataset is None:
            self._toolbar_and_empty(w)
            return

        _toolbar(w)
        collapse = _collapse()
        full = st.session_state.get(FULL, False)
        rl, rc, rr = _RATIOS.get(st.session_state.get(RATIO, "Balanced"), _RATIOS["Balanced"])

        show_left = not collapse["left"] and not full
        show_right = not collapse["right"] and not full
        ratios = ([rl] if show_left else []) + [rc] + ([rr] if show_right else [])
        columns = st.columns(ratios, gap="small")
        col_left = columns[0] if show_left else None
        col_center = columns[1] if show_left else columns[0]
        col_right = columns[-1] if show_right else None

        # Pre-create each panel's container in VISUAL order, so filling them later (inputs
        # before views) keeps positions correct while fixing execution order.
        left_c = _region_containers(col_left, "left")
        center_c = _region_containers(col_center, "center")
        right_c = _region_containers(col_right, "right")

        # Phase 1 — INPUT panels (write selections/viz/options this run)
        _fill_region(left_c, "left", "input", w)
        _fill_region(right_c, "right", "input", w)

        # Prepare frames + ctx from the now-current selections (single engine, cached)
        _prepare(w)

        # Phase 2 — VIEW panels consume the prepared state (stage reflects this run)
        _fill_region(left_c, "left", "view", w)
        _fill_region(center_c, "center", "view", w)
        _fill_region(right_c, "right", "view", w)

        with st.container(key="ops_bottom"):
            _render_region("bottom", w, as_tabs=True)
        _status_bar(w)

    def _toolbar_and_empty(self, w: Studio) -> None:
        _toolbar(w)
        _panel_datasets(w)

    # ------------------------------------------------------------ styling
    def _inject_css(self) -> None:
        st.markdown("""
<style>
.st-key-ops_toolbar { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: 12px; padding: 8px 12px; margin-bottom: 10px; }
.ops-tb-title { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.ops-tb-title .chip { display:flex; width:30px; height:30px; align-items:center; justify-content:center;
  border-radius:8px; background: var(--fap-hover); color: var(--fap-primary); }
.ops-tb-title .t { font-weight: 800; font-size: 0.98rem; line-height:1.1; }
.ops-tb-title .s { font-size: 11px; color: var(--fap-text-muted); }
/* descendant selector (not '>') is deliberate: toolbar buttons carry help= tooltips, so
   Streamlit nests the <button> under stTooltipIcon/stTooltipHoverTarget — a direct-child
   selector misses them and the icon glyph (::before) never renders. */
/* Explicit app-themed background+color (not Streamlit's native button chrome): the icon
   glyph paints with currentColor, so the button MUST carry a skin background it contrasts
   with. Without this the button falls back to Streamlit's base theme — which can be light
   while the app skin is dark, leaving a light glyph on a white button (invisible). */
.st-key-ops_toolbar .stButton button, .st-key-ops_toolbar [data-testid="stDownloadButton"] button {
  min-height: 34px; color: var(--fap-text); background: var(--fap-surface);
  border: 1px solid var(--fap-border); display:flex; align-items:center; justify-content:center; }
.st-key-ops_toolbar .stButton button::before {
  content:""; display:inline-block; width:16px; height:16px; background-color: currentColor;
  -webkit-mask-repeat:no-repeat; mask-repeat:no-repeat; -webkit-mask-position:center; mask-position:center;
  -webkit-mask-size:contain; mask-size:contain; }
.st-key-ops_toolbar .stButton button:hover { color: var(--fap-primary);
  background: var(--fap-hover); border-color: var(--fap-primary); }
.ops-h { font-size: 11px; font-weight: 800; letter-spacing: .09em; text-transform: uppercase;
  color: var(--fap-text-subtle); margin: 4px 2px 8px; }
[class*="st-key-ops_panel_"] { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: 12px; padding: 10px 12px; margin-bottom: 10px; }
.ops-ds { display:flex; flex-direction:column; gap:2px; padding:6px 0; }
.ops-ds span { font-size: 12px; color: var(--fap-text-muted); }
.ops-stage-title { font-size: 1.05rem; font-weight: 800; margin: 2px 0 6px; }
.st-key-ops_bottom { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: 12px; padding: 6px 12px; margin-top: 12px; }
.ops-statusbar { display:flex; flex-wrap:wrap; gap: 14px; margin-top: 10px; padding: 8px 12px;
  background: var(--fap-surface); border: 1px solid var(--fap-border); border-radius: 10px;
  font-size: 12px; color: var(--fap-text-muted); }
.ops-sb-item b { color: var(--fap-text); font-weight: 700; margin-right: 4px; }
.ops-msg { font-size: 12px; color: var(--fap-text-muted); padding: 3px 0;
  border-bottom: 1px dashed var(--fap-border); }
/* ---- Home Dashboard ---- */
.ops-dash-hero { display: flex; flex-direction: column; gap: 2px; }
.ops-dash-hero .t { font-size: 1.5rem; font-weight: 850; letter-spacing: -.01em; }
.ops-dash-hero .s { font-size: 12px; color: var(--fap-text-muted); display: flex; align-items: center; gap: 6px; }
.ops-dash-card { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; box-shadow: var(--fap-shadow-sm); min-height: 120px; }
.ops-dash-card .hd { display: flex; align-items: center; gap: 8px; font-weight: 750;
  font-size: 0.92rem; margin-bottom: 10px; color: var(--fap-text); }
.ops-dash-card .rows { display: flex; flex-direction: column; gap: 6px; }
.ops-dash-card .r { display: flex; justify-content: space-between; align-items: baseline;
  font-size: 13px; color: var(--fap-text-muted); }
.ops-dash-card .r b { color: var(--fap-text); font-weight: 700; font-variant-numeric: tabular-nums; }
.ops-dash-card .empty { font-size: 12px; color: var(--fap-text-subtle); }
.ops-dash-card .hr { display: flex; align-items: center; gap: 8px; font-size: 13px;
  color: var(--fap-text-muted); padding: 3px 0; }
.ops-dash-card .hr .l { flex: 1; }
.ops-dash-card .hr b { color: var(--fap-text); font-weight: 700; }
.ops-dash-card .dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; }
.ops-dash-card .dot.good { background: #2ecc71; }
.ops-dash-card .dot.warn { background: #f1c40f; }
.ops-dash-card .dot.bad { background: #e74c3c; }
</style>
""", unsafe_allow_html=True)
