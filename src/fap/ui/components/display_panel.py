"""Shared UI for the display-configuration system: a capability-gated Display
panel (+ Reset Display) and the collapsible Data & Methodology note.

Reused by every visualization workspace (Open Play Studio, Set Pieces, Players/
Scouting viz) so the controls and the provenance note look and behave identically
everywhere. Presentation only: the checkboxes write display toggles; the note is
generated from the actual configuration. No analytics here.
"""
from __future__ import annotations

import html as _html
from typing import Any, Callable

import streamlit as st

from fap.visuals.display import VisualizationCapabilities, display_controls_for
from fap.visuals.methodology import MethodologyNote


def render_display_controls(caps: VisualizationCapabilities, values: dict[str, Any],
                            *, key: str, columns: int = 2,
                            defaults: dict[str, Any] | None = None,
                            on_reset: Callable[[], None] | None = None,
                            title: str = "Display") -> dict[str, Any]:
    """Render ONLY the display toggles this visualization supports (strict gating),
    plus a Reset Display action. ``values`` seeds current state; ``defaults`` are the
    visualization's own display defaults (per-viz overrides of the global baseline),
    used to seed unset toggles and to reset. The returned dict holds the (possibly
    updated) display values for the caller to apply to its render config. Never
    renders a control the visualization can't honour."""
    controls = display_controls_for(caps)
    dft = defaults or {}
    header = st.columns([3, 1], vertical_alignment="center")
    header[0].markdown(f"**{title}**")
    reset = header[1].button("Reset", key=f"{key}_reset", use_container_width=True,
                             help="Restore default display (does not change data, "
                                  "filters or selections).")
    out = dict(values)
    if not controls:
        st.caption("No display options for this visualization.")
    else:
        cols = st.columns(max(1, columns))
        for i, ctl in enumerate(controls):
            seed = out.get(ctl.key, dft.get(ctl.key, ctl.default))
            out[ctl.key] = cols[i % len(cols)].checkbox(
                ctl.label, value=bool(seed), key=f"{key}_{ctl.key}",
                help=ctl.help or None)
    if reset:
        for ctl in controls:
            out[ctl.key] = dft.get(ctl.key, ctl.default)
            st.session_state.pop(f"{key}_{ctl.key}", None)      # clear the widget state
        if on_reset is not None:
            on_reset()
        st.rerun()
    return out


def render_methodology_note(note: MethodologyNote, *, key: str = "",
                            expanded: bool = False) -> None:
    """The collapsible 'Data & Methodology' section under a visualization. Renders
    the actual dataset/fields/filters/metric/coordinates/scope/missing behaviour."""
    with st.expander("Data & Methodology", expanded=expanded):
        rows = "".join(
            f'<div style="display:flex;gap:.6rem;padding:.15rem 0;">'
            f'<div style="min-width:104px;color:var(--fap-text-muted);'
            f'font-size:.82rem;">{_html.escape(label)}</div>'
            f'<div style="font-size:.82rem;">{_html.escape(value)}</div></div>'
            for label, value in note.rows())
        st.markdown(
            f'<div style="line-height:1.35;">{rows}</div>', unsafe_allow_html=True)
        st.caption("Generated from this visualization's live configuration — it "
                   "reflects exactly what produced the chart above.")


__all__ = ["render_display_controls", "render_methodology_note"]
