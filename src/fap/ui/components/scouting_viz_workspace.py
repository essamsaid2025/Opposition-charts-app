"""Player Scouting Visualization Workspace (P4).

A professional metric-analysis workspace for a player-scouting dataset. It reuses:
the scouting service for data, ``fap.scouting.viz`` as the pure adapter,
``fap.scouting.charts`` (matplotlib + mplsoccer PyPizza) for rendering, the
existing ThemeManager for themes, and the existing ExportEngine for PNG/PDF. It
NEVER touches event data - no x/y/event_type - and never re-normalizes a
normalized dataset.

The component is a thin view: all analytics live in ``viz``/``charts``. It stores
only selections + PNG bytes in session state (never matplotlib figures), and
closes every figure after export.
"""
from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from fap.scouting import charts, viz
from fap.theme import components as C
from fap.utils.text import slugify


def _themes(shell):
    """Resolve the figure ThemeManager the same way the event viz workspace does:
    the service registry is the source of truth (``shell.platform`` in the running
    app exposes ``.services`` but not always a ``.themes`` attribute); fall back to
    the attribute for direct-construction contexts (tests)."""
    plat = getattr(shell, "platform", None)
    tm = None
    if plat is not None:
        services = getattr(plat, "services", None)
        if services is not None:
            try:
                tm = services.get("themes")
            except Exception:
                tm = None
        if tm is None:
            tm = getattr(plat, "themes", None)
    if tm is None:
        return None, []
    try:
        return tm, tm.ids()
    except Exception:
        return None, []


def _export_engine():
    from fap.visuals.export import ExportEngine
    return ExportEngine()


def _stash_render(fig, title: str, ex, *, stash_key: str, viz_id: str = "",
                  config: dict | None = None) -> None:
    """Export a freshly-rendered figure to PNG (+PDF), CLOSE it, and stash the BYTES
    in session_state. Called only on a Render click. The figure never enters session
    state - only bytes do (no DataFrame/Figure persisted anywhere)."""
    import matplotlib.pyplot as plt
    try:
        png = ex.export(fig, title, fmt="png").data
        try:
            pdf = ex.export(fig, title, fmt="pdf").data
        except Exception:
            pdf = None
    finally:
        plt.close(fig)
    st.session_state[stash_key] = {"png": png, "pdf": pdf, "title": title,
                                   "viz_id": viz_id, "config": dict(config or {})}


def _show_stash(stash_key: str, *, key: str, save: dict | None = None) -> None:
    """Render the last-rendered chart's image + download + 'Save to player' buttons
    EVERY run from the session stash. This is the fix for the nested-button bug: the
    Save button must exist on the run where it is clicked, so it cannot live inside
    the one-shot ``if st.button('Render'):`` block. 'Save to player' persists an
    immutable player asset scoped to THIS player + THIS dataset via ``save``."""
    data = st.session_state.get(stash_key)
    if not data:
        return
    png, pdf = data["png"], data.get("pdf")
    title, viz_id, config = data["title"], data.get("viz_id", ""), data.get("config", {})
    st.image(png, use_container_width=True)
    slug = slugify(title) or "chart"
    cols = st.columns(3)
    cols[0].download_button("Download PNG", png, file_name=f"{slug}.png",
                            mime="image/png", key=f"{key}_png", use_container_width=True)
    if pdf is not None:
        cols[1].download_button("Download PDF", pdf, file_name=f"{slug}.pdf",
                                mime="application/pdf", key=f"{key}_pdf",
                                use_container_width=True)
    if save is not None and cols[2].button("Save to player", key=f"{key}_assign",
                                            use_container_width=True):
        cfg = dict(config or {})
        cfg["theme"] = save.get("theme_id", "")
        cfg["viz"] = viz_id
        try:
            save["svc"].save_player_visualization(
                save["user"], save["player"].id, png, dataset_id=save["dataset_id"],
                title=title, viz_id=viz_id, scope={"player": [save["primary"]]},
                config=cfg, source_name=save["source_name"])
            if save.get("on_assign") is not None:            # keep report-embed
                save["on_assign"](png, title, viz_id)
            st.toast(f"Saved to {getattr(save['player'], 'name', 'player')} · Visual evidence updated")
            st.rerun()                                        # refresh the dossier immediately
        except Exception as exc:                              # surface the real reason
            C.render_alert(f"Could not save to the player: {exc}", "warning")


def render_scouting_viz_workspace(shell, svc, player, ctx, *, key: str,
                                  on_assign: Callable | None = None,
                                  allow_save: bool | None = None) -> None:
    """The full player-scoped viz workspace over a LINKED player-scouting dataset.

    ``ctx`` is a resolved context from ``ScoutingService.scouting_viz_context`` -
    read by dataset_id (NEVER the active dataset), with ``primary`` = the player's
    exact dataset row resolved through the P4.2.1/P4.6 matcher (so 'Mamadu Bah'
    already maps to 'S. Mamadu bah'). The player-scoped view is built for that ONE
    player (never the whole population).

    ``on_assign`` (optional) embeds the saved chart into a report on save. ``allow_save``
    explicitly toggles the "Save to player" button: when None it defaults to
    ``on_assign is not None`` (so Scouting is unchanged), so a consumer without a
    report-embed callback (e.g. First Team) can still enable Save via ``allow_save=True``.
    Both the save context and the ``svc.save_player_visualization`` contract are
    domain-neutral, so the same workspace serves Scouting and First-Team players."""
    if ctx is None or ctx.get("frame") is None or not ctx.get("primary"):
        C.render_alert("No player row resolved in the linked dataset yet.", "info")
        return
    frame = ctx["frame"]
    schema = ctx["schema"]
    population = ctx["players"]
    primary = ctx["primary"]
    tm, theme_ids = _themes(shell)
    if tm is None or not theme_ids:
        C.render_alert("Chart themes are unavailable in this session.", "warning")
        return

    # ---- controls: theme + comparison players ----
    default_theme = "opta_dark" if "opta_dark" in theme_ids else theme_ids[0]
    tcol, pcol = st.columns([1, 2])
    theme_id = tcol.selectbox("Theme", theme_ids,
                              index=theme_ids.index(st.session_state.get(f"{key}_theme", default_theme))
                              if st.session_state.get(f"{key}_theme", default_theme) in theme_ids else 0,
                              key=f"{key}_theme")
    others = [p for p in population if p != primary]
    compare = pcol.multiselect("Compare with (same dataset)", others,
                               default=st.session_state.get(f"{key}_cmp", []),
                               max_selections=3, key=f"{key}_cmp")
    theme = tm.get(theme_id)
    selected_players = [primary] + [c for c in compare if c in population]
    view = viz.build_view(frame, schema, selected_players,
                          dataset_id=ctx["id"], dataset_name=ctx["name"])
    if not view.metrics:
        C.render_alert("This dataset has no numeric scouting metrics to visualize.", "warning")
        return

    # save-context: every saved chart is a persistent player asset scoped to THIS
    # player + THIS dataset (never the active dataset, never all players).
    save_enabled = (on_assign is not None) if allow_save is None else bool(allow_save)
    save = {"user": shell.user, "svc": svc, "player": player, "dataset_id": ctx["id"],
            "source_name": ctx["name"], "primary": primary, "theme_id": theme_id,
            "on_assign": on_assign} if save_enabled else None

    # ---- player header ----
    dims = view.dimensions.get(view.primary, {})
    C.render_section_title(
        view.primary, eyebrow="Visual Analysis",
        subtitle="  ·  ".join(str(dims[k]) for k in ("team", "position", "league")
                              if dims.get(k)) or ctx["name"], icon_name="scouting")
    st.caption(f"Dataset: {view.dataset_name}  ·  {view.population} players  ·  "
               f"{len(view.metrics)} metrics  ·  values are "
               f"{'percentile/normalized (0-1)' if view.value_scale == viz.SCALE_NORMALIZED else 'raw measurements'}")

    ex = _export_engine()
    tab_explorer, tab_viz, tab_pizza, tab_pop = st.tabs(
        ["Metric Explorer", "Visualizations", "Pizza Builder", "Population Context"])
    with tab_explorer:
        _metric_explorer(view, key)
    with tab_viz:
        _viz_workspace(view, theme, frame, ex, key, save)
    with tab_pizza:
        _pizza_builder(shell, svc, view, theme, ex, key, save)
    with tab_pop:
        _population_context(view, key)


# ------------------------------------------------------------ metric explorer
def _metric_explorer(view: viz.ScoutingView, key: str) -> None:
    st.caption("Search, filter and sort every metric. Raw source values are always kept.")
    c = st.columns([2, 1, 1])
    q = c[0].text_input("Search", key=f"{key}_ex_q", placeholder="passes, xg, duels…").lower().strip()
    cats = ["All"] + view.categories()
    units = ["All"] + view.units()
    fcat = c[1].selectbox("Category", cats, key=f"{key}_ex_cat")
    funit = c[2].selectbox("Unit", units, key=f"{key}_ex_unit")
    rows = []
    for m in view.metrics:
        if q and q not in m.name.lower():
            continue
        if fcat != "All" and m.category != fcat:
            continue
        if funit != "All" and m.unit != funit:
            continue
        v = m.value(view.primary)
        pct = m.percentile(view.primary)
        rk = m.rank(view.primary)
        rows.append({
            "Metric": m.name, "Category": m.category, "Unit": m.unit,
            "Value": "—" if v is None else round(float(v), 3),
            "Percentile": "—" if pct is None else round(float(pct)),
            "Rank": "—" if rk is None else f"{rk}/{m.count}",
            "Population": m.count,
        })
    st.caption(f"{len(rows)} of {len(view.metrics)} metrics")
    st.dataframe(rows, use_container_width=True, hide_index=True)


# ------------------------------------------------------------ visualization workspace
def _viz_workspace(view: viz.ScoutingView, theme, frame, ex, key: str,
                   save) -> None:
    avail = viz.chart_availability(view, selected=st.session_state.get(f"{key}_metrics"))
    options = list(viz.CHART_TYPES)
    labels = {ct: viz.CHART_LABELS[ct] + ("" if avail[ct][0] else "  (unavailable)")
              for ct in options}
    ct = st.selectbox("Chart type", options, format_func=lambda c: labels[c], key=f"{key}_ct")
    ok, reason = avail[ct]
    if not ok:
        C.render_alert(f"{viz.CHART_LABELS[ct]} unavailable: {reason}", "info")
        return

    sources = view.sources()
    opts: dict[str, Any] = {"frame": frame}
    # per-chart metric controls
    if ct in ("bar", "percentile_bar", "radar", "lollipop", "comparison",
              "small_multiples", "heatmap", "box"):
        default = viz.suggest_pizza_metrics(view, 10) if ct in ("radar",) else sources[:12]
        picked = st.multiselect("Metrics", sources,
                                default=st.session_state.get(f"{key}_m_{ct}", default),
                                format_func=lambda s: view.metric(s).name if view.metric(s) else s,
                                key=f"{key}_m_{ct}")
        opts["metrics"] = picked or default
        st.session_state[f"{key}_metrics"] = opts["metrics"]
    elif ct == "scatter":
        cc = st.columns(2)
        xs = cc[0].selectbox("X metric", sources,
                             format_func=lambda s: view.metric(s).name, key=f"{key}_sx")
        ys = cc[1].selectbox("Y metric", sources, index=min(1, len(sources) - 1),
                             format_func=lambda s: view.metric(s).name, key=f"{key}_sy")
        opts["x"], opts["y"] = xs, ys
    elif ct in ("ranking_bar", "histogram"):
        mk = st.selectbox("Metric", sources,
                          format_func=lambda s: view.metric(s).name, key=f"{key}_single_{ct}")
        opts["metric"] = mk

    stash_key = f"{key}_vizstash_{ct}"
    if st.button("Render", type="primary", key=f"{key}_render_{ct}"):
        try:
            fig = charts.render(ct, view, theme, opts)
        except Exception as exc:                       # never crash the page
            C.render_alert(f"Could not render this chart: {exc}", "warning")
            return
        title = f"{view.primary} - {viz.CHART_LABELS[ct]}"
        cfg = {k2: opts[k2] for k2 in ("metrics", "metric", "x", "y") if k2 in opts}
        _stash_render(fig, title, ex, stash_key=stash_key,
                      viz_id=f"scouting_{ct}", config=cfg)
    # rendered image + download + 'Save to player' are drawn UNCONDITIONALLY from the
    # stash, so the Save button exists on the run where it is clicked (bugfix).
    _show_stash(stash_key, key=f"{key}_{ct}", save=save)


# ------------------------------------------------------------ pizza builder
def _pizza_builder(shell, svc, view: viz.ScoutingView, theme, ex, key: str,
                   save) -> None:
    st.caption("Manually choose the metrics on the pizza. Presets only appear when "
               "matching metrics exist; the analyst always controls the final set.")
    sources = view.sources()
    state_key = f"{key}_pizza_sel"
    if state_key not in st.session_state:
        st.session_state[state_key] = viz.suggest_pizza_metrics(view, 10)

    # presets (only those with enough metrics) + select-all / clear
    presets = viz.available_presets(view)
    pcols = st.columns(max(len(presets) + 2, 3))
    for i, preset in enumerate(presets):
        if pcols[i].button(preset, key=f"{key}_preset_{i}", use_container_width=True):
            st.session_state[state_key] = viz.preset_metrics(view, preset)[:12]
            st.rerun()
    if pcols[len(presets)].button("Select all", key=f"{key}_pz_all", use_container_width=True):
        st.session_state[state_key] = sources[:12]
        st.rerun()
    if pcols[len(presets) + 1].button("Clear", key=f"{key}_pz_clear", use_container_width=True):
        st.session_state[state_key] = []
        st.rerun()

    selected = st.multiselect(
        "Pizza metrics (search to add, drag order kept)", sources,
        default=[s for s in st.session_state[state_key] if s in sources],
        format_func=lambda s: view.metric(s).name if view.metric(s) else s,
        key=f"{key}_pz_ms")
    st.session_state[state_key] = selected

    # saved presets (reuse existing preset persistence)
    with st.expander("Saved selections"):
        sc = st.columns([2, 1])
        pname = sc[0].text_input("Name", key=f"{key}_pz_name", placeholder="e.g. CF template")
        if sc[1].button("Save selection", key=f"{key}_pz_save", use_container_width=True):
            if selected and pname.strip():
                svc.save_scouting_view_preset(shell.user, pname.strip(),
                                              {"chart": "pizza", "metrics": selected})
                st.toast(f"Saved '{pname.strip()}'")
        saved = svc.list_scouting_view_presets(shell.user)
        if saved:
            pick = st.selectbox("Load", saved, format_func=lambda p: p["name"],
                                key=f"{key}_pz_load_sel")
            if st.button("Load selection", key=f"{key}_pz_load"):
                st.session_state[state_key] = [s for s in pick["config"].get("metrics", [])
                                               if s in sources]
                st.rerun()

    data = viz.pizza_values(view, selected)
    if not data["available"]:
        C.render_alert(f"Pizza unavailable: {data['reason']}", "info")
        return
    st.caption(f"{data['note']}  ·  {len(selected)} metrics")
    stash_key = f"{key}_pzstash"
    if st.button("Render pizza", type="primary", key=f"{key}_pz_render"):
        try:
            fig = charts.pizza_chart(view, selected, theme)
        except Exception as exc:
            C.render_alert(f"Could not render the pizza: {exc}", "warning")
            return
        _stash_render(fig, f"{view.primary} - Pizza", ex, stash_key=stash_key,
                      viz_id="scouting_pizza",
                      config={"metrics": selected, "mode": data.get("mode", "")})
    # unconditional show so the Save button survives the click-triggered rerun (bugfix)
    _show_stash(stash_key, key=f"{key}_pz", save=save)


# ------------------------------------------------------------ population context
def _population_context(view: viz.ScoutingView, key: str) -> None:
    if view.population < 2:
        C.render_alert("Population context needs more than one player in the dataset.", "info")
        return
    st.caption(f"How {view.primary} ranks within the {view.population}-player dataset.")
    ranked = [(m, m.percentile(view.primary)) for m in view.metrics
              if m.percentile(view.primary) is not None]
    ranked.sort(key=lambda t: t[1], reverse=True)
    top = ranked[:6]
    bottom = ranked[-6:][::-1] if len(ranked) > 6 else []
    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Strengths** (top percentiles)")
        for m, pct in top:
            rk = m.rank(view.primary)
            st.markdown(f"{C.badge_html(f'{pct:.0f} pct', 'success')} {m.name}"
                        f" &nbsp; <span style='color:var(--fap-text-muted)'>#{rk}/{m.count}</span>",
                        unsafe_allow_html=True)
    with cols[1]:
        if bottom:
            st.markdown("**Development areas** (low percentiles)")
            for m, pct in bottom:
                rk = m.rank(view.primary)
                st.markdown(f"{C.badge_html(f'{pct:.0f} pct', 'warning')} {m.name}"
                            f" &nbsp; <span style='color:var(--fap-text-muted)'>#{rk}/{m.count}</span>",
                            unsafe_allow_html=True)


__all__ = ["render_scouting_viz_workspace"]
