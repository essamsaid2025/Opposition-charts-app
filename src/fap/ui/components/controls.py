"""Generic control renderer - the piece that keeps the UI closed for
modification: it turns a plugin's declared Control tuples into widgets and
returns their values. No visual-specific widget code exists anywhere else."""
from __future__ import annotations

from typing import Any, Sequence

import streamlit as st

from fap.core.types import Control


def render_controls(controls: Sequence[Control], saved: dict[str, Any] | None = None,
                    key_prefix: str = "ctl") -> dict[str, Any]:
    saved = saved or {}
    values: dict[str, Any] = {}
    for control in controls:
        default = saved.get(control.key, control.default)
        widget_key = f"{key_prefix}::{control.key}"
        if control.kind == "checkbox":
            values[control.key] = st.checkbox(control.label, value=bool(default), key=widget_key,
                                              help=control.help or None)
        elif control.kind == "color":
            values[control.key] = st.color_picker(control.label, value=str(default), key=widget_key)
        elif control.kind in ("slider", "int_slider"):
            cast = int if control.kind == "int_slider" else float
            values[control.key] = st.slider(
                control.label, cast(control.min_value or 0), cast(control.max_value or 100),
                cast(default), step=cast(control.step) if control.step else None, key=widget_key,
            )
        elif control.kind == "select":
            options = list(control.options)
            index = options.index(default) if default in options else 0
            values[control.key] = st.selectbox(control.label, options, index=index, key=widget_key)
        elif control.kind == "multiselect":
            values[control.key] = st.multiselect(control.label, list(control.options),
                                                 default=list(default or ()), key=widget_key)
        else:  # text
            values[control.key] = st.text_input(control.label, value=str(default or ""), key=widget_key)
    return values
