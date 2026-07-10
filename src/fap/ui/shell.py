"""Application shell: page config, auth gate, theme + workspace selection,
then dispatch to pages. Deliberately free of analytics logic.

Auth flow:
  environment=development  -> auto-login as a temporary Developer (no screen)
  environment=production   -> login gate; users flagged must_change_password
                              are forced through a password-change form first.
"""
from __future__ import annotations

import streamlit as st

from fap.auth.workflow import DEV_USER, is_development, session_user
from fap.bootstrap import AppContext
from fap.core.exceptions import AuthError
from fap.state import keys
from fap.ui.components import app_header, note_box
from fap.ui.css import inject_theme_css


def run(ctx: AppContext) -> None:
    st.set_page_config(page_title=ctx.settings.app_name, page_icon="⚽",
                       layout="wide", initial_sidebar_state="expanded")

    theme_id = ctx.state.setdefault(keys.ACTIVE_THEME_ID, ctx.settings.default_theme)
    theme = ctx.themes.get(theme_id)
    inject_theme_css(theme)

    if is_development(ctx.settings):
        ctx.state.setdefault(keys.CURRENT_USER, dict(DEV_USER))
    elif ctx.settings.auth.enabled:
        user = ctx.state.get(keys.CURRENT_USER)
        if user is None:
            _login_gate(ctx)
            return
        if user.get("must_change_password"):
            _password_change_gate(ctx, user)
            return

    _sidebar(ctx, theme_id)
    app_header(ctx.settings.app_name,
               "Modular analysis platform - visuals, metrics, providers and exports are plugins.")
    note_box(
        f"Architecture online. Registered plugins - visuals: {len(ctx.visuals)}, "
        f"metrics: {len(ctx.metrics)}, providers: {len(ctx.providers)}, "
        f"exporters: {len(ctx.exporters)}. Add modules to the plugin packages to extend."
    )


# ---------------------------------------------------------------- sidebar
def _sidebar(ctx: AppContext, theme_id: str) -> None:
    with st.sidebar:
        user = ctx.state.get(keys.CURRENT_USER) or {}
        if user.get("dev_mode"):
            st.info("Development mode - signed in as Developer (auth bypassed).")
        elif user:
            st.caption(f"Signed in as **{user.get('username')}** ({user.get('role')})")
            if st.button("Sign out"):
                ctx.state.delete(keys.CURRENT_USER)
                st.rerun()
        chosen = st.selectbox("Theme", ctx.themes.ids(), index=ctx.themes.ids().index(theme_id))
        if chosen != theme_id:
            ctx.state.set(keys.ACTIVE_THEME_ID, chosen)
            st.rerun()


# ---------------------------------------------------------------- gates
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
                ctx.state.set(keys.CURRENT_USER, session_user(user))
                st.rerun()


def _password_change_gate(ctx: AppContext, user: dict) -> None:
    app_header(ctx.settings.app_name, "Password change required")
    note_box("Your account is using a temporary password. Choose a new one to continue.")
    with st.form("change_password"):
        new = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Change password"):
            if new != confirm:
                st.error("Passwords do not match.")
            else:
                try:
                    ctx.authenticator.change_password(user["username"], new)
                except AuthError as exc:
                    st.error(str(exc))
                else:
                    user = dict(user)
                    user["must_change_password"] = False
                    ctx.state.set(keys.CURRENT_USER, user)
                    st.success("Password updated.")
                    st.rerun()
