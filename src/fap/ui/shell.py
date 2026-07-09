"""Application shell: page config, auth gate, theme + workspace selection,
then dispatch to pages. Deliberately free of analytics logic."""
from __future__ import annotations

import streamlit as st

from fap.bootstrap import AppContext
from fap.state import keys
from fap.ui.components import app_header, note_box
from fap.ui.css import inject_theme_css


def run(ctx: AppContext) -> None:
    st.set_page_config(page_title=ctx.settings.app_name, page_icon="⚽",
                       layout="wide", initial_sidebar_state="expanded")

    theme_id = ctx.state.setdefault(keys.ACTIVE_THEME_ID, ctx.settings.default_theme)
    theme = ctx.themes.get(theme_id)
    inject_theme_css(theme)

    if ctx.settings.auth.enabled and ctx.state.get(keys.CURRENT_USER) is None:
        _login_gate(ctx)
        return

    with st.sidebar:
        chosen = st.selectbox("Theme", ctx.themes.ids(),
                              index=ctx.themes.ids().index(theme_id))
        if chosen != theme_id:
            ctx.state.set(keys.ACTIVE_THEME_ID, chosen)
            st.rerun()

    app_header(ctx.settings.app_name,
               "Modular analysis platform - visuals, metrics, providers and exports are plugins.")
    note_box(
        f"Architecture online. Registered plugins - visuals: {len(ctx.visuals)}, "
        f"metrics: {len(ctx.metrics)}, providers: {len(ctx.providers)}, "
        f"exporters: {len(ctx.exporters)}. Add modules to the plugin packages to extend."
    )


def _login_gate(ctx: AppContext) -> None:
    app_header(ctx.settings.app_name, "Sign in to continue")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            user = ctx.authenticator.authenticate(username, password)
            if user is None:
                st.error("Invalid credentials.")
            else:
                ctx.state.set(keys.CURRENT_USER, {"id": user.id, "username": user.username,
                                                  "role": user.role})
                st.rerun()
