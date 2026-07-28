"""Settings - per-user preferences, auto-saved through the platform."""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.theme import components as C
from fap.ui.page import Page, page_registry

_SCOPE = "settings"
_DEFAULTS = {"language": "English", "units": "Metric", "pitch": "100 x 68",
             "export": "PNG", "provider": "Auto-detect"}


@page_registry.register
class SettingsPage(Page):
    info = PluginInfo(id="settings", name="Settings", category="page")
    section = "Admin"
    icon = "settings"
    order = 95
    min_role = Role.READ_ONLY           # personal settings for everyone

    def render(self, shell) -> None:
        C.render_section_title(
            "Settings", eyebrow="Preferences", icon_name="settings",
            subtitle="Personal defaults, saved automatically to your account.")
        saved = {}
        if shell.wm is not None:
            try:
                saved = shell.wm.load_autosave(shell.user, scope=_SCOPE)
            except Exception:
                saved = {}
        settings = {**_DEFAULTS, **saved}

        C.render_alert("Changes save automatically. The application theme is chosen in the sidebar; "
                       "charts keep their own figure themes.", "info")

        C.render_section_title("Localization", icon_name="flag")
        lc = st.columns(2)
        with lc[0]:
            language = st.selectbox("Language", ["English", "Español", "Français", "Deutsch"],
                                    index=_idx(["English", "Español", "Français", "Deutsch"],
                                               settings["language"]))
        with lc[1]:
            units = st.radio("Units", ["Metric", "Imperial"], horizontal=True,
                             index=_idx(["Metric", "Imperial"], settings["units"]))

        C.render_section_title("Data & export", icon_name="datasets")
        dc = st.columns(3)
        with dc[0]:
            pitch = st.selectbox("Pitch defaults", ["100 x 68", "105 x 68", "120 x 80"],
                                 index=_idx(["100 x 68", "105 x 68", "120 x 80"], settings["pitch"]))
        with dc[1]:
            export = st.selectbox("Export defaults", ["PNG", "SVG", "PDF"],
                                  index=_idx(["PNG", "SVG", "PDF"], settings["export"]))
        with dc[2]:
            provider = st.selectbox("Provider defaults",
                                    ["Auto-detect", "StatsBomb", "Wyscout", "Opta", "Generic"],
                                    index=_idx(["Auto-detect", "StatsBomb", "Wyscout", "Opta",
                                                "Generic"], settings["provider"]))

        new = {"language": language, "units": units, "pitch": pitch,
               "export": export, "provider": provider}
        if new != settings and shell.wm is not None:
            try:
                shell.wm.autosave(shell.user, new, scope=_SCOPE)   # no Save button
                st.toast("Settings saved")
            except Exception:
                pass


def _idx(options: list[str], value: str) -> int:
    return options.index(value) if value in options else 0
