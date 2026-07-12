"""Analysis page: pick any visualization plugin, auto-generated controls and
filters, framework rendering, professional export. Contains zero
per-visualization code - everything is driven by plugin declarations."""
from __future__ import annotations

from collections import defaultdict

import matplotlib.pyplot as plt
import streamlit as st

from fap.bootstrap import AppContext
from fap.core.types import RenderContext
from fap.pipeline.filters import FilterSet
from fap.state import keys
from fap.ui.components import app_header, note_box, render_controls


def render(ctx: AppContext) -> None:
    app_header("Match Analysis", "125+ professional visualizations on the canonical event model.")
    df = ctx.state.get(keys.CANONICAL_DATASET)
    if df is None or df.empty:
        note_box("No dataset loaded yet. Use <b>Import Data</b> to load any provider's "
                 "events - every visualization below then works automatically.")
        return

    theme = ctx.themes.get(ctx.state.get(keys.ACTIVE_THEME_ID) or ctx.settings.default_theme)

    # ---- visualization picker (grouped by category) ----
    grouped: dict[str, list] = defaultdict(list)
    for info in ctx.visuals.infos():
        grouped[info.category or "Other"].append(info)
    with st.sidebar:
        st.markdown("### Visualization")
        category = st.selectbox("Category", sorted(grouped))
        infos = grouped[category]
        chosen = st.selectbox("Visualization", [i.name for i in infos])
        viz = ctx.visuals.create(next(i.id for i in infos if i.name == chosen))
        if viz.info.description:
            st.caption(viz.info.description)

        # ---- automatic filters ----
        st.markdown("### Filters")
        filters = _filter_widgets(df)

        # ---- automatic controls from the plugin declaration ----
        st.markdown("### Controls")
        controls = render_controls(viz.all_controls, key_prefix=f"viz::{viz.info.id}")
        if not controls.get("title"):
            controls["title"] = viz.info.name

    render_ctx = RenderContext(df=df, theme=theme, controls=controls,
                               meta={"filters": filters.to_dict()})
    with st.spinner("Rendering..."):
        fig = ctx.renderer.render(viz, render_ctx)
    st.pyplot(fig, width="stretch")

    # ---- export bar (framework export engine) ----
    c1, c2, c3 = st.columns(3)
    dpi = controls.get("export_dpi", "standard")
    transparent = bool(controls.get("transparent_bg"))
    for col, fmt in zip((c1, c2, c3), ("png", "svg", "pdf")):
        result = ctx.export_engine.export(fig, controls["title"], fmt=fmt,
                                          dpi=dpi, transparent=transparent)
        col.download_button(f"Download {fmt.upper()}", data=result.data,
                            file_name=result.filename, mime=result.mime,
                            width="stretch")
    plt.close(fig)


def _filter_widgets(df) -> FilterSet:
    def options(col: str) -> list[str]:
        return sorted(v for v in df[col].astype(str).unique() if v.strip())

    team = st.selectbox("Team", ["All"] + options("team"))
    opponent = st.selectbox("Opponent", ["All"] + options("opponent"))
    match = st.selectbox("Match", ["All"] + options("match_id"))
    competitions = st.multiselect("Competition", options("competition"))
    seasons = st.multiselect("Season", options("season"))
    players = st.multiselect("Player", options("player"))
    positions = st.multiselect("Position", options("position"))
    event_types = st.multiselect("Event type", options("event_type"))
    outcomes = st.multiselect("Outcome", options("outcome"))
    body_parts = st.multiselect("Body part", options("body_part"))
    play_patterns = st.multiselect("Play pattern", options("play_pattern"))
    periods = st.multiselect("Period", sorted(df["period"].dropna().astype(int).unique()))
    minute_range = st.slider("Minute range", 0, 120, (0, 120))
    score_states = st.multiselect("Score state", ["winning", "drawing", "losing"])
    venues = st.multiselect("Home/Away", options("venue") or ["home", "away"])
    pressure_state = st.selectbox("Pressure", ["any", "under_pressure", "no_pressure"])
    only_success = st.checkbox("Only successful", value=False)
    return FilterSet(
        team=team, opponent=opponent, match_id=match,
        competitions=tuple(competitions), seasons=tuple(seasons),
        players=tuple(players), positions=tuple(positions),
        event_types=tuple(event_types), outcomes=tuple(outcomes),
        body_parts=tuple(body_parts), play_patterns=tuple(play_patterns),
        periods=tuple(int(p) for p in periods),
        minute_range=(float(minute_range[0]), float(minute_range[1])),
        score_states=tuple(score_states), venues=tuple(venues),
        pressure_state=pressure_state, only_successful=only_success,
    )
