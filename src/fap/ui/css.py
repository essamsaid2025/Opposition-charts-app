from __future__ import annotations

import streamlit as st

from fap.themes.theme import Theme


def inject_theme_css(theme: Theme) -> None:
    c = theme.colors
    st.markdown(
        f"""
        <style>
            .stApp {{ background: {c['bg']}; color: {c['text']}; }}
            [data-testid="stSidebar"] {{ background: {c['panel']}; border-right: 1px solid {c['grid']}; }}
            [data-testid="stSidebar"] * {{ color: {c['text']} !important; }}
            .block-container {{ padding-top: 1rem; max-width: 100%; }}
            .fap-header {{ background: {c['panel']}; border: 1px solid {c['grid']};
                           border-radius: 22px; padding: 18px 22px; margin-bottom: 18px; }}
            .fap-title {{ color: {c['text']}; font-size: 30px; font-weight: 850; letter-spacing: -0.03em; }}
            .fap-subtitle {{ color: {c['muted']}; font-size: 14px; margin-top: 4px; }}
            .fap-kpi {{ background: {c['panel']}; border: 1px solid {c['grid']}; border-radius: 18px;
                        padding: 14px 16px; text-align: center; min-height: 86px; }}
            .fap-kpi-label {{ color: {c['muted']}; font-size: 13px; }}
            .fap-kpi-value {{ color: {c['text']}; font-size: 25px; font-weight: 850; margin-top: 4px; }}
            .fap-note {{ background: {c['panel']}; border: 1px solid {c['grid']}; border-radius: 16px;
                         padding: 14px 16px; color: {c['text']}; margin-bottom: 10px; }}
            .stDownloadButton button, .stButton button {{ border-radius: 12px; font-weight: 700; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
