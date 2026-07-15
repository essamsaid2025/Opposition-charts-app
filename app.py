# Opponent Open Play Analysis App v4 — Production Visualization Engine
# Phase 7: engine refinement. Strictly additive over v3.
# - Plugin registry (every visualization is a registered plugin)
# - Pitch Engine: orientation, crops/views, mirror/flip, auto attack direction
# - Thirds Engine: line/highlight/custom modes, both orientations
# - Visualization Themes (16) — affect figures ONLY, never the Streamlit app theme
# - Heatmap Studio: KDE / hexbin / grid / zone / density variants + semantic presets
# - Marker Studio, Arrow Studio, Label Engine (collision-aware), Legend Engine
# - Statistical tables, match summary cards, dashboard builder with saved templates
# - Export PNG/SVG/PDF at selectable DPI, exact match with preview
# Streamlit + Pandas + Matplotlib + mplsoccer. No set-pieces, no xG model required.

from __future__ import annotations

import json
import math
import sys
from io import BytesIO
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib import gridspec
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.markers import MarkerStyle
from matplotlib.patches import Arc, Circle, FancyBboxPatch, Rectangle
from matplotlib.transforms import Affine2D

try:
    from mplsoccer import Pitch, VerticalPitch
    HAS_MPLSOCCER = True
except Exception:
    HAS_MPLSOCCER = False

# The platform package lives in src/ and is not pip-installed; make `fap`
# importable exactly the way the test-suite bootstrap already does.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fap.bootstrap import PlatformContext, init_platform   # noqa: E402
from fap.core.exceptions import FAPError               # noqa: E402
from fap.core.version import platform_version          # noqa: E402
from fap.pipeline.columns import (                     # noqa: E402
    CONFIDENCE_THRESHOLD,
    alias_candidates as platform_alias_candidates,
    detect_columns,
    normalize_name,
)
from fap.pipeline.importer import ImportResult, ImportService  # noqa: E402

# -----------------------------
# Page config
# -----------------------------
st.set_page_config(
    page_title="Opponent Open Play Analysis",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------
# App (chrome) themes — style the Streamlit UI only.
# Visualization themes are defined separately below and never touch the app.
# -----------------------------
APP_THEMES: Dict[str, Dict[str, str]] = {
    "Opta Analyst Light": {
        "bg": "#ECECEC", "panel": "#F5F5F5", "text": "#201C2B", "muted": "#7A7584",
        "grid": "#B8B8B8", "accent": "#6D28D9",
    },
    "Sofa Light": {
        "bg": "#F7F9FC", "panel": "#FFFFFF", "text": "#111111", "muted": "#5A6572",
        "grid": "#DDE3EA", "accent": "#2563EB",
    },
    "The Athletic Dark": {
        "bg": "#0E1117", "panel": "#111827", "text": "#FFFFFF", "muted": "#A0A7B4",
        "grid": "#2A3240", "accent": "#38BDF8",
    },
    "Opta Dark": {
        "bg": "#0E1117", "panel": "#141A22", "text": "#FFFFFF", "muted": "#A0A7B4",
        "grid": "#2A3240", "accent": "#00C2FF",
    },
    "Black Stripe": {
        "bg": "#000000", "panel": "#0A0A0A", "text": "#FFFFFF", "muted": "#B7B7B7",
        "grid": "#2A2A2A", "accent": "#38BDF8",
    },
}


def inject_css(theme: Dict[str, str]) -> None:
    st.markdown(
        f"""
        <style>
            .stApp {{ background: {theme['bg']}; color: {theme['text']}; }}
            [data-testid="stSidebar"] {{ background: {theme['panel']}; border-right: 1px solid {theme['grid']}; }}
            [data-testid="stSidebar"] * {{ color: {theme['text']} !important; }}
            .block-container {{ padding-top: 1.0rem; max-width: 100%; }}
            .main-header {{ background: {theme['panel']}; border: 1px solid {theme['grid']}; border-radius: 22px; padding: 18px 22px; margin-bottom: 18px; }}
            .main-title {{ color: {theme['text']}; font-size: 30px; font-weight: 850; letter-spacing: -0.03em; }}
            .main-subtitle {{ color: {theme['muted']}; font-size: 14px; margin-top: 4px; }}
            .kpi-card {{ background: {theme['panel']}; border: 1px solid {theme['grid']}; border-radius: 18px; padding: 14px 16px; text-align: center; min-height: 86px; }}
            .kpi-label {{ color: {theme['muted']}; font-size: 13px; }}
            .kpi-value {{ color: {theme['text']}; font-size: 25px; font-weight: 850; margin-top: 4px; }}
            .note-box {{ background: {theme['panel']}; border: 1px solid {theme['grid']}; border-radius: 16px; padding: 14px 16px; color: {theme['text']}; margin-bottom: 10px; }}
            div[data-testid="stMetricValue"] {{ color: {theme['text']}; }}
            .stDownloadButton button, .stButton button {{ border-radius: 12px; font-weight: 700; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Visualization themes — figures only. NEVER applied to the Streamlit UI.
# Tokens cover: pitch, typography, legends, tables, cards, grid, arrows,
# markers, spacing, borders, background.
# -----------------------------
def _vt(bg, pitch, stripe, line, text, muted, grid, accent, accent2,
        success="#22A06B", danger="#D64045", warning="#E3B341", grey="#8F8F8F",
        panel=None, font="DejaVu Sans", serif=False, line_w=1.6,
        title_weight="bold", card_face=None, card_edge=None,
        legend_face=None, legend_edge=None, table_zebra=None) -> Dict:
    panel = panel or bg
    return {
        "bg": bg, "panel": panel, "pitch": pitch, "stripe": stripe, "line": line,
        "text": text, "muted": muted, "grid": grid, "accent": accent,
        "accent2": accent2, "success": success, "danger": danger,
        "warning": warning, "grey": grey,
        "font": ("DejaVu Serif" if serif else font),
        "line_w": line_w, "title_weight": title_weight,
        "card_face": card_face or panel, "card_edge": card_edge or grid,
        "legend_face": legend_face or panel, "legend_edge": legend_edge or grid,
        "table_zebra": table_zebra or grid,
    }


VIZ_THEMES: Dict[str, Dict] = {
    "Opta Analyst": _vt("#ECECEC", "#ECECEC", "#E4E4E4", "#9F9F9F", "#201C2B", "#7A7584",
                        "#C6C6C6", "#6D28D9", "#D64045", panel="#F5F5F5"),
    "The Athletic": _vt("#FAF6EF", "#FAF6EF", "#F3EDE0", "#3B3630", "#1E1B16", "#7C7468",
                        "#DDD5C6", "#E4572E", "#2E6F95", serif=True, panel="#FFFDF8",
                        table_zebra="#F1EADB"),
    "StatsBomb": _vt("#22312B", "#22312B", "#26352F", "#C7D5CC", "#F4F4F4", "#9AAFA5",
                     "#37463F", "#FF4B44", "#38BDF8", panel="#1B2823"),
    "Hudl": _vt("#101820", "#13202B", "#152532", "#DDE5EC", "#FFFFFF", "#93A3B1",
                "#26343F", "#FF6300", "#38BDF8", panel="#0C141B"),
    "Wyscout": _vt("#FFFFFF", "#F5F5F5", "#EFEFEF", "#8A8A8A", "#1B1B1B", "#707070",
                   "#DADADA", "#E2001A", "#1B3B6F", panel="#FAFAFA"),
    "FBref": _vt("#FFFFFF", "#EDEDED", "#E7E7E7", "#8C8C8C", "#121212", "#6E6E6E",
                 "#D6D6D6", "#0B6623", "#B0322A", panel="#F7F7F7"),
    "SofaScore": _vt("#F7F9FC", "#79C98A", "#66C679", "#FFFFFF", "#111111", "#5A6572",
                     "#DDE3EA", "#374DF5", "#06B6D4", panel="#FFFFFF"),
    "UEFA": _vt("#050A30", "#0A1F5C", "#0C2467", "#9BD1FF", "#FFFFFF", "#9FB2D8",
                "#1C3272", "#00E1FF", "#FFD166", panel="#081642"),
    "FIFA": _vt("#0B1F3A", "#10294B", "#123055", "#E9EDF4", "#FFFFFF", "#A9B7CB",
                "#223B5E", "#D4AF37", "#4CC9F0", panel="#0E2444"),
    "TV Broadcast": _vt("#061A10", "#2E8B3D", "#278036", "#FFFFFF", "#FFFFFF", "#BBD6C2",
                        "#1E4D2B", "#FFD400", "#38BDF8", panel="#0A2417", line_w=2.0),
    "Presentation": _vt("#FFFFFF", "#F2F4F7", "#ECEFF3", "#7B8794", "#101828", "#667085",
                        "#D0D5DD", "#2563EB", "#F97316", panel="#FFFFFF", line_w=2.0,
                        title_weight="heavy"),
    "Print": _vt("#FFFFFF", "#FFFFFF", "#FFFFFF", "#000000", "#000000", "#444444",
                 "#BBBBBB", "#000000", "#666666", success="#333333", danger="#000000",
                 warning="#777777", grey="#999999", panel="#FFFFFF", line_w=1.2),
    "Dark Professional": _vt("#0B0D12", "#0F1218", "#11151C", "#E6E6E6", "#FFFFFF", "#A0A7B4",
                             "#242A33", "#38BDF8", "#A78BFA", panel="#12161E"),
    "Light Professional": _vt("#FFFFFF", "#F2F4F7", "#EDF0F4", "#98A2B3", "#101828", "#667085",
                              "#D0D5DD", "#2563EB", "#12B76A", panel="#FBFCFE"),
    # "Club Theme" and "Custom Theme" are constructed at runtime from pickers.
}
CLUB_CUSTOM_NAMES = ["Club Theme", "Custom Theme"]

HEAT_CMAPS = ["Greens", "Blues", "Reds", "Purples", "Oranges", "YlOrRd", "YlGnBu",
              "RdYlGn_r", "coolwarm", "magma", "inferno", "viridis", "cividis", "bone_r", "Greys"]
DEF_EVENTS = ["duel", "recovery", "interception", "clearance", "tackle", "block"]
ARROW_EVENTS = ["pass", "carry", "cross", "dribble"]
SUCCESS_WORDS = ["successful", "success", "complete", "won"]
REQUIRED_MINIMUM = ["event_type", "x", "y"]
PITCH_LENGTH = 100
PITCH_WIDTH = 68
W = PITCH_WIDTH  # shorthand

# -----------------------------
# Data helpers (v3 contract preserved)
# -----------------------------
COORD_SYSTEM_IDS: Dict[str, str] = {"0-100": "0-100", "120 x 80": "120x80"}


@st.cache_resource(show_spinner=False)
def _platform_context(version: str) -> PlatformContext:
    """Cached platform, keyed by the platform's own version.

    `version` is unused in the body on purpose: it is the cache key. Streamlit
    invalidates a cached resource only when *this function's* body changes, so
    without the key a code update would keep serving a context whose services
    were built from the previous modules (that is exactly what broke Phase
    2B.2 in production). Fingerprint changes -> new key -> services rebuilt
    against the modules just loaded. No reboot, no constant to bump.
    """
    return init_platform(Path(__file__).resolve().parent)


def platform() -> PlatformContext:
    """The platform this rerun should use. Cheap: one stat per fap module."""
    return _platform_context(platform_version())


def import_service() -> ImportService:
    """The platform import engine: provider registry, mapping templates,
    coordinate normalization, cleaning and validation. Resolved through the
    platform bootstrap - Open Play constructs nothing itself."""
    return platform().importer


def read_uploaded_file(uploaded_file) -> pd.DataFrame:
    """Raw, un-normalized frame from the platform provider registry.

    Contract unchanged (uploaded file -> DataFrame). The direct pd.read_csv /
    pd.read_excel calls are gone: provider detection and file loading are the
    platform's job, so every registered format - now including JSON - works
    here without Open Play knowing about any of them.
    """
    name = getattr(uploaded_file, "name", "") or "upload.csv"
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    data = uploaded_file.read()
    try:
        provider = import_service().pick_provider(name)
    except FAPError as exc:
        raise ValueError("Please upload a CSV, Excel or JSON file.") from exc
    return provider.load(BytesIO(data), name).frame


def platform_import(filename: str, data: bytes, mapping: Dict[str, str],
                    coord_mode: str, attack_direction: str) -> ImportResult:
    """Hand the confirmed Open Play mapping to the platform and let it do the
    work: provider detection, loading, mapping, coordinate normalization,
    cleaning, validation and quality scoring.

    Open Play's mapping is {canonical: source}; ImportService wants the inverse.
    """
    return import_service().import_file(
        data, filename,
        mapping={src: canon for canon, src in mapping.items() if src},
        coord_system=COORD_SYSTEM_IDS.get(coord_mode, "0-100"),
        flip_direction=attack_direction.startswith("Team attacks right-to-left"),
    )


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_columns(df)
    for col in ["x", "y", "x2", "y2", "minute", "second", "shirt_number", "period"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["event_type", "phase", "team", "opponent", "player", "receiver", "outcome",
                "shot_result", "body_part", "direction", "competition", "date", "match_id",
                "zone", "sequence_id", "notes"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    if "period" not in df.columns:
        df["period"] = 1
    df["period"] = pd.to_numeric(df["period"], errors="coerce").fillna(1)
    for col in ["x2", "y2", "minute", "second"]:
        if col not in df.columns:
            df[col] = np.nan
    return df


def validate_data(df: pd.DataFrame) -> List[str]:
    missing = [c for c in REQUIRED_MINIMUM if c not in df.columns]
    return [f"Missing required columns: {', '.join(missing)}"] if missing else []


# ============================================================================
# COLUMN MAPPING - Open Play consumes the platform's mapping engine.
# The alias table, the normalizer, candidate ranking and detection all live in
# fap.pipeline.columns; there is no second alias list here and there must never
# be one again. Open Play only translates between its own field vocabulary
# (x2/y2) and the platform's canonical schema (end_x/end_y), and drives the UI.
# ============================================================================
REQUIRED_CANONICAL = ["event_type", "x", "y"]
OPTIONAL_CANONICAL = ["x2", "y2"]
CANONICAL_LABELS = {"event_type": "Event type", "x": "X (start)", "y": "Y (start)",
                    "x2": "X (end)", "y2": "Y (end)"}

# Open Play's field names -> the platform's canonical schema. x2/y2 are the
# schema's legacy aliases for end_x/end_y and are kept in sync by coerce_schema.
_APP_TO_PLATFORM = {"event_type": "event_type", "x": "x", "y": "y",
                    "x2": "end_x", "y2": "end_y"}
_PLATFORM_TO_APP = {v: k for k, v in _APP_TO_PLATFORM.items()}

# the platform's normalizer, re-exported under the historical Open Play name
_norm_key = normalize_name


def alias_candidates(df: pd.DataFrame) -> Dict[str, List[str]]:
    """Platform alias candidates, expressed in Open Play's field names.
    Best match first; used for the preview log and the mapping dialog."""
    platform = platform_alias_candidates(df)
    return {app_field: list(platform[plat_field])
            for app_field, plat_field in _APP_TO_PLATFORM.items()
            if platform.get(plat_field)}


def platform_detect(df: pd.DataFrame) -> Tuple[object, Optional[str]]:
    """Platform detection for this file shape: a saved mapping template wins,
    otherwise the alias engine. Returns (ColumnMapping, template_name)."""
    try:
        return import_service().detect(df)
    except FAPError:
        # no template store available (e.g. read-only deployment) -> aliases only
        return detect_columns(df), None


def auto_map_columns(df: pd.DataFrame) -> Dict[str, str]:
    """Best-match auto detection via the platform. Returns {canonical: source}
    for the fields Open Play maps; every rule behind it belongs to the platform."""
    detected, _template = platform_detect(df)
    mapping: Dict[str, str] = {}
    for source, plat_field in detected.mapping.items():
        app_field = _PLATFORM_TO_APP.get(plat_field)
        if app_field:
            mapping[app_field] = source
    return mapping


def mapping_confidence(df: pd.DataFrame) -> float:
    """Platform confidence for the fields Open Play requires. Below the
    platform's CONFIDENCE_THRESHOLD the mapping dialog opens."""
    detected, _template = platform_detect(df)
    return detected.confidence_for([_APP_TO_PLATFORM[c] for c in REQUIRED_CANONICAL])


def save_mapping_template(name: str, df: pd.DataFrame, mapping: Dict[str, str],
                          filename: str) -> None:
    """Persist the confirmed mapping through the platform TemplateRepository so
    the next file with this column shape maps itself."""
    svc = import_service()
    source_to_canonical = {src: _APP_TO_PLATFORM[canon]
                           for canon, src in mapping.items() if src}
    svc.save_template(name, svc.pick_provider(filename).info.id,
                      [str(c) for c in df.columns], source_to_canonical)


def mapping_log(df: pd.DataFrame, mapping: Dict[str, str]) -> List[str]:
    """Human-readable notes for cases where several aliases were present and a
    best match had to be chosen (requirement: 'use the best match and log it')."""
    cands = alias_candidates(df)
    logs: List[str] = []
    for canon, chosen in mapping.items():
        others = [c for c in cands.get(canon, []) if c != chosen]
        if others:
            logs.append(f"{CANONICAL_LABELS.get(canon, canon)}: using '{chosen}' "
                        f"(also matched: {', '.join(others)})")
    return logs


def resolve_column_mapping(df: pd.DataFrame,
                           manual: Optional[Dict[str, str]] = None
                           ) -> Tuple[Dict[str, str], List[str]]:
    """Auto detection combined with a user/session manual map (manual wins).
    Returns (mapping {canonical: source}, unresolved_required_canonicals)."""
    mapping = auto_map_columns(df)
    for canon, src in (manual or {}).items():
        if src and src in df.columns:
            for other in [k for k, v in mapping.items() if v == src and k != canon]:
                del mapping[other]            # free the source from any auto claim
            mapping[canon] = src
    unresolved = [c for c in REQUIRED_CANONICAL if c not in mapping]
    return mapping, unresolved


def apply_column_mapping(df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
    """Rename detected/selected source columns to their canonical names."""
    rename = {src: canon for canon, src in mapping.items()
              if src in df.columns and src != canon and canon not in df.columns}
    return df.rename(columns=rename) if rename else df


def mapping_preview_table(df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
    """Original column -> mapped canonical field, for every uploaded column."""
    inv = {src: canon for canon, src in mapping.items()}
    rows = [{"Original column": col,
             "Mapped to": CANONICAL_LABELS.get(inv[col], inv[col]) if col in inv else "—"}
            for col in df.columns]
    return pd.DataFrame(rows, columns=["Original column", "Mapped to"])


def render_import_preview(df: pd.DataFrame, mapping: Dict[str, str], logs: List[str],
                          confidence: float = 1.0, filename: str = "") -> None:
    """Interactive preview + mapping dialog shown before import. Lets the user
    review and correct which uploaded column feeds each required/optional field,
    then confirm. Choices are remembered in session_state until the app restarts,
    and can be saved as a reusable mapping template."""
    st.markdown("### Column mapping preview")
    st.caption("Review how your uploaded columns map to the required fields, adjust "
               "anything that's wrong, then confirm to import. This is remembered "
               "for the session.")
    _detected, template_used = platform_detect(df)
    if template_used:
        st.success(f"Loaded saved mapping template: **{template_used}**")
    st.caption(f"Automatic detection confidence: **{confidence:.0%}** "
               f"(dialog opens below {CONFIDENCE_THRESHOLD:.0%})")
    for msg in logs:
        st.caption("• " + msg)

    options = ["— none —"] + list(map(str, df.columns))
    chosen: Dict[str, Optional[str]] = {}
    cols_ui = st.columns(2)
    for i, canon in enumerate(REQUIRED_CANONICAL + OPTIONAL_CANONICAL):
        required = canon in REQUIRED_CANONICAL
        detected = mapping.get(canon)
        idx = options.index(detected) if detected in options else 0
        with cols_ui[i % 2]:
            sel = st.selectbox(
                f"{CANONICAL_LABELS[canon]}{' *' if required else '  (optional)'}",
                options, index=idx, key=f"premap_{canon}")
        chosen[canon] = None if sel == "— none —" else sel

    live = apply_column_mapping(df, {c: s for c, s in chosen.items() if s})
    st.dataframe(mapping_preview_table(df, {c: s for c, s in chosen.items() if s}),
                 width="stretch", height=min(360, 60 + 32 * len(df.columns)))

    missing = [CANONICAL_LABELS[c] for c in REQUIRED_CANONICAL if not chosen.get(c)]
    if missing:
        st.warning("Required fields still unmapped: " + ", ".join(missing) +
                   ". Pick the matching uploaded column above to continue.")

    # Save this mapping for every future file with the same column shape.
    tpl_name = st.text_input("Save as mapping template (optional)", value="",
                             placeholder="e.g. My Club, Hudl Export, Custom GPS",
                             key="premap_template_name")

    if st.button("Confirm mapping & import", type="primary", disabled=bool(missing)):
        cm = st.session_state.setdefault("col_map", {})
        for canon, src in chosen.items():
            if src:
                cm[canon] = src
            else:
                cm.pop(canon, None)
        if tpl_name.strip():
            try:
                save_mapping_template(tpl_name.strip(), df,
                                      {c: s for c, s in chosen.items() if s}, filename)
                st.toast(f"Saved mapping template '{tpl_name.strip()}'")
            except Exception as exc:                      # never block an import
                st.warning(f"Could not save template: {exc}")
        st.session_state["_import_confirmed"] = st.session_state.get("_mapping_file")
        st.session_state["_force_mapping"] = False
        st.rerun()


def render_import_summary(result: ImportResult, source_df: pd.DataFrame) -> None:
    """What the platform did with this file: detected provider, mapping
    confidence, fields the file supplied vs fields the schema generated, and
    anything required that is still missing."""
    summary = result.summary
    generated = summary.get("generated_fields", [])
    missing = summary.get("missing_required", [])
    label = summary.get("provider_name") or result.provider_id

    with st.expander("Import summary", expanded=bool(missing)):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Detected provider", label)
        c2.metric("Mapping confidence", f"{result.mapping_confidence:.0%}")
        c3.metric("Coordinates", f"{result.coord_system} ({result.coord_confidence:.0%})")
        c4.metric("Data quality", f"{result.quality.overall:.0f}/100")

        if result.template_used:
            st.caption(f"Mapping template applied: **{result.template_used}**")
        if result.cache_hit:
            st.caption("Loaded from the import cache.")

        st.caption("**Mapped from your file:** " +
                   (", ".join(f"`{c}`" for c in sorted(result.mapping.values())) or "—"))
        if generated:
            st.caption("**Generated (not in your file, filled by the schema):** " +
                       ", ".join(f"`{c}`" for c in generated))
        if missing:
            st.error("Missing required fields: " + ", ".join(f"`{c}`" for c in missing))
        if result.cleaning_log:
            st.caption("**Cleaning:** " + "; ".join(result.cleaning_log))

        if st.button("Review / edit column mapping"):
            st.session_state["_force_mapping"] = True
            st.session_state["_import_confirmed"] = None
            st.rerun()


def normalize_coordinates(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    df = df.copy()
    if mode == "120 x 80":
        for a in ["x", "x2"]:
            df[a] = df[a] / 120 * 100
        for a in ["y", "y2"]:
            df[a] = df[a] / 80 * 100
    for col in ["x", "y", "x2", "y2"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").clip(0, 100)
    return df


def flip_attacking_direction(df: pd.DataFrame, attack_direction: str) -> pd.DataFrame:
    df = df.copy()
    if attack_direction.startswith("Team attacks right-to-left"):
        for col in ["x", "x2"]:
            df[col] = 100 - df[col]
    return df


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    dx = df["x2"] - df["x"]
    dy = df["y2"] - df["y"]
    df["distance"] = np.sqrt(dx**2 + dy**2)
    df["is_forward"] = dx > 8
    df["is_backward"] = dx < -8
    df["is_lateral"] = (~df["is_forward"]) & (~df["is_backward"])
    df["is_progressive"] = (dx >= 10) & ((100 - df["x2"]) <= 0.75 * (100 - df["x"]))
    df["into_final_third"] = (df["x"] < 66.67) & (df["x2"] >= 66.67)
    df["into_box"] = (df["x2"] >= 83) & (df["y2"].between(21, 79))
    df["in_box"] = (df["x"] >= 83) & (df["y"].between(21, 79))
    df["start_third"] = pd.cut(df["x"], bins=[-0.1, 33.33, 66.67, 100.1],
                               labels=["Defensive Third", "Middle Third", "Final Third"])
    df["lane"] = pd.cut(df["y"], bins=[-0.1, 33.33, 66.67, 100.1],
                        labels=["Left Lane", "Central Lane", "Right Lane"])
    df["time_min"] = pd.to_numeric(df["minute"], errors="coerce").fillna(0) + \
        pd.to_numeric(df["second"], errors="coerce").fillna(0) / 60
    df["shot_distance"] = np.sqrt((100 - df["x"]) ** 2 + (50 - df["y"]) ** 2)
    return df


def pct(n: float, d: float) -> str:
    return "0%" if d == 0 else f"{(n / d * 100):.0f}%"


def safe_count(df: pd.DataFrame, col: str, value: str) -> int:
    if col not in df.columns:
        return 0
    return int(df[col].astype(str).str.lower().eq(value.lower()).sum())


def is_success(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(SUCCESS_WORDS)


def kpi(label: str, value) -> None:
    st.markdown(
        f"<div class='kpi-card'><div class='kpi-label'>{label}</div>"
        f"<div class='kpi-value'>{value}</div></div>",
        unsafe_allow_html=True,
    )


# =============================
# PITCH ENGINE
# =============================
PITCH_VIEWS = ["Full Pitch", "Attacking Half", "Defensive Half", "Final Third",
               "Middle Third", "Defensive Third", "Attacking Penalty Area",
               "Defensive Penalty Area", "Custom Crop"]


@dataclass
class PitchSpec:
    orientation: str = "Horizontal"          # Horizontal | Vertical | Auto
    view: str = "Full Pitch"
    custom_crop: Tuple[float, float, float, float] = (0.0, 100.0, 0.0, 100.0)  # x0,x1,y0,y1 in 0-100
    mirror: bool = False                     # flip X (attack direction)
    flip_y: bool = False
    thirds_mode: str = "Length thirds (lines)"
    thirds_positions: str = "33.33, 66.67"
    thirds_color: str = "#E3B341"
    thirds_width: float = 1.3
    thirds_alpha: float = 0.7
    thirds_labels: bool = False
    lane_lines: bool = False
    stripes: bool = True

    def is_vertical(self) -> bool:
        if self.orientation == "Vertical":
            return True
        if self.orientation == "Auto":
            return self.view in ("Final Third", "Attacking Half", "Attacking Penalty Area")
        return False


def apply_pitch_transforms(df: pd.DataFrame, spec: PitchSpec) -> pd.DataFrame:
    """Apply mirror/flip, then compute plotting coordinates on the 100x68 pitch."""
    df = df.copy()
    if spec.mirror:
        for c in ["x", "x2"]:
            df[c] = 100 - df[c]
    if spec.flip_y:
        for c in ["y", "y2"]:
            df[c] = 100 - df[c]
    df["x_plot"] = df["x"]
    df["x2_plot"] = df["x2"]
    df["y_plot"] = df["y"] * W / 100
    df["y2_plot"] = df["y2"] * W / 100
    return df


def view_limits(spec: PitchSpec) -> Tuple[float, float, float, float]:
    """Return (x0, x1, w0, w1) in horizontal pitch frame (length 0-100, width 0-68)."""
    v = spec.view
    if v == "Attacking Half":
        return (47, 103, -3, W + 3)
    if v == "Defensive Half":
        return (-3, 53, -3, W + 3)
    if v == "Final Third":
        return (63.5, 103, -3, W + 3)
    if v == "Middle Third":
        return (30.3, 69.7, -3, W + 3)
    if v == "Defensive Third":
        return (-3, 36.5, -3, W + 3)
    if v == "Attacking Penalty Area":
        return (79.5, 103, 9.5, W - 9.5)
    if v == "Defensive Penalty Area":
        return (-3, 20.5, 9.5, W - 9.5)
    if v == "Custom Crop":
        x0, x1, y0, y1 = spec.custom_crop
        return (max(-3, x0 - 2), min(103, x1 + 2), max(-3, y0 * W / 100 - 2), min(W + 3, y1 * W / 100 + 2))
    return (-3, 103, -3, W + 3)


def pc(x, y, vertical: bool):
    """Map horizontal-frame plot coords to axis coords for the chosen orientation."""
    if vertical:
        return y, x
    return x, y


def draw_manual_pitch(ax, vt: Dict, spec: PitchSpec):
    lc, lw = vt["line"], vt["line_w"]
    ax.add_patch(Rectangle((0, 0), 100, W, fill=False, edgecolor=lc, linewidth=lw, zorder=2))
    ax.plot([50, 50], [0, W], color=lc, lw=lw, zorder=2)
    ax.add_patch(Circle((50, W / 2), 9.15, fill=False, edgecolor=lc, lw=lw, zorder=2))
    ax.add_patch(Circle((50, W / 2), 0.45, color=lc, zorder=2))
    ax.add_patch(Rectangle((0, 13.84), 16.5, 40.32, fill=False, edgecolor=lc, linewidth=lw, zorder=2))
    ax.add_patch(Rectangle((83.5, 13.84), 16.5, 40.32, fill=False, edgecolor=lc, linewidth=lw, zorder=2))
    ax.add_patch(Rectangle((0, 24.84), 5.5, 18.32, fill=False, edgecolor=lc, linewidth=lw, zorder=2))
    ax.add_patch(Rectangle((94.5, 24.84), 5.5, 18.32, fill=False, edgecolor=lc, linewidth=lw, zorder=2))
    ax.add_patch(Circle((11, W / 2), 0.45, color=lc, zorder=2))
    ax.add_patch(Circle((89, W / 2), 0.45, color=lc, zorder=2))
    ax.add_patch(Arc((11, W / 2), 18.3, 18.3, theta1=310, theta2=50, color=lc, lw=lw, zorder=2))
    ax.add_patch(Arc((89, W / 2), 18.3, 18.3, theta1=130, theta2=230, color=lc, lw=lw, zorder=2))
    ax.add_patch(Rectangle((-2, 29.5), 2, 9, fill=False, edgecolor=lc, linewidth=lw, zorder=2))
    ax.add_patch(Rectangle((100, 29.5), 2, 9, fill=False, edgecolor=lc, linewidth=lw, zorder=2))


def parse_positions(text: str) -> List[float]:
    out = []
    for tok in str(text).replace(";", ",").split(","):
        tok = tok.strip()
        try:
            v = float(tok)
            if 0 < v < 100:
                out.append(v)
        except Exception:
            pass
    return out


def draw_thirds(ax, vt: Dict, spec: PitchSpec, ctx: Dict):
    """Thirds engine. Draws length/lane lines or third highlights, both orientations."""
    vertical = spec.is_vertical()
    mode = spec.thirds_mode
    col, lwd, alp = spec.thirds_color, spec.thirds_width, spec.thirds_alpha

    def length_line(xv):
        p1 = pc(xv, 0, vertical)
        p2 = pc(xv, W, vertical)
        ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=col, lw=lwd, ls="--", alpha=alp, zorder=2.5)

    def lane_line(yv):
        p1 = pc(0, yv, vertical)
        p2 = pc(100, yv, vertical)
        ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=col, lw=max(0.8, lwd - 0.3), ls=":", alpha=alp, zorder=2.5)

    def highlight(x0, x1, label):
        px, py = pc(x0, 0, vertical)
        wdt, hgt = (W, x1 - x0) if vertical else (x1 - x0, W)
        ax.add_patch(Rectangle((px, py), wdt, hgt, color=col, alpha=min(0.35, alp * 0.4), zorder=1.5, lw=0))
        if spec.thirds_labels:
            cx, cy = pc((x0 + x1) / 2, W / 2, vertical)
            ax.text(cx, cy, label, ha="center", va="center", color=vt["text"],
                    fontsize=ctx.get("label_size", 11), fontweight="bold", alpha=0.85,
                    fontfamily=vt["font"], zorder=2.6,
                    path_effects=[pe.withStroke(linewidth=3, foreground=vt["pitch"])])

    def third_labels():
        if not spec.thirds_labels:
            return
        for x0, x1, name in [(0, 33.33, "DEF 3RD"), (33.33, 66.67, "MID 3RD"), (66.67, 100, "FINAL 3RD")]:
            cx, cy = pc((x0 + x1) / 2, W + 1.7, vertical)
            rot = 90 if vertical else 0
            ax.text(cx, cy, name, ha="center", va="center", color=vt["muted"],
                    fontsize=max(7, ctx.get("label_size", 11) - 2), fontfamily=vt["font"],
                    rotation=rot, zorder=2.6)

    if mode == "None":
        pass
    elif mode == "Length thirds (lines)":
        length_line(33.33)
        length_line(66.67)
        third_labels()
    elif mode == "Width lanes (lines)":
        lane_line(W / 3)
        lane_line(2 * W / 3)
    elif mode == "Length thirds + lanes":
        length_line(33.33)
        length_line(66.67)
        lane_line(W / 3)
        lane_line(2 * W / 3)
        third_labels()
    elif mode == "Highlight final third":
        highlight(66.67, 100, "FINAL 3RD")
    elif mode == "Highlight middle third":
        highlight(33.33, 66.67, "MID 3RD")
    elif mode == "Highlight defensive third":
        highlight(0, 33.33, "DEF 3RD")
    elif mode == "Highlight attacking half":
        highlight(50, 100, "ATT HALF")
    elif mode == "Highlight defensive half":
        highlight(0, 50, "DEF HALF")
    elif mode == "Custom positions":
        for v in parse_positions(spec.thirds_positions):
            length_line(v)

    if spec.lane_lines and mode not in ("Width lanes (lines)", "Length thirds + lanes"):
        lane_line(W / 3)
        lane_line(2 * W / 3)


def new_pitch_fig(vt: Dict, spec: PitchSpec, ctx: Dict, fig_scale: float = 1.0,
                  ax=None) -> Tuple[plt.Figure, plt.Axes]:
    """Create (or draw into) a themed pitch axes with crop, stripes and thirds."""
    vertical = spec.is_vertical()
    x0, x1, w0, w1 = view_limits(spec)
    if ax is None:
        span_x = x1 - x0
        span_w = w1 - w0
        if vertical:
            figsize = (7.0 * fig_scale * (span_w / (W + 6)) + 1.2, 9.6 * fig_scale * (span_x / 106) + 1.0)
        else:
            figsize = (11.2 * fig_scale * (span_x / 106) + 1.2, 7.6 * fig_scale * (span_w / (W + 6)) + 1.0)
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure
    fig.patch.set_facecolor(vt["bg"])
    ax.set_facecolor(vt["pitch"])

    # base pitch
    if HAS_MPLSOCCER:
        PitchCls = VerticalPitch if vertical else Pitch
        pitch = PitchCls(pitch_type="custom", pitch_length=PITCH_LENGTH, pitch_width=PITCH_WIDTH,
                         pitch_color=vt["pitch"], line_color=vt["line"], linewidth=vt["line_w"],
                         line_zorder=2, pad_top=3, pad_bottom=3, pad_left=3, pad_right=3)
        pitch.draw(ax=ax)
    else:
        draw_manual_pitch(ax, vt, spec) if not vertical else None
        if vertical:  # manual vertical: draw horizontal then rely on pc() mapping for content;
            # draw simple rotated pitch outline
            lc, lw = vt["line"], vt["line_w"]
            ax.add_patch(Rectangle((0, 0), W, 100, fill=False, edgecolor=lc, linewidth=lw, zorder=2))
            ax.plot([0, W], [50, 50], color=lc, lw=lw, zorder=2)
            ax.add_patch(Circle((W / 2, 50), 9.15, fill=False, edgecolor=lc, lw=lw, zorder=2))
            ax.add_patch(Rectangle((13.84, 0), 40.32, 16.5, fill=False, edgecolor=lc, lw=lw, zorder=2))
            ax.add_patch(Rectangle((13.84, 83.5), 40.32, 16.5, fill=False, edgecolor=lc, lw=lw, zorder=2))

    # stripes under lines (line_zorder=2), above pitch face
    if spec.stripes and vt["stripe"] != vt["pitch"]:
        for i in range(0, 100, 20):
            if (i // 20) % 2 == 0:
                px, py = pc(i, 0, vertical)
                wdt, hgt = (W, 20) if vertical else (20, W)
                ax.add_patch(Rectangle((px, py), wdt, hgt, color=vt["stripe"], alpha=0.55, zorder=1, lw=0))

    draw_thirds(ax, vt, spec, ctx)

    # crop
    if vertical:
        ax.set_xlim(w0, w1)
        ax.set_ylim(x0, x1)
    else:
        ax.set_xlim(x0, x1)
        ax.set_ylim(w0, w1)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def coords(df: pd.DataFrame, spec: PitchSpec, end: bool = False) -> Tuple[pd.Series, pd.Series]:
    x = df["x2_plot"] if end else df["x_plot"]
    y = df["y2_plot"] if end else df["y_plot"]
    return pc(x, y, spec.is_vertical())

# =============================
# MARKER STUDIO
# =============================
MARKER_SHAPES = {"Circle": "o", "Square": "s", "Diamond": "D", "Triangle Up": "^",
                 "Triangle Down": "v", "Hexagon": "h", "Pentagon": "p", "Star": "*",
                 "Plus": "P", "X": "X"}


def marker_effects(ms: Dict, vt: Dict) -> List:
    fx = []
    if ms.get("glow"):
        fx.append(pe.withStroke(linewidth=ms.get("glow_width", 5.0), foreground=ms.get("glow_color", vt["accent"]), alpha=0.35))
    if ms.get("shadow"):
        fx.append(pe.SimplePatchShadow(offset=(1.4, -1.4), shadow_rgbFace="#000000", alpha=0.35))
    fx.append(pe.Normal())
    return fx


def resolve_marker(ms: Dict):
    m = MARKER_SHAPES.get(ms.get("shape", "Circle"), "o")
    rot = float(ms.get("rotation", 0) or 0)
    if rot:
        try:
            return MarkerStyle(m, transform=Affine2D().rotate_deg(rot))
        except Exception:
            return m
    return m


def scatter_points(ax, x, y, color, ms: Dict, vt: Dict, size_mult: float = 1.0,
                   zorder: Optional[float] = None, label: Optional[str] = None):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    jit = float(ms.get("jitter", 0) or 0)
    if jit > 0 and len(x):
        rng = np.random.default_rng(7)
        x = x + rng.uniform(-jit, jit, len(x))
        y = y + rng.uniform(-jit, jit, len(y))
    coll = ax.scatter(
        x, y, s=float(ms.get("size", 80)) * size_mult, c=color,
        marker=resolve_marker(ms), edgecolors=ms.get("edge_color", vt["line"]),
        linewidths=float(ms.get("edge_width", 1.1)), alpha=float(ms.get("alpha", 0.85)),
        zorder=(zorder if zorder is not None else float(ms.get("zorder", 6))), label=label,
    )
    coll.set_path_effects(marker_effects(ms, vt))
    return coll


# =============================
# ARROW STUDIO
# =============================
def draw_arrow(ax, p1: Tuple[float, float], p2: Tuple[float, float], color: str,
               ast_: Dict, vt: Dict, alpha_override: Optional[float] = None, zorder: float = 4.0):
    kind = ast_.get("kind", "Straight")
    lw = float(ast_.get("width", 1.6))
    alpha = float(alpha_override if alpha_override is not None else ast_.get("alpha", 0.72))
    head = float(ast_.get("head", 10))
    curv = float(ast_.get("curvature", 0.18))
    cap = ast_.get("linecap", "round")
    fx = []
    if ast_.get("glow"):
        fx.append(pe.withStroke(linewidth=lw + 3.5, foreground=color, alpha=0.25))
    if ast_.get("shadow"):
        fx.append(pe.SimpleLineShadow(offset=(1.1, -1.1), alpha=0.3))
    fx.append(pe.Normal())

    if kind in ("Comet", "Gradient Comet"):
        n = 16
        xs = np.linspace(p1[0], p2[0], n + 1)
        ys = np.linspace(p1[1], p2[1], n + 1)
        segs = np.stack([np.column_stack([xs[:-1], ys[:-1]]), np.column_stack([xs[1:], ys[1:]])], axis=1)
        lws = np.linspace(lw * 0.15, lw * 1.9, n)
        alphas = np.linspace(alpha * 0.15, alpha, n)
        if kind == "Gradient Comet":
            cmap = matplotlib.colormaps.get_cmap(ast_.get("cmap", "viridis"))
            cols = [(*cmap(i / max(1, n - 1))[:3], a) for i, a in enumerate(alphas)]
        else:
            base = matplotlib.colors.to_rgb(color)
            cols = [(*base, a) for a in alphas]
        lc = LineCollection(segs, linewidths=lws, colors=cols, capstyle=cap, zorder=zorder)
        lc.set_path_effects(fx)
        ax.add_collection(lc)
        ax.scatter([p2[0]], [p2[1]], s=(lw * 2.6) ** 2, c=[cols[-1][:3]], alpha=alpha, zorder=zorder + 0.1, lw=0)
        return

    style_map = {"Straight": ("-", "-|>", 0.0), "Curved": ("-", "-|>", curv),
                 "Bezier": ("-", "-|>", curv * 1.6), "Dashed": ("--", "-|>", 0.0),
                 "Dotted": (":", "-|>", 0.0), "Double Arrow": ("-", "<|-|>", 0.0)}
    ls, arrowstyle, rad = style_map.get(kind, ("-", "-|>", 0.0))
    ann = ax.annotate(
        "", xy=p2, xytext=p1,
        arrowprops=dict(arrowstyle=arrowstyle, color=color, lw=lw, alpha=alpha,
                        linestyle=ls, capstyle=cap, joinstyle=ast_.get("linejoin", "round"),
                        mutation_scale=head,
                        connectionstyle=f"arc3,rad={rad}" if rad else "arc3"),
        zorder=zorder,
    )
    ann.arrow_patch.set_path_effects(fx)


# =============================
# LABEL ENGINE — collision-aware smart labels
# =============================
class LabelEngine:
    def __init__(self, ax, vt: Dict, style: Dict):
        self.ax = ax
        self.vt = vt
        self.s = style
        self.placed: List = []
        self.count = 0

    def _bbox(self, artist):
        try:
            renderer = self.ax.figure.canvas.get_renderer()
        except Exception:
            self.ax.figure.canvas.draw()
            renderer = self.ax.figure.canvas.get_renderer()
        return artist.get_window_extent(renderer=renderer)

    def _overlaps(self, bb) -> bool:
        pad = 1.5
        for other in self.placed:
            if (bb.x0 - pad < other.x1 and bb.x1 + pad > other.x0 and
                    bb.y0 - pad < other.y1 and bb.y1 + pad > other.y0):
                return True
        return False

    def add(self, x: float, y: float, text: str, color: Optional[str] = None,
            fontsize: Optional[float] = None, weight: str = "bold", zorder: float = 9.0):
        s = self.s
        if not s.get("show", True) or not str(text).strip():
            return
        maxn = int(s.get("max_labels", 0) or 0)
        if maxn and self.count >= maxn:
            return
        fontsize = fontsize or s.get("size", 9)
        color = color or self.vt["text"]
        kw = dict(ha="center", va="center", fontsize=fontsize, color=color,
                  fontweight=weight, fontfamily=self.vt["font"],
                  rotation=float(s.get("rotation", 0) or 0), zorder=zorder)
        fx = []
        if s.get("halo", True):
            fx.append(pe.withStroke(linewidth=float(s.get("halo_width", 2.6)),
                                    foreground=s.get("halo_color", self.vt["pitch"])))
        if s.get("box"):
            kw["bbox"] = dict(boxstyle="round,pad=0.28", fc=self.vt["panel"],
                              ec=self.vt["grid"], alpha=0.92)
        off = float(s.get("offset", 1.6))
        candidates = [(0, off), (0, -off), (off, 0), (-off, 0),
                      (off, off), (-off, off), (off, -off), (-off, -off), (0, 0)]
        if not s.get("smart", True):
            candidates = [(0, s.get("fixed_dy", off))]
        t = None
        chosen = None
        for dx, dy in candidates:
            if t is not None:
                t.remove()
            t = self.ax.text(x + dx, y + dy, str(text), **kw)
            if fx:
                t.set_path_effects(fx)
            bb = self._bbox(t)
            if not self._overlaps(bb):
                chosen = (dx, dy, bb)
                break
        if chosen is None:
            if s.get("hide_overlapping", True):
                if t is not None:
                    t.remove()
                return
            chosen = (candidates[0][0], candidates[0][1], self._bbox(t))
        dx, dy, bb = chosen
        if s.get("leader_lines", True) and math.hypot(dx, dy) > off * 1.3:
            self.ax.plot([x, x + dx * 0.7], [y, y + dy * 0.7], color=self.vt["muted"],
                         lw=0.6, alpha=0.7, zorder=zorder - 0.1)
        self.placed.append(bb)
        self.count += 1


# =============================
# LEGEND ENGINE
# =============================
LEGEND_POSITIONS = {
    "Bottom": dict(loc="upper center", bbox_to_anchor=(0.5, -0.02)),
    "Top": dict(loc="lower center", bbox_to_anchor=(0.5, 1.02)),
    "Right (outside)": dict(loc="center left", bbox_to_anchor=(1.02, 0.5)),
    "Left (outside)": dict(loc="center right", bbox_to_anchor=(-0.02, 0.5)),
    "Inside top-left": dict(loc="upper left"),
    "Inside top-right": dict(loc="upper right"),
    "Inside bottom-left": dict(loc="lower left"),
    "Inside bottom-right": dict(loc="lower right"),
}


def parse_renames(text: str) -> Dict[str, str]:
    out = {}
    for pair in str(text or "").split(";"):
        if "=" in pair:
            a, b = pair.split("=", 1)
            if a.strip():
                out[a.strip().lower()] = b.strip()
    return out


def build_legend(ax, handles: List, labels: List[str], vt: Dict, lg: Dict, ctx: Dict):
    if not lg.get("show", True) or not handles:
        return
    renames = parse_renames(lg.get("renames", ""))
    hidden = [h.strip().lower() for h in str(lg.get("hide", "")).split(",") if h.strip()]
    order_txt = [o.strip().lower() for o in str(lg.get("order", "")).split(",") if o.strip()]
    items = [(h, l) for h, l in zip(handles, labels) if l.lower() not in hidden]
    if order_txt:
        items.sort(key=lambda hl: order_txt.index(hl[1].lower()) if hl[1].lower() in order_txt else 99)
    if not items:
        return
    hs = [h for h, _ in items]
    ls = [renames.get(l.lower(), l) for _, l in items]
    ncol = len(ls) if lg.get("orientation", "Horizontal") == "Horizontal" else 1
    pos = LEGEND_POSITIONS.get(lg.get("position", "Bottom"), LEGEND_POSITIONS["Bottom"])
    leg = ax.legend(hs, ls, ncol=max(1, min(ncol, 6)),
                    facecolor=vt["legend_face"], edgecolor=vt["legend_edge"],
                    labelcolor=vt["text"], fontsize=ctx.get("legend_size", 10),
                    framealpha=0.95 if lg.get("frame", True) else 0.0,
                    title=lg.get("title") or None, prop={"family": vt["font"]}, **pos)
    if leg.get_title():
        leg.get_title().set_color(vt["text"])
        leg.get_title().set_fontfamily(vt["font"])
    if not lg.get("frame", True):
        leg.get_frame().set_linewidth(0)


# =============================
# HEAT ENGINE
# =============================
def _gaussian_kernel1d(sigma: float) -> np.ndarray:
    radius = max(1, int(3 * sigma))
    xk = np.arange(-radius, radius + 1)
    k = np.exp(-(xk ** 2) / (2 * sigma ** 2))
    return k / k.sum()


def gaussian_blur(H: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return H
    k = _gaussian_kernel1d(sigma)
    out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 0, H)
    out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 1, out)
    return out


def heat_grid(x: np.ndarray, yw: np.ndarray, nx: int, ny: int,
              weights: Optional[np.ndarray] = None) -> np.ndarray:
    H, _, _ = np.histogram2d(x, yw, bins=[nx, ny], range=[[0, 100], [0, W]], weights=weights)
    return H  # H[ix, iy] — ix over length, iy over width


def scale_heat(H: np.ndarray, hs: Dict) -> Tuple[np.ndarray, float]:
    Hs = H.copy().astype(float)
    if hs.get("normalization", "Count") == "Percent" and Hs.sum() > 0:
        Hs = Hs / Hs.sum() * 100
    if hs.get("log_scale"):
        Hs = np.log1p(Hs)
    if hs.get("percentile_scale"):
        flat = Hs[Hs > 0]
        if len(flat):
            ranks = np.searchsorted(np.sort(flat), Hs, side="right") / len(flat) * 100
            Hs = np.where(Hs > 0, ranks, 0.0)
    thr_pct = float(hs.get("threshold", 0) or 0)
    vmin = 0.0
    if thr_pct > 0:
        pos = Hs[Hs > 0]
        if len(pos):
            vmin = float(np.percentile(pos, thr_pct))
    return Hs, vmin


def render_heat_array(ax, H: np.ndarray, spec: PitchSpec, hs: Dict, vt: Dict, mode: str = "imshow"):
    vertical = spec.is_vertical()
    Hs, vmin = scale_heat(H, hs)
    cmap = matplotlib.colormaps.get_cmap(hs.get("cmap", "Greens")).copy()
    cmap.set_under(alpha=0.0)
    alpha = float(hs.get("alpha", 0.65))
    interp = hs.get("interpolation", "bilinear")
    extent = (0, W, 0, 100) if vertical else (0, 100, 0, W)
    arr = Hs if vertical else Hs.T
    if mode == "contour":
        ny, nx = arr.shape[1], arr.shape[0]
        xs = np.linspace(extent[0], extent[1], arr.shape[1])
        ys = np.linspace(extent[2], extent[3], arr.shape[0])
        X, Y = np.meshgrid(xs, ys)
        levels = int(hs.get("levels", 10))
        vmax = arr.max() if arr.max() > 0 else 1
        lv = np.linspace(max(vmin, vmax * 0.02), vmax, max(2, levels))
        ax.contourf(X, Y, arr, levels=lv, cmap=cmap, alpha=alpha, zorder=2.2, extend="max")
    else:
        ax.imshow(arr, origin="lower", extent=extent, cmap=cmap, alpha=alpha,
                  interpolation=interp, vmin=max(vmin, 1e-9), aspect="auto", zorder=2.2)

# =============================
# PLUGIN REGISTRY
# =============================
VIZ_REGISTRY: Dict[str, Dict] = {}


def register_viz(name: str, category: str, renderer: Callable, uses_pitch: bool = True):
    """Additive plugin registration. New visualizations never edit existing ones."""
    VIZ_REGISTRY[name] = {"category": category, "render": renderer, "uses_pitch": uses_pitch}


def finalize_fig(fig, title: str, subtitle: str, ctx: Dict):
    vt = ctx["vt"]
    if ctx.get("show_title", True):
        fig.suptitle(title, fontsize=ctx.get("title_size", 20), color=vt["text"],
                     fontweight=vt["title_weight"], fontfamily=vt["font"], y=0.985)
        if subtitle:
            fig.text(0.5, 0.94, subtitle, ha="center",
                     fontsize=max(8, ctx.get("title_size", 20) - 8),
                     color=vt["muted"], fontfamily=vt["font"])
    return fig


def fig_to_bytes(fig, fmt: str = "png", dpi: int = 240, transparent: bool = False) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format=fmt, dpi=dpi, bbox_inches="tight", pad_inches=0.25,
                transparent=transparent,
                facecolor=("none" if transparent else fig.get_facecolor()))
    buf.seek(0)
    return buf.getvalue()


def outcome_color(row, ctx) -> str:
    ok = str(row.get("outcome", "")).lower() in SUCCESS_WORDS
    return ctx["colors"]["arrow"] if ok else ctx["colors"]["unsuccess"]


# =============================
# PITCH PANELS (draw into an ax) + registered figure renderers
# =============================
HEAT_TYPES = ["Gaussian KDE", "Adaptive KDE", "Smooth Density", "Grid Heatmap",
              "Hexbin Count", "Hexbin Mean Distance", "Zone Heatmap (thirds x lanes)",
              "Zone Heatmap (custom grid)", "Classic Histogram"]
HEAT_PRESETS = {
    "All selected events": None,
    "Touch density": None,
    "Pass density": lambda d: d[d["event_type"].str.lower() == "pass"],
    "Shot density": lambda d: d[d["event_type"].str.lower() == "shot"],
    "Recovery density": lambda d: d[d["event_type"].str.lower() == "recovery"],
    "Defensive pressure": lambda d: d[d["event_type"].str.lower().isin(DEF_EVENTS)],
    "Ball progression": lambda d: d[(d["event_type"].str.lower().isin(["pass", "carry"])) & (d["is_progressive"])],
    "Final third entries": lambda d: d[d["into_final_third"]],
    "Box entries": lambda d: d[d["into_box"]],
    "Crosses": lambda d: d[d["event_type"].str.lower() == "cross"],
}


def panel_heat(ax, df, ctx) -> str:
    spec: PitchSpec = ctx["spec"]
    hs = ctx["heat"]
    vt = ctx["vt"]
    preset = hs.get("preset", "All selected events")
    fn = HEAT_PRESETS.get(preset)
    d = fn(df) if fn else df
    d = d.dropna(subset=["x_plot", "y_plot"])
    n = len(d)
    if n == 0:
        return "No events for this selection"
    x = d["x_plot"].to_numpy()
    yw = d["y_plot"].to_numpy()
    htype = hs.get("type", "Gaussian KDE")
    vertical = spec.is_vertical()
    if htype in ("Gaussian KDE", "Adaptive KDE", "Smooth Density"):
        nx, ny = 200, 136
        H = heat_grid(x, yw, nx, ny)
        bw = float(hs.get("bandwidth", 3.0))
        sigma = bw * 2.0
        if htype == "Adaptive KDE":
            Hs1 = gaussian_blur(H, sigma * 0.6)
            Hs2 = gaussian_blur(H, sigma * 1.8)
            dens = Hs2 / (Hs2.max() + 1e-9)
            H = Hs1 * (1 - dens * 0.5) + Hs2 * (dens * 0.5)
        else:
            H = gaussian_blur(H, sigma)
        mode = "contour" if htype != "Smooth Density" else "imshow"
        render_heat_array(ax, H, spec, hs, vt, mode=mode)
    elif htype == "Classic Histogram":
        nb = int(hs.get("bins", 13))
        H = heat_grid(x, yw, nb, max(3, int(nb * 0.68)))
        render_heat_array(ax, H, spec, hs, vt, mode="imshow")
    elif htype == "Grid Heatmap":
        cell = float(hs.get("cell_size", 10))
        nx = max(2, int(round(100 / cell)))
        ny = max(2, int(round(W / cell)))
        H = heat_grid(x, yw, nx, ny)
        Hs, vmin = scale_heat(H, hs)
        cmap = matplotlib.colormaps.get_cmap(hs.get("cmap", "Greens"))
        vmax = Hs.max() if Hs.max() > 0 else 1
        eng = LabelEngine(ax, vt, ctx["labels"])
        for i in range(nx):
            for j in range(ny):
                v = Hs[i, j]
                if v < max(vmin, 1e-9):
                    continue
                x0, y0 = i * 100 / nx, j * W / ny
                px, py = pc(x0, y0, vertical)
                wdt, hgt = (W / ny, 100 / nx) if vertical else (100 / nx, W / ny)
                ax.add_patch(Rectangle((px, py), wdt, hgt, color=cmap(v / vmax),
                                       alpha=float(hs.get("alpha", 0.65)), zorder=2.2, lw=0))
                if hs.get("cell_labels") and H[i, j] > 0:
                    cx, cy = pc(x0 + 50 / nx, y0 + W / ny / 2, vertical)
                    eng.add(cx, cy, f"{int(H[i, j])}", fontsize=max(6, ctx["label_size"] - 3))
    elif htype.startswith("Hexbin"):
        px, py = pc(x, yw, vertical)
        C = None
        reduce_fn = np.mean
        if htype == "Hexbin Mean Distance":
            C = d["distance"].fillna(0).to_numpy()
        cmap = matplotlib.colormaps.get_cmap(hs.get("cmap", "Greens")).copy()
        cmap.set_under(alpha=0.0)
        hb = ax.hexbin(px, py, C=C, reduce_C_function=reduce_fn,
                       gridsize=int(hs.get("gridsize", 22)),
                       extent=(0, W, 0, 100) if vertical else (0, 100, 0, W),
                       cmap=cmap, alpha=float(hs.get("alpha", 0.65)),
                       mincnt=1, linewidths=0.4, edgecolors=vt["bg"], zorder=2.2,
                       bins="log" if hs.get("log_scale") else None)
    elif htype.startswith("Zone Heatmap"):
        if "custom" in htype:
            cell = float(hs.get("cell_size", 20))
            nx = max(2, int(round(100 / cell)))
            ny = max(2, int(round(100 / cell * 0.68)))
        else:
            nx, ny = 3, 3
        H = heat_grid(x, yw, nx, ny)
        total = H.sum()
        cmap = matplotlib.colormaps.get_cmap(hs.get("cmap", "Greens"))
        vmax = H.max() if H.max() > 0 else 1
        eng = LabelEngine(ax, vt, dict(ctx["labels"], smart=False, hide_overlapping=False))
        for i in range(nx):
            for j in range(ny):
                x0, y0 = i * 100 / nx, j * W / ny
                px, py = pc(x0, y0, vertical)
                wdt, hgt = (W / ny, 100 / nx) if vertical else (100 / nx, W / ny)
                ax.add_patch(Rectangle((px, py), wdt, hgt, color=cmap(H[i, j] / vmax),
                                       alpha=float(hs.get("alpha", 0.65)), zorder=2.2,
                                       lw=0.6, ec=vt["grid"]))
                cx, cy = pc(x0 + 50 / nx, y0 + W / ny / 2, vertical)
                if total > 0:
                    ax.text(cx, cy, pct(H[i, j], total), ha="center", va="center",
                            fontsize=ctx["label_size"], color=vt["text"], fontweight="bold",
                            fontfamily=vt["font"], zorder=7,
                            path_effects=[pe.withStroke(linewidth=3, foreground=vt["pitch"])])
    return f"{preset} | {htype} | Events: {n}"


def viz_heat_studio(df, ctx):
    fig, ax = new_pitch_fig(ctx["vt"], ctx["spec"], ctx)
    sub = panel_heat(ax, df, ctx)
    return finalize_fig(fig, ctx["title"], sub, ctx)


def panel_arrow_map(ax, df, ctx, default_event: str) -> str:
    spec = ctx["spec"]
    vt = ctx["vt"]
    if ctx.get("respect_filter"):
        d = df.copy()
    else:
        d = df[df["event_type"].str.lower() == default_event].copy()
    d = d.dropna(subset=["x_plot", "y_plot", "x2_plot", "y2_plot"])
    for _, r in d.iterrows():
        rx, ry = pc(r["x_plot"], r["y_plot"], spec.is_vertical())
        rx2, ry2 = pc(r["x2_plot"], r["y2_plot"], spec.is_vertical())
        ok = str(r.get("outcome", "")).lower() in SUCCESS_WORDS
        col = ctx["colors"]["arrow"] if ok else ctx["colors"]["unsuccess"]
        draw_arrow(ax, (rx, ry), (rx2, ry2), col, ctx["arrow"], vt,
                   alpha_override=None if ok else float(ctx["arrow"].get("alpha", 0.72)) * 0.6)
    if ctx["labels"].get("show_players"):
        eng = LabelEngine(ax, vt, ctx["labels"])
        for _, r in d.iterrows():
            rx, ry = pc(r["x_plot"], r["y_plot"], spec.is_vertical())
            eng.add(rx, ry, str(r.get("shirt_number", "")).replace(".0", "") or str(r.get("player", ""))[:12])
    handles = [Line2D([0], [0], color=ctx["colors"]["arrow"], lw=2),
               Line2D([0], [0], color=ctx["colors"]["unsuccess"], lw=2)]
    build_legend(ax, handles, ["Successful", "Unsuccessful"], vt, ctx["legend"], ctx)
    return f"{default_event.title()} events: {len(d)}"


def make_arrow_viz(event: str):
    def _render(df, ctx):
        fig, ax = new_pitch_fig(ctx["vt"], ctx["spec"], ctx)
        sub = panel_arrow_map(ax, df, ctx, event)
        return finalize_fig(fig, ctx["title"], sub, ctx)
    return _render


def panel_shots(ax, df, ctx) -> str:
    spec, vt = ctx["spec"], ctx["vt"]
    d = df[df["event_type"].str.lower() == "shot"].dropna(subset=["x_plot", "y_plot"]).copy()
    if len(d):
        goal_mask = d["shot_result"].str.lower().eq("goal")
        sizes = (105 - d["shot_distance"].fillna(60).clip(0, 100)) / 35
        x, y = coords(d, spec)
        ms = ctx["marker"]
        ng = scatter_points(ax, x[~goal_mask], y[~goal_mask], ctx["colors"]["shot"], ms, vt,
                            size_mult=float(np.clip(sizes[~goal_mask].mean() if (~goal_mask).any() else 1, 0.5, 3)))
        g = scatter_points(ax, x[goal_mask], y[goal_mask], ctx["colors"]["goal"],
                           dict(ms, alpha=0.95), vt, size_mult=1.4, zorder=float(ms.get("zorder", 6)) + 1)
        eng = LabelEngine(ax, vt, ctx["labels"])
        if ctx["labels"].get("show_players"):
            for _, r in d[goal_mask].iterrows():
                rx, ry = pc(r["x_plot"], r["y_plot"], spec.is_vertical())
                eng.add(rx, ry, str(r.get("player", ""))[:14])
        handles = [Line2D([0], [0], marker="o", ls="", mfc=ctx["colors"]["shot"], mec=vt["line"]),
                   Line2D([0], [0], marker="o", ls="", mfc=ctx["colors"]["goal"], mec=ctx["colors"]["goal"])]
        build_legend(ax, handles, ["No Goal", "Goal"], vt, ctx["legend"], ctx)
    return f"Shots: {len(d)} | Size = closer to goal, not xG"


def viz_shots(df, ctx):
    fig, ax = new_pitch_fig(ctx["vt"], ctx["spec"], ctx)
    sub = panel_shots(ax, df, ctx)
    return finalize_fig(fig, ctx["title"], sub, ctx)


def panel_defensive(ax, df, ctx) -> str:
    spec, vt = ctx["spec"], ctx["vt"]
    d = df[df["event_type"].str.lower().isin(DEF_EVENTS)].dropna(subset=["x_plot", "y_plot"]).copy()
    color_map = {"recovery": vt["success"], "interception": vt["accent"], "duel": vt["warning"],
                 "clearance": vt["danger"], "tackle": vt["accent2"], "block": vt["grey"]}
    handles, labels = [], []
    for ev, sub in d.groupby(d["event_type"].str.lower()):
        x, y = coords(sub, spec)
        scatter_points(ax, x, y, color_map.get(ev, vt["accent"]), ctx["marker"], vt)
        handles.append(Line2D([0], [0], marker="o", ls="", mfc=color_map.get(ev, vt["accent"]), mec=vt["line"]))
        labels.append(ev.title())
    build_legend(ax, handles, labels, vt, ctx["legend"], ctx)
    return f"Defensive actions: {len(d)}"


def viz_defensive(df, ctx):
    fig, ax = new_pitch_fig(ctx["vt"], ctx["spec"], ctx)
    sub = panel_defensive(ax, df, ctx)
    return finalize_fig(fig, ctx["title"], sub, ctx)


def panel_start_end(ax, df, ctx, event_name: str) -> str:
    spec, vt = ctx["spec"], ctx["vt"]
    d = df[df["event_type"].str.lower() == event_name].dropna(
        subset=["x_plot", "y_plot", "x2_plot", "y2_plot"]).copy()
    x, y = coords(d, spec)
    x2, y2 = coords(d, spec, end=True)
    scatter_points(ax, x, y, ctx["colors"]["start"], ctx["marker"], vt)
    scatter_points(ax, x2, y2, ctx["colors"]["end"], ctx["marker"], vt)
    handles = [Line2D([0], [0], marker="o", ls="", mfc=ctx["colors"]["start"], mec=vt["line"]),
               Line2D([0], [0], marker="o", ls="", mfc=ctx["colors"]["end"], mec=vt["line"])]
    build_legend(ax, handles, ["Start Event", "End Event"], vt, ctx["legend"], ctx)
    return f"{event_name.title()} starts and ends: {len(d)}"


def viz_start_end(df, ctx):
    fig, ax = new_pitch_fig(ctx["vt"], ctx["spec"], ctx)
    sub = panel_start_end(ax, df, ctx, ctx["aux"].get("start_end_event", "pass"))
    return finalize_fig(fig, ctx["title"], sub, ctx)


def panel_zone_pct(ax, df, ctx, mode: str) -> str:
    spec, vt = ctx["spec"], ctx["vt"]
    d = df.dropna(subset=["x", "y"]).copy()
    total = len(d)
    vertical = spec.is_vertical()
    if mode == "Pitch Thirds":
        zones = [(0, 0, 33.33, W, "Def 3rd", (d["x"] < 33.33).sum()),
                 (33.33, 0, 33.34, W, "Mid 3rd", ((d["x"] >= 33.33) & (d["x"] < 66.67)).sum()),
                 (66.67, 0, 33.33, W, "Final 3rd", (d["x"] >= 66.67).sum())]
    else:
        zones = [(0, 0, 100, W / 3, "Left", (d["y"] < 33.33).sum()),
                 (0, W / 3, 100, W / 3, "Center", ((d["y"] >= 33.33) & (d["y"] < 66.67)).sum()),
                 (0, 2 * W / 3, 100, W / 3, "Right", (d["y"] >= 66.67).sum())]
    counts = [z[5] for z in zones]
    mx = max(counts) if counts else 1
    for (x0, y0, wdt, hgt, name, cnt) in zones:
        alpha = 0.14 + 0.24 * (cnt / mx if mx else 0)
        px, py = pc(x0, y0, vertical)
        rw, rh = (hgt, wdt) if vertical else (wdt, hgt)
        ax.add_patch(Rectangle((px, py), rw, rh, color=ctx["colors"]["zone"], alpha=alpha, zorder=2.2, lw=0))
        cx, cy = pc(x0 + wdt / 2, y0 + hgt / 2, vertical)
        ax.text(cx, cy, pct(cnt, total), ha="center", va="center", fontsize=ctx["title_size"],
                color=vt["text"], fontweight="bold", fontfamily=vt["font"], zorder=7,
                bbox=dict(boxstyle="round,pad=0.35", fc=vt["panel"], ec="none", alpha=0.92))
        ox, oy = pc(x0 + wdt / 2, y0 + hgt / 2 - (6 if not vertical else 0), vertical)
        if vertical:
            oy -= 6
        ax.text(ox, oy, name, ha="center", va="center", fontsize=ctx["label_size"],
                color=vt["muted"], fontfamily=vt["font"], zorder=7)
    return f"Based on {total} selected events"


def viz_zone_pct(df, ctx):
    spec2 = ctx["spec"]
    save_mode = spec2.thirds_mode
    spec2.thirds_mode = "None"
    fig, ax = new_pitch_fig(ctx["vt"], spec2, ctx)
    spec2.thirds_mode = save_mode
    sub = panel_zone_pct(ax, df, ctx, ctx["aux"].get("zone_mode", "Pitch Thirds"))
    return finalize_fig(fig, ctx["title"], sub, ctx)


# --- Sequence map (v3 logic preserved, engine-rendered) ---
def select_sequence_dataframe(df: pd.DataFrame, sequence_mode: str, sequence_id: str) -> pd.DataFrame:
    if "sequence_id" not in df.columns or df["sequence_id"].astype(str).str.strip().eq("").all():
        return df.iloc[0:0].copy()
    base = df[df["sequence_id"].astype(str).str.strip() != ""].copy()
    if base.empty:
        return base
    base["_seq"] = base["sequence_id"].astype(str)
    period_ser = pd.to_numeric(base["period"], errors="coerce").fillna(1) if "period" in base.columns else pd.Series(1, index=base.index)
    base["_time_sort"] = period_ser * 10000 + base["time_min"].fillna(0)
    if sequence_mode == "Specific sequence" and str(sequence_id).strip():
        chosen = str(sequence_id)
    elif sequence_mode == "Latest shot sequence":
        shots = base[base["event_type"].str.lower().eq("shot")].sort_values("_time_sort")
        chosen = str(shots["_seq"].iloc[-1]) if len(shots) else str(base["_seq"].iloc[-1])
    elif sequence_mode == "Latest goal sequence":
        goals = base[(base["event_type"].str.lower().eq("shot")) &
                     (base["shot_result"].str.lower().eq("goal"))].sort_values("_time_sort")
        chosen = str(goals["_seq"].iloc[-1]) if len(goals) else str(base["_seq"].iloc[-1])
    elif sequence_mode == "Longest sequence":
        chosen = str(base["_seq"].value_counts().idxmax())
    else:
        chosen = str(base["_seq"].iloc[-1])
    out = base[base["_seq"].eq(chosen)].copy()
    sort_cols = [c for c in ["period", "minute", "second"] if c in out.columns]
    out = out.sort_values(sort_cols) if sort_cols else out.sort_values("time_min")
    return out.drop(columns=["_seq", "_time_sort"], errors="ignore")


def panel_sequence(ax, df, ctx) -> str:
    spec, vt = ctx["spec"], ctx["vt"]
    d = select_sequence_dataframe(df, ctx["aux"].get("sequence_mode", "Longest sequence"),
                                  ctx["aux"].get("sequence_id", ""))
    if d.empty:
        ax.text(0.5, 0.5, "No sequence_id found after filters", transform=ax.transAxes,
                ha="center", va="center", color=vt["text"], fontsize=ctx["title_size"],
                fontweight="bold", fontfamily=vt["font"])
        return "Add/use sequence_id to draw possession chains"
    seq_label = str(d["sequence_id"].iloc[0])
    vertical = spec.is_vertical()
    arrowed = d[d["event_type"].str.lower().isin(ARROW_EVENTS)].dropna(
        subset=["x_plot", "y_plot", "x2_plot", "y2_plot"])
    eng = LabelEngine(ax, vt, ctx["labels"])
    for i, (_, r) in enumerate(arrowed.iterrows(), start=1):
        p1 = pc(r["x_plot"], r["y_plot"], vertical)
        p2 = pc(r["x2_plot"], r["y2_plot"], vertical)
        ev = str(r.get("event_type", "")).lower()
        ok = str(r.get("outcome", "")).lower() in SUCCESS_WORDS
        if ev in ("carry", "dribble"):
            col, kind = ctx["colors"]["carry"], "Dotted"
        elif ev == "cross":
            col, kind = ctx["colors"]["cross"], "Dashed"
        else:
            col = ctx["colors"]["arrow"] if ok else ctx["colors"]["unsuccess"]
            kind = ctx["arrow"].get("kind", "Straight")
        draw_arrow(ax, p1, p2, col, dict(ctx["arrow"], kind=kind if ev != "pass" else ctx["arrow"].get("kind", "Straight")), vt)
        if ctx["aux"].get("show_sequence_numbers", True):
            mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
            ax.text(mx, my, str(i), ha="center", va="center",
                    fontsize=max(7, ctx["label_size"] - 1), color=vt["bg"],
                    fontfamily=vt["font"],
                    bbox=dict(boxstyle="circle,pad=0.22", fc=vt["text"], ec=vt["grid"], alpha=0.92),
                    zorder=8)
    points = d.dropna(subset=["x_plot", "y_plot"]).copy()
    if len(points):
        cols = []
        for ev, sr in zip(points["event_type"].str.lower(), points["shot_result"].str.lower()):
            if ev == "shot" and sr == "goal":
                cols.append(ctx["colors"]["goal"])
            elif ev == "shot":
                cols.append(ctx["colors"]["end"])
            elif ev in ("carry", "dribble"):
                cols.append(ctx["colors"]["carry"])
            elif ev == "cross":
                cols.append(ctx["colors"]["cross"])
            else:
                cols.append(ctx["colors"]["start"])
        x, y = coords(points, spec)
        scatter_points(ax, x, y, cols, ctx["marker"], vt)
        for _, r in points.iterrows():
            label = str(r.get("shirt_number", "")).replace(".0", "")
            if label and label.lower() != "nan":
                rx, ry = pc(r["x_plot"], r["y_plot"], vertical)
                eng.add(rx, ry, label, zorder=9.5)
    final = d.iloc[-1]
    if str(final["event_type"]).lower() in ARROW_EVENTS and pd.notna(final["x2_plot"]) and pd.notna(final["y2_plot"]):
        fx, fy = pc(final["x2_plot"], final["y2_plot"], vertical)
    else:
        fx, fy = pc(final["x_plot"], final["y_plot"], vertical)
    scatter_points(ax, [fx], [fy], ctx["colors"]["end"],
                   dict(ctx["marker"], size=float(ctx["marker"].get("size", 80)) * 1.55,
                        edge_color=vt["text"], alpha=0.95), vt,
                   zorder=float(ctx["marker"].get("zorder", 6)) + 4)
    handles = [Line2D([0], [0], color=ctx["colors"]["arrow"], lw=2),
               Line2D([0], [0], color=ctx["colors"]["carry"], lw=2, linestyle=":"),
               Line2D([0], [0], color=ctx["colors"]["cross"], lw=2, linestyle="--"),
               Line2D([0], [0], marker="o", ls="", mfc=ctx["colors"]["end"], mec=vt["text"])]
    build_legend(ax, handles, ["Pass", "Carry/Dribble", "Cross", "End Event"], vt, ctx["legend"], ctx)
    final_event = str(d["event_type"].iloc[-1]).title()
    final_result = str(d["shot_result"].iloc[-1]) if "shot_result" in d.columns else ""
    tail = f" - {final_result}" if final_result and final_result.lower() != "nan" else ""
    return f"Sequence {seq_label} | Events: {len(d)} | End: {final_event}{tail}"


def viz_sequence(df, ctx):
    fig, ax = new_pitch_fig(ctx["vt"], ctx["spec"], ctx)
    sub = panel_sequence(ax, df, ctx)
    return finalize_fig(fig, ctx["title"], sub, ctx)

# =============================
# NON-PITCH CHARTS
# =============================
def new_standard_fig(ctx, w=10.5, h=6.2, ax=None):
    vt = ctx["vt"]
    if ax is None:
        fig, ax = plt.subplots(figsize=(w, h))
    else:
        fig = ax.figure
    fig.patch.set_facecolor(vt["bg"])
    ax.set_facecolor(vt["panel"])
    ax.tick_params(colors=vt["text"], labelsize=ctx["label_size"])
    for lbl in ax.get_xticklabels() + ax.get_yticklabels():
        lbl.set_fontfamily(vt["font"])
    for spine in ax.spines.values():
        spine.set_color(vt["grid"])
    ax.grid(axis="y", color=vt["grid"], alpha=0.35, linestyle="--")
    return fig, ax


def _annotate_barh(ax, counts, ctx):
    vt = ctx["vt"]
    mx = max(counts.values) if len(counts) else 1
    for i, v in enumerate(counts.values):
        ax.text(v + mx * 0.01, i, str(v), va="center", color=vt["text"],
                fontsize=ctx["label_size"], fontfamily=vt["font"])


def panel_event_bar(ax, df, ctx) -> str:
    vt = ctx["vt"]
    new_standard_fig(ctx, ax=ax)
    counts = df["event_type"].str.lower().value_counts().sort_values(ascending=True)
    ax.barh(counts.index, counts.values, color=ctx["colors"]["bar"])
    ax.set_xlabel("Count", color=vt["muted"], fontfamily=vt["font"])
    _annotate_barh(ax, counts, ctx)
    return "Event distribution"


def viz_event_bar(df, ctx):
    fig, ax = new_standard_fig(ctx)
    sub = panel_event_bar(ax, df, ctx)
    return finalize_fig(fig, ctx["title"], sub, ctx)


def panel_player_bar(ax, df, ctx, top_n: int) -> str:
    vt = ctx["vt"]
    new_standard_fig(ctx, ax=ax)
    d = df[df["player"].astype(str).str.strip() != ""]
    counts = d["player"].value_counts().head(top_n).sort_values()
    ax.barh(counts.index, counts.values, color=ctx["colors"]["bar"])
    ax.set_xlabel("Events", color=vt["muted"], fontfamily=vt["font"])
    _annotate_barh(ax, counts, ctx)
    return f"Top {len(counts)} players"


def viz_player_bar(df, ctx):
    fig, ax = new_standard_fig(ctx)
    sub = panel_player_bar(ax, df, ctx, int(ctx["aux"].get("top_n", 10)))
    return finalize_fig(fig, ctx["title"], sub, ctx)


def panel_pass_direction(ax, df, ctx) -> str:
    vt = ctx["vt"]
    new_standard_fig(ctx, ax=ax)
    passes = df[df["event_type"].str.lower() == "pass"]
    vals = pd.Series({"Forward": int(passes["is_forward"].sum()),
                      "Lateral": int(passes["is_lateral"].sum()),
                      "Backward": int(passes["is_backward"].sum())})
    ax.bar(vals.index, vals.values, color=[ctx["colors"]["bar"], vt["grey"], ctx["colors"]["unsuccess"]])
    ax.set_ylabel("Passes", color=vt["muted"], fontfamily=vt["font"])
    mx = max(vals.values.max(), 1)
    for i, v in enumerate(vals.values):
        ax.text(i, v + mx * 0.02, str(v), ha="center", color=vt["text"],
                fontsize=ctx["label_size"], fontfamily=vt["font"])
    return f"Passes: {len(passes)}"


def viz_pass_direction(df, ctx):
    fig, ax = new_standard_fig(ctx)
    sub = panel_pass_direction(ax, df, ctx)
    return finalize_fig(fig, ctx["title"], sub, ctx)


def panel_shot_summary(ax, df, ctx) -> str:
    vt = ctx["vt"]
    new_standard_fig(ctx, ax=ax)
    shots = df[df["event_type"].str.lower() == "shot"]
    result = shots["shot_result"].replace("", "Unknown").value_counts().sort_values(ascending=True) \
        if len(shots) else pd.Series(dtype=int)
    if len(result):
        ax.barh(result.index, result.values, color=ctx["colors"]["bar"])
        _annotate_barh(ax, result, ctx)
    ax.set_xlabel("Shots", color=vt["muted"], fontfamily=vt["font"])
    return f"Total shots: {len(shots)}"


def viz_shot_summary(df, ctx):
    fig, ax = new_standard_fig(ctx)
    sub = panel_shot_summary(ax, df, ctx)
    return finalize_fig(fig, ctx["title"], sub, ctx)


def panel_timeline(ax, df, ctx, event_focus: str) -> str:
    vt = ctx["vt"]
    new_standard_fig(ctx, ax=ax)
    d = df.dropna(subset=["time_min"]).copy()
    if event_focus != "All":
        d = d[d["event_type"].str.lower() == event_focus]
    bins = np.arange(0, max(96, int(d["time_min"].max() if len(d) else 90) + 6), 5)
    d["bin"] = pd.cut(d["time_min"], bins=bins, labels=bins[:-1], include_lowest=True)
    trend = d.groupby("bin", observed=False).size()
    x = trend.index.astype(float)
    y = trend.values
    ax.plot(x, y, marker="o", color=ctx["colors"]["line"], lw=ctx["aux"].get("line_width", 2.4),
            label="Events per 5 minutes")
    if len(y) >= 3:
        roll = pd.Series(y).rolling(3, min_periods=1).mean().values
        ax.plot(x, roll, color=ctx["colors"]["trend"], lw=ctx["aux"].get("line_width", 2.4),
                linestyle="--", label="3-bin trend")
    ax.set_xlabel("Minute", color=vt["muted"], fontfamily=vt["font"])
    ax.set_ylabel("Events", color=vt["muted"], fontfamily=vt["font"])
    if ctx["legend"].get("show", True):
        ax.legend(facecolor=vt["legend_face"], edgecolor=vt["legend_edge"], labelcolor=vt["text"],
                  fontsize=ctx["legend_size"], prop={"family": vt["font"]})
    return f"Timeline: {event_focus}"


def viz_timeline(df, ctx):
    fig, ax = new_standard_fig(ctx)
    sub = panel_timeline(ax, df, ctx, ctx["aux"].get("timeline_focus", "All"))
    return finalize_fig(fig, ctx["title"], sub, ctx)


def panel_match_trend(ax, df, ctx, metric: str) -> str:
    vt = ctx["vt"]
    new_standard_fig(ctx, ax=ax)
    base = df.copy()
    if "match_id" not in base.columns or base["match_id"].astype(str).str.strip().eq("").all():
        base["match_id"] = "Selected Data"
    if metric == "Shots":
        g = base[base["event_type"].str.lower() == "shot"].groupby("match_id").size()
    elif metric == "Final third entries":
        g = base[(base["event_type"].str.lower() == "pass") & (base["into_final_third"])].groupby("match_id").size()
    elif metric == "Box entries":
        g = base[(base["event_type"].str.lower().isin(["pass", "carry"])) & (base["into_box"])].groupby("match_id").size()
    else:
        g = base.groupby("match_id").size()
    g = g.sort_index()
    ax.plot(range(len(g)), g.values, marker="o", color=ctx["colors"]["line"],
            lw=ctx["aux"].get("line_width", 2.4))
    ax.set_xticks(range(len(g)))
    ax.set_xticklabels(g.index, rotation=20, ha="right", fontfamily=vt["font"])
    ax.set_ylabel(metric, color=vt["muted"], fontfamily=vt["font"])
    return f"Trend by match: {metric}"


def viz_match_trend(df, ctx):
    fig, ax = new_standard_fig(ctx)
    sub = panel_match_trend(ax, df, ctx, ctx["aux"].get("trend_metric", "All Events"))
    return finalize_fig(fig, ctx["title"], sub, ctx)


# =============================
# METRICS, TABLES & SUMMARY CARDS
# =============================
def compute_metrics(d: pd.DataFrame) -> Dict[str, float]:
    passes = d[d["event_type"].str.lower() == "pass"]
    shots = d[d["event_type"].str.lower() == "shot"]
    crosses = d[d["event_type"].str.lower() == "cross"]
    defensive = d[d["event_type"].str.lower().isin(DEF_EVENTS)]
    carries = d[d["event_type"].str.lower() == "carry"]
    on_target = shots["shot_result"].str.lower().isin(["goal", "saved", "on target", "on_target"]).sum()
    return {
        "Events": len(d),
        "Passes": len(passes),
        "Pass Accuracy %": round(is_success(passes["outcome"]).mean() * 100, 1) if len(passes) else 0.0,
        "Forward Pass %": round(passes["is_forward"].mean() * 100, 1) if len(passes) else 0.0,
        "Progressive Passes": int(((passes["is_progressive"]).fillna(False)).sum()),
        "Progressive Carries": int(((carries["is_progressive"]).fillna(False)).sum()),
        "Final 3rd Entries": int(d["into_final_third"].fillna(False).sum()),
        "Box Entries": int(d["into_box"].fillna(False).sum()),
        "Touches in Box": int(d["in_box"].fillna(False).sum()),
        "Crosses": len(crosses),
        "Shots": len(shots),
        "Shots on Target": int(on_target),
        "Goals": safe_count(shots, "shot_result", "Goal"),
        "Avg Shot Distance": round(shots["shot_distance"].mean(), 1) if len(shots) else 0.0,
        "Defensive Actions": len(defensive),
        "High Regains %": round((defensive["x"] >= 66.67).mean() * 100, 1) if len(defensive) else 0.0,
    }


HIGHER_BETTER = {m: True for m in ["Events", "Passes", "Pass Accuracy %", "Forward Pass %",
                                   "Progressive Passes", "Progressive Carries", "Final 3rd Entries",
                                   "Box Entries", "Touches in Box", "Crosses", "Shots",
                                   "Shots on Target", "Goals", "Defensive Actions", "High Regains %"]}
HIGHER_BETTER["Avg Shot Distance"] = False


def per_match_metric_frame(df_all: pd.DataFrame) -> pd.DataFrame:
    base = df_all.copy()
    if base["match_id"].astype(str).str.strip().eq("").all():
        base["match_id"] = "Selected Data"
    rows = {}
    for mid, g in base.groupby(base["match_id"].astype(str)):
        rows[mid] = compute_metrics(g)
    return pd.DataFrame(rows).T


def viz_stat_table(df, ctx):
    """Professional statistical table: metric / value / rank / percentile / mini bar."""
    vt = ctx["vt"]
    frame = per_match_metric_frame(ctx["aux"]["df_all"])
    current = compute_metrics(df)
    metrics = list(current.keys())
    n = len(metrics)
    fig_h = 0.52 * n + 1.6
    fig, ax = plt.subplots(figsize=(10.8, fig_h))
    fig.patch.set_facecolor(vt["bg"])
    ax.set_facecolor(vt["bg"])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, n + 1.3)
    ax.axis("off")
    headers = [("METRIC", 2, "left"), ("VALUE", 44, "right"), ("RANK", 56, "right"),
               ("PERCENTILE", 96, "right")]
    for txt, xh, al in headers:
        ax.text(xh, n + 0.75, txt, ha=al, va="center", fontsize=ctx["label_size"],
                color=vt["muted"], fontweight="bold", fontfamily=vt["font"])
    ax.plot([1, 99], [n + 0.4, n + 0.4], color=vt["text"], lw=1.4)
    nmatch = len(frame)
    for i, m in enumerate(metrics):
        yrow = n - i - 0.15
        if i % 2 == 0:
            ax.add_patch(Rectangle((0.5, yrow - 0.42), 99, 0.9, color=vt["table_zebra"],
                                   alpha=0.28, lw=0, zorder=0.5))
        val = current[m]
        series = frame[m] if m in frame.columns else pd.Series([val])
        asc = not HIGHER_BETTER.get(m, True)
        if nmatch > 1:
            rank = int((series.sort_values(ascending=asc).values.tolist().index(
                min(series.values, key=lambda v: abs(v - val)))) + 1) if len(series) else 1
            ranks = series.rank(pct=True, ascending=not asc)
            pcile = float(np.interp(val, np.sort(series.values), np.sort(ranks.values))) * 100
            rank_txt = f"{rank}/{nmatch}"
        else:
            pcile = 50.0
            rank_txt = "—"
        good = pcile >= 66
        bad = pcile <= 33
        vc = vt["success"] if good else (vt["danger"] if bad else vt["text"])
        ax.text(2, yrow, m, ha="left", va="center", fontsize=ctx["label_size"] + 1,
                color=vt["text"], fontfamily=vt["font"])
        ax.text(44, yrow, f"{val:g}", ha="right", va="center", fontsize=ctx["label_size"] + 1,
                color=vc, fontweight="bold", fontfamily=vt["font"])
        ax.text(56, yrow, rank_txt, ha="right", va="center", fontsize=ctx["label_size"],
                color=vt["muted"], fontfamily=vt["font"])
        # mini percentile bar
        bx0, bx1 = 60, 96
        ax.add_patch(Rectangle((bx0, yrow - 0.16), bx1 - bx0, 0.32, color=vt["grid"],
                               alpha=0.5, lw=0, zorder=1))
        ax.add_patch(Rectangle((bx0, yrow - 0.16), (bx1 - bx0) * pcile / 100, 0.32,
                               color=(vt["success"] if good else vt["danger"] if bad else vt["accent"]),
                               alpha=0.9, lw=0, zorder=2))
        ax.text(bx1 + 1.5, yrow, f"{pcile:.0f}", ha="left", va="center",
                fontsize=ctx["label_size"] - 1, color=vt["muted"], fontfamily=vt["font"])
    sub = f"vs {nmatch} match(es) in dataset" if nmatch > 1 else "single match — percentiles need multiple matches"
    return finalize_fig(fig, ctx["title"], sub, ctx)


CARD_METRICS = ["Shots", "Shots on Target", "Goals", "Touches in Box", "Box Entries",
                "Final 3rd Entries", "Progressive Passes", "Crosses", "Pass Accuracy %",
                "Defensive Actions", "High Regains %", "Progressive Carries"]


def panel_cards(fig, gs_slot, df, ctx, metrics: Optional[List[str]] = None, ncols: int = 4):
    vt = ctx["vt"]
    metrics = metrics or CARD_METRICS[:8]
    frame = per_match_metric_frame(ctx["aux"]["df_all"])
    current = compute_metrics(df)
    nrows = math.ceil(len(metrics) / ncols)
    inner = gridspec.GridSpecFromSubplotSpec(nrows, ncols, subplot_spec=gs_slot,
                                             wspace=0.18, hspace=0.35)
    for i, m in enumerate(metrics):
        ax = fig.add_subplot(inner[i // ncols, i % ncols])
        ax.set_facecolor(vt["bg"])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.add_patch(FancyBboxPatch((0.02, 0.04), 0.96, 0.92,
                                    boxstyle="round,pad=0.02,rounding_size=0.06",
                                    fc=vt["card_face"], ec=vt["card_edge"], lw=1.1, zorder=1))
        val = current.get(m, 0)
        ax.text(0.5, 0.68, f"{val:g}", ha="center", va="center", fontsize=ctx["title_size"],
                color=vt["text"], fontweight="heavy", fontfamily=vt["font"], zorder=3)
        ax.text(0.5, 0.30, m.upper(), ha="center", va="center",
                fontsize=max(6.5, ctx["label_size"] - 3), color=vt["muted"],
                fontfamily=vt["font"], zorder=3)
        # trend vs mean of other matches + sparkline
        if m in frame.columns and len(frame) > 1:
            series = frame[m].astype(float)
            others = series.mean()
            delta = float(val) - others
            better = (delta >= 0) == HIGHER_BETTER.get(m, True)
            arrow = "▲" if delta >= 0 else "▼"
            ax.text(0.5, 0.12, f"{arrow} {abs(delta):.1f} vs avg", ha="center", va="center",
                    fontsize=max(6, ctx["label_size"] - 4),
                    color=vt["success"] if better else vt["danger"],
                    fontfamily=vt["font"], zorder=3)
            xs = np.linspace(0.12, 0.88, len(series))
            ys = series.values
            rng = ys.max() - ys.min()
            yn = 0.86 + 0.08 * ((ys - ys.min()) / rng if rng else np.zeros_like(ys))
            ax.plot(xs, yn, color=vt["accent"], lw=1.1, alpha=0.8, zorder=3)


def viz_summary_cards(df, ctx):
    vt = ctx["vt"]
    fig = plt.figure(figsize=(12.4, 6.4))
    fig.patch.set_facecolor(vt["bg"])
    gs = gridspec.GridSpec(1, 1, figure=fig, top=0.86, bottom=0.04, left=0.02, right=0.98)
    panel_cards(fig, gs[0], df, ctx, metrics=CARD_METRICS, ncols=4)
    return finalize_fig(fig, ctx["title"], "Trend markers compare vs average of other matches in dataset", ctx)

# =============================
# DASHBOARD BUILDER
# =============================
PANEL_LIBRARY: Dict[str, Callable] = {}


def dashboard_pitch_panel(fig, slot, df, ctx, panel_fn, title, *args):
    ax = fig.add_subplot(slot)
    sub_spec = ctx["spec"]
    new_pitch_fig(ctx["vt"], sub_spec, ctx, ax=ax)
    panel_fn(ax, df, ctx, *args)
    ax.set_title(title, color=ctx["vt"]["text"], fontsize=max(9, ctx["label_size"] + 1),
                 fontweight="bold", fontfamily=ctx["vt"]["font"], pad=6)
    return ax


def dashboard_chart_panel(fig, slot, df, ctx, panel_fn, title, *args):
    ax = fig.add_subplot(slot)
    panel_fn(ax, df, ctx, *args)
    ax.set_title(title, color=ctx["vt"]["text"], fontsize=max(9, ctx["label_size"] + 1),
                 fontweight="bold", fontfamily=ctx["vt"]["font"], pad=6)
    return ax


def _dash_ctx(ctx) -> Dict:
    """Dashboard sub-panels use compact legends/labels and no per-panel titles."""
    c = dict(ctx)
    c["legend"] = dict(ctx["legend"], show=False)
    c["labels"] = dict(ctx["labels"], show=False)
    c["title_size"] = max(10, ctx["title_size"] - 8)
    c["label_size"] = max(7, ctx["label_size"] - 2)
    return c


PANEL_CHOICES = {
    "Heatmap": ("pitch", panel_heat, ()),
    "Pass Map": ("pitch", panel_arrow_map, ("pass",)),
    "Carry Map": ("pitch", panel_arrow_map, ("carry",)),
    "Cross Map": ("pitch", panel_arrow_map, ("cross",)),
    "Dribble Map": ("pitch", panel_arrow_map, ("dribble",)),
    "Shot Map": ("pitch", panel_shots, ()),
    "Defensive Actions": ("pitch", panel_defensive, ()),
    "Zone % (Thirds)": ("pitch", panel_zone_pct, ("Pitch Thirds",)),
    "Zone % (Lanes)": ("pitch", panel_zone_pct, ("Lanes",)),
    "Sequence Map": ("pitch", panel_sequence, ()),
    "Event Bar": ("chart", panel_event_bar, ()),
    "Top Players": ("chart", panel_player_bar, (10,)),
    "Pass Direction": ("chart", panel_pass_direction, ()),
    "Shot Results": ("chart", panel_shot_summary, ()),
    "Timeline": ("chart", panel_timeline, ("All",)),
}

DASHBOARD_PRESETS: Dict[str, Dict] = {
    "Match Summary Dashboard": {"cards": True, "panels": ["Pass Map", "Shot Map", "Zone % (Thirds)", "Shot Results"]},
    "Team Dashboard": {"cards": True, "panels": ["Heatmap", "Pass Map", "Pass Direction", "Timeline"]},
    "Opponent Dashboard": {"cards": True, "panels": ["Defensive Actions", "Heatmap", "Zone % (Lanes)", "Event Bar"]},
    "Player Dashboard": {"cards": True, "panels": ["Heatmap", "Pass Map", "Shot Map", "Top Players"]},
    "Goalkeeper Dashboard": {"cards": False, "panels": ["Pass Map", "Heatmap", "Zone % (Thirds)", "Event Bar"]},
    "Shot Quality Dashboard": {"cards": True, "panels": ["Shot Map", "Shot Results", "Zone % (Thirds)", "Timeline"]},
    "Territory Control Dashboard": {"cards": False, "panels": ["Zone % (Thirds)", "Zone % (Lanes)", "Heatmap", "Defensive Actions"]},
    "Performance Dashboard": {"cards": True, "panels": ["Timeline", "Pass Direction", "Event Bar", "Top Players"]},
}


def render_dashboard(df, ctx, layout: Dict):
    vt = ctx["vt"]
    panels = [p for p in layout.get("panels", []) if p in PANEL_CHOICES][:4]
    with_cards = bool(layout.get("cards", True))
    fig = plt.figure(figsize=(13.6, 10.6 if with_cards else 8.8))
    fig.patch.set_facecolor(vt["bg"])
    if with_cards:
        gs = gridspec.GridSpec(3, 2, figure=fig, height_ratios=[0.9, 1.6, 1.6],
                               top=0.90, bottom=0.03, left=0.04, right=0.98,
                               hspace=0.30, wspace=0.14)
        panel_cards(fig, gs[0, :], df, ctx, metrics=CARD_METRICS[:8], ncols=8)
        slots = [gs[1, 0], gs[1, 1], gs[2, 0], gs[2, 1]]
    else:
        gs = gridspec.GridSpec(2, 2, figure=fig, top=0.90, bottom=0.03, left=0.04,
                               right=0.98, hspace=0.26, wspace=0.14)
        slots = [gs[0, 0], gs[0, 1], gs[1, 0], gs[1, 1]]
    dctx = _dash_ctx(ctx)
    for slot, pname in zip(slots, panels):
        kind, fn, args = PANEL_CHOICES[pname]
        if kind == "pitch":
            dashboard_pitch_panel(fig, slot, df, dctx, fn, pname, *args)
        else:
            dashboard_chart_panel(fig, slot, df, dctx, fn, pname, *args)
    return finalize_fig(fig, ctx["title"], layout.get("subtitle", "Report-ready dashboard"), ctx)


def make_dashboard_viz(preset_name: str):
    def _render(df, ctx):
        layout = ctx["aux"].get("dashboard_layout") or DASHBOARD_PRESETS[preset_name]
        return render_dashboard(df, ctx, layout)
    return _render


def viz_custom_dashboard(df, ctx):
    layout = ctx["aux"].get("dashboard_layout") or {"cards": True, "panels": ["Pass Map", "Shot Map", "Heatmap", "Timeline"]}
    return render_dashboard(df, ctx, layout)


# =============================
# Insights (v3 preserved)
# =============================
def build_insights(df: pd.DataFrame) -> List[str]:
    insights: List[str] = []
    total = len(df)
    if total == 0:
        return ["No data after filters."]
    passes = df[df["event_type"].str.lower() == "pass"]
    carries = df[df["event_type"].str.lower() == "carry"]
    shots = df[df["event_type"].str.lower() == "shot"]
    defensive = df[df["event_type"].str.lower().isin(DEF_EVENTS)]
    if df["lane"].notna().any():
        lane = df["lane"].astype(str).value_counts().idxmax()
        lane_pct = df["lane"].astype(str).value_counts(normalize=True).max() * 100
        insights.append(f"Most selected actions start in the **{lane}** ({lane_pct:.0f}%).")
    if df["start_third"].notna().any():
        third = df["start_third"].astype(str).value_counts().idxmax()
        third_pct = df["start_third"].astype(str).value_counts(normalize=True).max() * 100
        insights.append(f"Highest activity third: **{third}** ({third_pct:.0f}%).")
    if len(passes):
        insights.append(f"Passing: **{pct(passes['is_forward'].sum(), len(passes))}** forward, "
                        f"**{int(passes['into_final_third'].sum())}** final-third entries, "
                        f"**{int(passes['into_box'].sum())}** passes into box.")
        if passes["player"].str.strip().ne("").any():
            insights.append(f"Most involved passer: **{passes['player'].value_counts().idxmax()}**.")
    if len(carries):
        insights.append(f"Carries: **{int((carries['distance'] >= 10).sum())}** progressive carries "
                        f"of 10+ pitch units from **{len(carries)}** carries.")
    if len(shots):
        goals = safe_count(shots, "shot_result", "Goal")
        on_target = shots["shot_result"].str.lower().isin(["goal", "saved", "on target", "on_target"]).sum()
        inside_box = ((shots["x"] >= 83) & (shots["y"].between(21, 79))).sum()
        insights.append(f"Shots: **{len(shots)}** shots, **{goals}** goals, **{on_target}** on target, "
                        f"**{inside_box}** inside the box.")
    if len(defensive):
        high = (defensive["x"] >= 66.67).sum()
        insights.append(f"Defensive actions: **{pct(high, len(defensive))}** in the final third/high areas.")
    return insights


# =============================
# REGISTRATIONS (all v3 names preserved; new plugins added, nothing edited)
# =============================
register_viz("Overview Heatmap", "Heatmaps", viz_heat_studio)
register_viz("Heatmap Studio", "Heatmaps", viz_heat_studio)
register_viz("Pass Map", "Maps", make_arrow_viz("pass"))
register_viz("Carry Map", "Maps", make_arrow_viz("carry"))
register_viz("Cross Map", "Maps", make_arrow_viz("cross"))
register_viz("Dribble Map", "Maps", make_arrow_viz("dribble"))
register_viz("Start / End Map", "Maps", viz_start_end)
register_viz("Sequence Map", "Maps", viz_sequence)
register_viz("Shot Map", "Maps", viz_shots)
register_viz("Zone Percentages", "Maps", viz_zone_pct)
register_viz("Defensive Actions Map", "Maps", viz_defensive)
register_viz("Event Distribution Bar", "Charts", viz_event_bar, uses_pitch=False)
register_viz("Top Players Bar", "Charts", viz_player_bar, uses_pitch=False)
register_viz("Pass Direction Bar", "Charts", viz_pass_direction, uses_pitch=False)
register_viz("Shot Result Bar", "Charts", viz_shot_summary, uses_pitch=False)
register_viz("Timeline Line Chart", "Charts", viz_timeline, uses_pitch=False)
register_viz("Match Trend Line Chart", "Charts", viz_match_trend, uses_pitch=False)
register_viz("Statistical Table", "Tables & Cards", viz_stat_table, uses_pitch=False)
register_viz("Match Summary Cards", "Tables & Cards", viz_summary_cards, uses_pitch=False)
for _name in DASHBOARD_PRESETS:
    register_viz(_name, "Dashboards", make_dashboard_viz(_name), uses_pitch=False)
register_viz("Custom Dashboard", "Dashboards", viz_custom_dashboard, uses_pitch=False)
# "Data Table" handled directly in the UI (interactive, not a figure)

# =============================
# APP UI
# =============================
def run_app():
    app_theme_name = st.sidebar.selectbox("App theme (UI only)", list(APP_THEMES.keys()), index=0)
    inject_css(APP_THEMES[app_theme_name])

    st.markdown("""
    <div class='main-header'>
        <div class='main-title'>Opponent Open Play Analysis</div>
        <div class='main-subtitle'>Production visualization engine: themed pitch maps, heatmap studio, tables, cards and report-ready dashboards. No set-pieces. No xG model required.</div>
    </div>
    """, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("### 1) Upload Data")
        uploaded = st.file_uploader("Upload CSV, Excel or JSON",
                                    type=["csv", "xlsx", "xls", "json", "jsonl"])
        coord_mode = st.selectbox("Coordinate system", ["0-100", "120 x 80"], index=0)
        attack_direction = st.selectbox("Attacking direction", [
            "Data already left-to-right",
            "Team attacks right-to-left in data (flip to left-to-right)"], index=0)

        st.markdown("### 2) Visualization")
        categories = ["All"] + sorted({v["category"] for v in VIZ_REGISTRY.values()})
        cat_sel = st.selectbox("Category", categories, index=0)
        names = [n for n, v in VIZ_REGISTRY.items() if cat_sel in ("All", v["category"])]
        names = names + ["Data Table"]
        chart_type = st.selectbox("Choose visualization", names)

        st.markdown("### 3) Visualization Theme")
        st.caption("Applies to the figure only — never the app UI.")
        vt_names = list(VIZ_THEMES.keys()) + CLUB_CUSTOM_NAMES
        vt_name = st.selectbox("Theme", vt_names, index=0)
        if vt_name == "Club Theme":
            c1, c2 = st.columns(2)
            primary = c1.color_picker("Primary", "#B00020")
            secondary = c2.color_picker("Secondary", "#FFD700")
            club_dark = st.checkbox("Dark background", value=True)
            base = VIZ_THEMES["Dark Professional"] if club_dark else VIZ_THEMES["Light Professional"]
            vt = dict(base, accent=primary, accent2=secondary, danger=primary, warning=secondary)
        elif vt_name == "Custom Theme":
            c1, c2 = st.columns(2)
            vt = dict(VIZ_THEMES["Light Professional"])
            vt["bg"] = c1.color_picker("Background", vt["bg"])
            vt["pitch"] = c2.color_picker("Pitch", vt["pitch"])
            vt["line"] = c1.color_picker("Pitch lines", vt["line"])
            vt["text"] = c2.color_picker("Text", vt["text"])
            vt["accent"] = c1.color_picker("Accent", vt["accent"])
            vt["accent2"] = c2.color_picker("Accent 2", vt["accent2"])
            vt["panel"] = vt["card_face"] = vt["legend_face"] = st.color_picker("Panel / cards", vt["panel"])
            vt["stripe"] = vt["pitch"]
        else:
            vt = dict(VIZ_THEMES[vt_name])
        font_choice = st.selectbox("Font", ["Theme default", "DejaVu Sans", "DejaVu Serif", "Monospace"], index=0)
        if font_choice != "Theme default":
            vt["font"] = {"Monospace": "DejaVu Sans Mono"}.get(font_choice, font_choice)

        st.markdown("### 4) Title & Typography")
        custom_title = st.text_input("Chart title", value=chart_type)
        show_title = st.checkbox("Show title", value=True)
        title_size = st.slider("Title size", 12, 32, 20)
        label_size = st.slider("Label size", 7, 18, 11)
        legend_size = st.slider("Legend size", 7, 16, 10)

        with st.expander("Pitch Engine", expanded=True):
            orientation = st.selectbox("Orientation", ["Horizontal", "Vertical", "Auto"], index=0)
            pitch_view = st.selectbox("Pitch view", PITCH_VIEWS, index=0)
            custom_crop = (0.0, 100.0, 0.0, 100.0)
            if pitch_view == "Custom Crop":
                cx = st.slider("Crop length (x)", 0, 100, (50, 100))
                cy = st.slider("Crop width (y)", 0, 100, (0, 100))
                custom_crop = (float(cx[0]), float(cx[1]), float(cy[0]), float(cy[1]))
            mirror = st.checkbox("Mirror pitch (flip X)", value=False)
            flip_y_opt = st.checkbox("Flip Y", value=False)
            show_stripes = st.checkbox("Pitch stripes", value=True)

        with st.expander("Thirds Engine", expanded=False):
            thirds_mode = st.selectbox("Thirds mode", [
                "None", "Length thirds (lines)", "Width lanes (lines)", "Length thirds + lanes",
                "Highlight final third", "Highlight middle third", "Highlight defensive third",
                "Highlight attacking half", "Highlight defensive half", "Custom positions"], index=1)
            thirds_positions = st.text_input("Custom line positions (0-100)", "25, 50, 75") \
                if thirds_mode == "Custom positions" else "33.33, 66.67"
            thirds_color = st.color_picker("Thirds color", vt["warning"])
            thirds_width = st.slider("Thirds line width", 0.5, 4.0, 1.3)
            thirds_alpha = st.slider("Thirds opacity", 0.1, 1.0, 0.7)
            thirds_labels = st.checkbox("Show third labels", value=False)
            lane_lines = st.checkbox("Always show lane lines", value=False)

        with st.expander("Marker Studio", expanded=False):
            m_shape = st.selectbox("Shape", list(MARKER_SHAPES.keys()), index=0)
            m_size = st.slider("Marker size", 25, 320, 80)
            m_edge_w = st.slider("Border width", 0.0, 4.0, 1.1)
            m_edge_c = st.color_picker("Border color", vt["line"])
            m_alpha = st.slider("Marker opacity", 0.2, 1.0, 0.85)
            m_rot = st.slider("Rotation (deg)", 0, 315, 0, step=45)
            m_jitter = st.slider("Jitter", 0.0, 2.0, 0.0)
            m_zorder = st.slider("Z-order", 3, 12, 6)
            m_shadow = st.checkbox("Shadow", value=False)
            m_glow = st.checkbox("Glow", value=False)
            m_glow_c = st.color_picker("Glow color", vt["accent"]) if m_glow else vt["accent"]

        with st.expander("Arrow Studio", expanded=False):
            a_kind = st.selectbox("Arrow style", ["Straight", "Curved", "Bezier", "Dashed",
                                                  "Dotted", "Double Arrow", "Comet", "Gradient Comet"], index=0)
            a_width = st.slider("Arrow width", 0.5, 6.0, 1.6)
            a_head = st.slider("Arrow head size", 4, 26, 10)
            a_curv = st.slider("Curvature", 0.02, 0.6, 0.18)
            a_alpha = st.slider("Arrow opacity", 0.2, 1.0, 0.72)
            a_cap = st.selectbox("Line cap", ["round", "butt", "projecting"], index=0)
            a_shadow = st.checkbox("Arrow shadow", value=False)
            a_glow = st.checkbox("Arrow glow", value=False)
            a_cmap = st.selectbox("Gradient colormap", HEAT_CMAPS, index=10) \
                if a_kind == "Gradient Comet" else "viridis"

        with st.expander("Label Engine", expanded=False):
            l_show = st.checkbox("Enable labels", value=True)
            l_players = st.checkbox("Show player/shirt labels on maps", value=False)
            l_smart = st.checkbox("Smart positioning (collision detection)", value=True)
            l_hide = st.checkbox("Hide overlapping labels", value=True)
            l_halo = st.checkbox("Halo", value=True)
            l_box = st.checkbox("Background box", value=False)
            l_leader = st.checkbox("Leader lines", value=True)
            l_size = st.slider("Label font size", 6, 16, 9)
            l_off = st.slider("Label offset", 0.5, 5.0, 1.6)
            l_rot = st.slider("Label rotation", 0, 90, 0)
            l_max = st.slider("Max labels (0 = all)", 0, 60, 0)

        with st.expander("Legend Engine", expanded=False):
            lg_show = st.checkbox("Show legend", value=True)
            lg_pos = st.selectbox("Position", list(LEGEND_POSITIONS.keys()), index=0)
            lg_orient = st.selectbox("Legend orientation", ["Horizontal", "Vertical"], index=0)
            lg_frame = st.checkbox("Legend frame", value=True)
            lg_title = st.text_input("Legend title", "")
            lg_renames = st.text_input("Rename items (old=new; old2=new2)", "")
            lg_hide = st.text_input("Hide items (comma-separated)", "")
            lg_order = st.text_input("Custom order (comma-separated)", "")

        with st.expander("Heatmap Studio", expanded=False):
            h_type = st.selectbox("Heatmap type", HEAT_TYPES, index=0)
            h_preset = st.selectbox("Data preset", list(HEAT_PRESETS.keys()), index=0)
            h_cmap = st.selectbox("Color map", HEAT_CMAPS, index=0)
            h_alpha = st.slider("Heat opacity", 0.15, 0.95, 0.65)
            h_bw = st.slider("Bandwidth (KDE)", 0.5, 8.0, 3.0)
            h_levels = st.slider("Contour levels", 4, 24, 10)
            h_bins = st.slider("Histogram bins", 5, 30, 13)
            h_grid = st.slider("Hexbin grid size", 8, 40, 22)
            h_cell = st.slider("Cell size (grid/zone)", 5, 25, 10)
            h_interp = st.selectbox("Interpolation", ["bilinear", "nearest", "bicubic", "gaussian"], index=0)
            h_norm = st.selectbox("Normalization", ["Count", "Percent"], index=0)
            h_thr = st.slider("Threshold percentile", 0, 90, 0)
            h_pctl = st.checkbox("Percentile scale", value=False)
            h_log = st.checkbox("Log scale", value=False)
            h_cell_labels = st.checkbox("Grid cell count labels", value=False)

        with st.expander("Colors", expanded=False):
            arrow_color = st.color_picker("Successful arrow color", vt["accent"])
            unsuccess_color = st.color_picker("Unsuccessful / blocked color", vt["danger"])
            start_color = st.color_picker("Start event color", vt["accent"])
            end_color = st.color_picker("End event color", vt["accent2"])
            shot_color = st.color_picker("No goal shot color", vt["panel"])
            goal_color = st.color_picker("Goal color", vt["danger"])
            zone_color = st.color_picker("Zone overlay color", vt["warning"])
            bar_color = st.color_picker("Bar color", vt["accent"])
            line_color = st.color_picker("Line color", vt["accent"])
            trend_color = st.color_picker("Trend line color", vt["danger"])
            carry_color = st.color_picker("Carry / dribble color", vt["grey"])
            cross_color = st.color_picker("Cross color", vt["accent2"])
            line_width = st.slider("Line chart width", 1.0, 5.0, 2.4)

        with st.expander("Export", expanded=False):
            exp_fmt = st.selectbox("Format", ["PNG", "SVG", "PDF"], index=0)
            exp_dpi = st.slider("DPI", 100, 400, 240, step=20)
            exp_transparent = st.checkbox("Transparent background", value=False,
                                          help="Export with no background fill (PNG/SVG/PDF).")

    if uploaded is None:
        st.markdown("""
        <div class='note-box'>
            Upload a CSV, Excel or JSON export from any provider (StatsBomb, Wyscout, Opta,
            Hudl, Sportscode or custom tagging). Required fields are <b>event type, x, y</b> —
            provider column names are detected automatically, and a preview lets you map
            anything that isn't matched. No manual renaming needed.
            Recommended: <b>team, opponent, match_id, phase, player, receiver, x2, y2, outcome, shot_result,
            body_part, minute, second, period, sequence_id</b>.
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    try:
        file_bytes = uploaded.getvalue()
        cleaned = clean_columns(read_uploaded_file(uploaded))
    except Exception as e:
        st.error(f"Could not read file: {e}")
        st.stop()

    # New file -> reset the per-file import confirmation (mapping itself persists
    # in session_state until the app restarts, per requirement 5).
    if st.session_state.get("_mapping_file") != uploaded.name:
        st.session_state["_mapping_file"] = uploaded.name
        st.session_state["_import_confirmed"] = None
        st.session_state["_force_mapping"] = False
        for _c in REQUIRED_CANONICAL + OPTIONAL_CANONICAL:
            st.session_state.pop(f"premap_{_c}", None)

    # Mapping comes from the platform (aliases + saved templates). The dialog is
    # only shown when the platform is not confident enough, when a required field
    # is unresolved, or when the user asks to review it - a clean provider export
    # now imports straight through.
    mapping, unresolved = resolve_column_mapping(cleaned, st.session_state.get("col_map"))
    confidence = mapping_confidence(cleaned)
    needs_review = bool(unresolved) or confidence < CONFIDENCE_THRESHOLD
    if (needs_review or st.session_state.get("_force_mapping")) \
            and st.session_state.get("_import_confirmed") != uploaded.name:
        render_import_preview(cleaned, mapping, mapping_log(cleaned, mapping),
                              confidence=confidence, filename=uploaded.name)
        st.stop()

    cleaned = apply_column_mapping(cleaned, mapping)
    problems = validate_data(cleaned)
    if problems:
        st.session_state["_import_confirmed"] = None      # re-open the mapping dialog
        st.error(" | ".join(problems))
        st.stop()

    # The platform owns the import: provider detection, loading, mapping,
    # coordinate normalization, cleaning, validation and quality scoring all
    # happen inside ImportService. Open Play only orchestrates, then adds the
    # derived columns its own charts contract on.
    try:
        result = platform_import(uploaded.name, file_bytes, mapping, coord_mode, attack_direction)
        df = add_derived_columns(result.frame)
    except Exception as e:
        st.error(f"Could not process file: {e}")
        st.stop()

    render_import_summary(result, cleaned)

    # Filters (v3 preserved)
    with st.sidebar:
        st.markdown("### 5) Filters")
        _FILTER_KEYS = ["f_team", "f_opp", "f_match", "f_event", "f_phase",
                        "f_player", "f_success", "f_minute"]
        if st.button("Reset filters", help="Clear all filters below"):
            for _k in _FILTER_KEYS:
                st.session_state.pop(_k, None)
            st.rerun()
        team_options = ["All"] + sorted([x for x in df["team"].unique().tolist() if str(x).strip()])
        opp_options = ["All"] + sorted([x for x in df["opponent"].unique().tolist() if str(x).strip()])
        match_options = ["All"] + sorted([str(x) for x in df["match_id"].unique().tolist() if str(x).strip()])
        event_options = sorted([x for x in df["event_type"].str.lower().unique().tolist() if str(x).strip()])
        phase_options = sorted([x for x in df["phase"].str.lower().unique().tolist() if str(x).strip()])
        player_options = sorted([x for x in df["player"].unique().tolist() if str(x).strip()])

        team_sel = st.selectbox("Team", team_options, key="f_team")
        opp_sel = st.selectbox("Opponent", opp_options, key="f_opp")
        match_sel = st.selectbox("Match", match_options, key="f_match")
        event_sel = st.multiselect("Event type filter", event_options, default=[], key="f_event")
        phase_sel = st.multiselect("Phase filter", phase_options, default=[], key="f_phase")
        player_sel = st.multiselect("Player filter", player_options, default=[], key="f_player")
        only_success = st.checkbox("Only successful outcome", value=False, key="f_success")
        minute_range = st.slider("Minute range", 0, 120, (0, 95), key="f_minute")
        top_n = st.slider("Top N players", 3, 25, 10)
        zone_mode = st.selectbox("Zone percentage mode", ["Pitch Thirds", "Lanes"])
        start_end_event = st.selectbox("Start/End event", ["pass", "carry", "cross", "dribble"], index=0)
        timeline_focus = st.selectbox("Timeline event", ["All"] + event_options, index=0)
        trend_metric = st.selectbox("Match trend metric", ["All Events", "Shots", "Final third entries", "Box entries"], index=0)
        sequence_mode = st.selectbox("Sequence map mode", ["Specific sequence", "Latest shot sequence",
                                                           "Latest goal sequence", "Longest sequence"], index=0)
        seq_source = df.copy()
        if match_sel != "All":
            seq_source = seq_source[seq_source["match_id"].astype(str) == match_sel]
        sequence_options = sorted([str(x) for x in seq_source["sequence_id"].astype(str).unique().tolist()
                                   if str(x).strip() and str(x).lower() != "nan"])
        sequence_id_sel = st.selectbox("Sequence ID", sequence_options if sequence_options else [""], index=0)
        show_sequence_numbers = st.checkbox("Show sequence order numbers", value=True)

        dashboard_layout = None
        if chart_type == "Custom Dashboard":
            st.markdown("### 6) Dashboard Builder")
            saved = st.session_state.setdefault("dash_templates", {})
            db_panels = st.multiselect("Panels (max 4)", list(PANEL_CHOICES.keys()),
                                       default=["Pass Map", "Shot Map", "Heatmap", "Timeline"])
            db_cards = st.checkbox("Include summary cards row", value=True)
            dashboard_layout = {"cards": db_cards, "panels": db_panels[:4]}
            tname = st.text_input("Template name", "My Dashboard")
            c1, c2 = st.columns(2)
            if c1.button("Save template"):
                saved[tname] = dashboard_layout
                st.success(f"Saved '{tname}'")
            if saved:
                pick = c2.selectbox("Load template", ["—"] + list(saved.keys()))
                if pick != "—":
                    dashboard_layout = saved[pick]
            st.download_button("Download templates JSON",
                               json.dumps(saved, indent=2).encode("utf-8"),
                               "dashboard_templates.json", "application/json")
            tup = st.file_uploader("Upload templates JSON", type=["json"], key="tplup")
            if tup is not None:
                try:
                    st.session_state["dash_templates"].update(json.loads(tup.read().decode("utf-8")))
                    st.success("Templates loaded")
                except Exception as ex:
                    st.error(f"Invalid template file: {ex}")

    # Apply filters
    f = df.copy()
    if team_sel != "All":
        f = f[f["team"] == team_sel]
    if opp_sel != "All":
        f = f[f["opponent"] == opp_sel]
    if match_sel != "All":
        f = f[f["match_id"].astype(str) == match_sel]
    if event_sel:
        f = f[f["event_type"].str.lower().isin(event_sel)]
    if phase_sel:
        f = f[f["phase"].str.lower().isin(phase_sel)]
    if player_sel:
        f = f[f["player"].isin(player_sel)]
    f = f[(f["time_min"] >= minute_range[0]) & (f["time_min"] <= minute_range[1])]
    if only_success:
        f = f[f["outcome"].str.lower().isin(SUCCESS_WORDS)]

    # Never let filters silently remove every event: tell the user what happened
    # and how to recover, instead of drawing a blank pitch with no explanation.
    if len(f) == 0:
        if len(df) == 0:
            st.warning("The uploaded dataset contains no events to display.")
        else:
            active = []
            if team_sel != "All": active.append(f"team = {team_sel}")
            if opp_sel != "All": active.append(f"opponent = {opp_sel}")
            if match_sel != "All": active.append(f"match = {match_sel}")
            if event_sel: active.append(f"event type ∈ {event_sel}")
            if phase_sel: active.append(f"phase ∈ {phase_sel}")
            if player_sel: active.append(f"player ∈ {player_sel}")
            if only_success: active.append("only successful outcomes")
            if tuple(minute_range) != (0, 95): active.append(f"minutes {minute_range[0]}–{minute_range[1]}")
            detail = ("; ".join(active)) if active else "the current filter selection"
            st.warning(
                f"No events match {detail}. "
                f"All {len(df):,} events were filtered out — use **Reset filters** "
                f"in the sidebar to clear the selection."
            )

    spec = PitchSpec(orientation=orientation, view=pitch_view, custom_crop=custom_crop,
                     mirror=mirror, flip_y=flip_y_opt, thirds_mode=thirds_mode,
                     thirds_positions=thirds_positions, thirds_color=thirds_color,
                     thirds_width=thirds_width, thirds_alpha=thirds_alpha,
                     thirds_labels=thirds_labels, lane_lines=lane_lines, stripes=show_stripes)
    f = apply_pitch_transforms(f, spec)
    df_all = apply_pitch_transforms(df, spec)

    passes = f[f["event_type"].str.lower() == "pass"]
    carries = f[f["event_type"].str.lower() == "carry"]
    shots = f[f["event_type"].str.lower() == "shot"]
    defensive = f[f["event_type"].str.lower().isin(DEF_EVENTS)]

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1: kpi("Events", len(f))
    with k2: kpi("Passes", len(passes))
    with k3: kpi("Carries", len(carries))
    with k4: kpi("Shots", len(shots))
    with k5: kpi("Goals", safe_count(shots, "shot_result", "Goal"))
    with k6: kpi("Def Actions", len(defensive))

    ctx = {
        "vt": vt, "spec": spec,
        "title": custom_title, "show_title": show_title,
        "title_size": title_size, "label_size": label_size, "legend_size": legend_size,
        "respect_filter": bool(event_sel),
        "marker": {"shape": m_shape, "size": m_size, "edge_width": m_edge_w, "edge_color": m_edge_c,
                   "alpha": m_alpha, "rotation": m_rot, "jitter": m_jitter, "zorder": m_zorder,
                   "shadow": m_shadow, "glow": m_glow, "glow_color": m_glow_c},
        "arrow": {"kind": a_kind, "width": a_width, "head": a_head, "curvature": a_curv,
                  "alpha": a_alpha, "linecap": a_cap, "shadow": a_shadow, "glow": a_glow, "cmap": a_cmap},
        "labels": {"show": l_show, "show_players": l_players, "smart": l_smart,
                   "hide_overlapping": l_hide, "halo": l_halo, "halo_color": vt["pitch"],
                   "box": l_box, "leader_lines": l_leader, "size": l_size, "offset": l_off,
                   "rotation": l_rot, "max_labels": l_max},
        "legend": {"show": lg_show, "position": lg_pos, "orientation": lg_orient, "frame": lg_frame,
                   "title": lg_title, "renames": lg_renames, "hide": lg_hide, "order": lg_order},
        "heat": {"type": h_type, "preset": h_preset, "cmap": h_cmap, "alpha": h_alpha,
                 "bandwidth": h_bw, "levels": h_levels, "bins": h_bins, "gridsize": h_grid,
                 "cell_size": h_cell, "interpolation": h_interp, "normalization": h_norm,
                 "threshold": h_thr, "percentile_scale": h_pctl, "log_scale": h_log,
                 "cell_labels": h_cell_labels},
        "colors": {"arrow": arrow_color, "unsuccess": unsuccess_color, "start": start_color,
                   "end": end_color, "shot": shot_color, "goal": goal_color, "zone": zone_color,
                   "bar": bar_color, "line": line_color, "trend": trend_color,
                   "carry": carry_color, "cross": cross_color},
        "aux": {"df_all": df_all, "top_n": top_n, "zone_mode": zone_mode,
                "start_end_event": start_end_event, "timeline_focus": timeline_focus,
                "trend_metric": trend_metric, "sequence_mode": sequence_mode,
                "sequence_id": sequence_id_sel, "show_sequence_numbers": show_sequence_numbers,
                "line_width": line_width, "dashboard_layout": dashboard_layout},
    }

    st.write("")
    left, right = st.columns([2.45, 1])
    fig = None
    with left:
        if chart_type == "Data Table":
            st.dataframe(f, width="stretch", height=620)
        else:
            entry = VIZ_REGISTRY.get(chart_type)
            if entry is None:
                st.error(f"Unknown visualization: {chart_type}")
            else:
                try:
                    fig = entry["render"](f, ctx)
                except Exception as ex:
                    st.error(f"Render error: {ex}")
        if fig is not None:
            st.pyplot(fig, use_container_width=True)
            fmt = exp_fmt.lower()
            data = fig_to_bytes(fig, fmt=fmt, dpi=exp_dpi, transparent=exp_transparent)
            mime = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}[fmt]
            fname = f"{chart_type.lower().replace(' ', '_').replace('/', '_')}.{fmt}"
            st.download_button(f"Download chart as {exp_fmt}", data=data, file_name=fname, mime=mime)
            plt.close(fig)

    with right:
        st.markdown("### Auto Insights")
        for ins in build_insights(f):
            st.markdown(f"- {ins}")
        st.markdown("### Data Quality")
        st.metric("Rows with valid x/y", f[["x", "y"]].dropna().shape[0] if {"x", "y"}.issubset(f.columns) else 0)
        st.metric("Rows with valid x2/y2", f[["x2", "y2"]].dropna().shape[0] if {"x2", "y2"}.issubset(f.columns) else 0)
        st.metric("Selected matches", f["match_id"].astype(str).replace("", np.nan).dropna().nunique())
        st.markdown("### Export")
        st.download_button("Download filtered CSV", f.to_csv(index=False).encode("utf-8"),
                           "filtered_open_play_data.csv", "text/csv")

    st.markdown("---")
    st.markdown("<span style='opacity:0.7'>Maps use a 100 x 68 pitch; input can remain 0-100 coordinates "
                "(y is automatically scaled). Visualization themes affect figures only.</span>",
                unsafe_allow_html=True)


import os as _os
if not _os.environ.get("FAP_TEST"):
    run_app()
