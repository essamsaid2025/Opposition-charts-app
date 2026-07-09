"""Reusable presentational components: pure functions of (data, theme).
Pages compose these; no page hand-writes HTML."""
from __future__ import annotations

from typing import Sequence

import streamlit as st

from fap.core.types import MetricResult


def app_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"<div class='fap-header'><div class='fap-title'>{title}</div>"
        f"<div class='fap-subtitle'>{subtitle}</div></div>",
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: object) -> None:
    st.markdown(
        f"<div class='fap-kpi'><div class='fap-kpi-label'>{label}</div>"
        f"<div class='fap-kpi-value'>{value}</div></div>",
        unsafe_allow_html=True,
    )


def kpi_row(metrics: Sequence[MetricResult]) -> None:
    if not metrics:
        return
    for col, metric in zip(st.columns(len(metrics)), metrics):
        with col:
            kpi_card(metric.label, metric.formatted)


def note_box(markdown: str) -> None:
    st.markdown(f"<div class='fap-note'>{markdown}</div>", unsafe_allow_html=True)


def section_title(text: str) -> None:
    st.markdown(f"### {text}")
