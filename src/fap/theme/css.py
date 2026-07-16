"""The application stylesheet, generated from branding tokens.

``build_css`` is pure (returns a string) so it is fully unit-testable without
Streamlit. ``apply`` injects it. All application CSS lives here - pages carry no
inline CSS. Nothing here can affect a chart: matplotlib figures are rendered to
images before they reach the browser, so CSS never touches them. That is what
keeps "change the app theme, never the charts" true by construction.
"""
from __future__ import annotations

from fap.theme.branding import DEFAULT_BRANDING, Branding


def _variables(brand: Branding, mode: str) -> str:
    p = brand.palette
    s = p.surface_for("dark" if mode == "dark" else "light")
    sp, ty = brand.spacing, brand.typography
    return f"""
  --fap-primary: {p.primary};
  --fap-primary-hover: {p.primary_hover};
  --fap-on-primary: {p.on_primary};
  --fap-secondary: {p.secondary};
  --fap-accent: {p.accent};
  --fap-success: {p.success};
  --fap-warning: {p.warning};
  --fap-danger: {p.danger};
  --fap-info: {p.info};
  --fap-bg: {s.bg};
  --fap-surface: {s.surface};
  --fap-surface-alt: {s.surface_alt};
  --fap-border: {s.border};
  --fap-text: {s.text};
  --fap-text-muted: {s.text_muted};
  --fap-text-subtle: {s.text_subtle};
  --fap-overlay: {s.overlay};
  --fap-font-sans: {ty.font_sans};
  --fap-font-mono: {ty.font_mono};
  --fap-radius-sm: {sp.radius_sm};
  --fap-radius-md: {sp.radius_md};
  --fap-radius-lg: {sp.radius_lg};
  --fap-radius-xl: {sp.radius_xl};
  --fap-radius-full: {sp.radius_full};
  --fap-sidebar-width: {sp.sidebar_width};
  --fap-header-height: {sp.header_height};
  --fap-shadow-sm: {sp.shadow_sm};
  --fap-shadow-md: {sp.shadow_md};
  --fap-shadow-lg: {sp.shadow_lg};
  --fap-space-2: {sp.space_2};
  --fap-space-3: {sp.space_3};
  --fap-space-4: {sp.space_4};
  --fap-transition: {sp.transition_base};
""".rstrip()


def _base(brand: Branding) -> str:
    ty = brand.typography
    return f"""
.stApp {{
  background: var(--fap-bg);
  color: var(--fap-text);
  font-family: var(--fap-font-sans);
  font-size: {ty.size_base};
  line-height: {ty.line_normal};
}}
.block-container {{ padding-top: var(--fap-space-4); max-width: {brand.spacing.content_max_width}; }}
h1, h2, h3, h4 {{ color: var(--fap-text); font-weight: {ty.weight_bold};
  letter-spacing: {ty.tracking_tight}; line-height: {ty.line_tight}; }}
a {{ color: var(--fap-primary); }}
code, pre {{ font-family: var(--fap-font-mono); }}
"""


def _sidebar() -> str:
    return """
[data-testid="stSidebar"] {
  background: var(--fap-surface);
  border-right: 1px solid var(--fap-border);
  width: var(--fap-sidebar-width) !important;
}
[data-testid="stSidebar"] * { color: var(--fap-text); }
[data-testid="stSidebar"] .fap-nav-item {
  display: flex; align-items: center; gap: var(--fap-space-3);
  padding: 8px 12px; border-radius: var(--fap-radius-md);
  color: var(--fap-text-muted); transition: background var(--fap-transition),
  color var(--fap-transition); cursor: pointer;
}
[data-testid="stSidebar"] .fap-nav-item:hover { background: var(--fap-surface-alt); color: var(--fap-text); }
[data-testid="stSidebar"] .fap-nav-item.active {
  background: color-mix(in srgb, var(--fap-primary) 14%, transparent);
  color: var(--fap-primary); font-weight: 600;
  box-shadow: inset 3px 0 0 var(--fap-primary);
}
.fap-nav-section { color: var(--fap-text-subtle); font-size: 0.7rem;
  text-transform: uppercase; letter-spacing: 0.08em; margin: 14px 12px 6px; }
"""


def _components() -> str:
    return """
.fap-header {
  display: flex; align-items: center; justify-content: space-between;
  min-height: var(--fap-header-height); padding: 0 var(--fap-space-4);
  background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: var(--fap-radius-lg); box-shadow: var(--fap-shadow-sm);
  margin-bottom: var(--fap-space-4);
}
.fap-breadcrumb { color: var(--fap-text-muted); font-size: 0.85rem; }
.fap-breadcrumb b { color: var(--fap-text); }
.fap-card {
  background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: var(--fap-radius-lg); padding: var(--fap-space-4);
  box-shadow: var(--fap-shadow-sm); transition: box-shadow var(--fap-transition),
  transform var(--fap-transition);
}
.fap-card:hover { box-shadow: var(--fap-shadow-md); }
.fap-kpi { text-align: left; }
.fap-kpi .label { color: var(--fap-text-muted); font-size: 0.8rem; }
.fap-kpi .value { color: var(--fap-text); font-size: 1.6rem; font-weight: 750; margin-top: 2px; }
.fap-kpi .delta.up { color: var(--fap-success); }
.fap-kpi .delta.down { color: var(--fap-danger); }
.fap-badge {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px;
  border-radius: var(--fap-radius-full); font-size: 0.72rem; font-weight: 600;
}
.fap-badge.success { background: color-mix(in srgb, var(--fap-success) 16%, transparent); color: var(--fap-success); }
.fap-badge.warning { background: color-mix(in srgb, var(--fap-warning) 16%, transparent); color: var(--fap-warning); }
.fap-badge.danger  { background: color-mix(in srgb, var(--fap-danger) 16%, transparent); color: var(--fap-danger); }
.fap-badge.info    { background: color-mix(in srgb, var(--fap-info) 16%, transparent); color: var(--fap-info); }
.fap-badge.neutral { background: var(--fap-surface-alt); color: var(--fap-text-muted); }
.fap-footer {
  display: flex; gap: var(--fap-space-4); flex-wrap: wrap;
  color: var(--fap-text-subtle); font-size: 0.72rem;
  border-top: 1px solid var(--fap-border); padding-top: var(--fap-space-2);
  margin-top: var(--fap-space-4);
}
.fap-icon { vertical-align: middle; flex: 0 0 auto; }
"""


def _forms() -> str:
    return """
.stButton > button, .stDownloadButton > button {
  border-radius: var(--fap-radius-md); font-weight: 600;
  border: 1px solid var(--fap-border); transition: all var(--fap-transition);
}
.stButton > button[kind="primary"] {
  background: var(--fap-primary); border-color: var(--fap-primary); color: var(--fap-on-primary);
}
.stButton > button[kind="primary"]:hover { background: var(--fap-primary-hover); }
.stButton > button:hover { border-color: var(--fap-primary); }
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-baseweb="select"] > div, [data-testid="stTextArea"] textarea {
  border-radius: var(--fap-radius-md) !important;
}
[data-baseweb="checkbox"] svg, [data-baseweb="radio"] svg { color: var(--fap-primary); }
[data-testid="stFileUploaderDropzone"] {
  border-radius: var(--fap-radius-lg); border: 1px dashed var(--fap-border);
  background: var(--fap-surface-alt);
}
"""


def _tables() -> str:
    return """
[data-testid="stTable"], .stDataFrame { border-radius: var(--fap-radius-md); overflow: hidden; }
[data-testid="stTable"] thead th, .stDataFrame thead th {
  position: sticky; top: 0; z-index: 1;
  background: var(--fap-surface-alt); color: var(--fap-text);
  font-weight: 600; border-bottom: 1px solid var(--fap-border);
}
[data-testid="stTable"] tbody tr:hover, .stDataFrame tbody tr:hover { background: var(--fap-surface-alt); }
[data-testid="stTable"] td { border-bottom: 1px solid var(--fap-border); }
"""


def _a11y_and_motion() -> str:
    return """
:where(button, a, input, select, textarea, [tabindex]):focus-visible {
  outline: 2px solid var(--fap-primary); outline-offset: 2px; border-radius: var(--fap-radius-sm);
}
.fap-card, .fap-nav-item, .stButton > button { will-change: auto; }
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
@keyframes fap-fade-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.fap-fade-in { animation: fap-fade-in var(--fap-transition); }
"""


def _responsive(brand: Branding) -> str:
    sp = brand.spacing
    return f"""
@media (max-width: {sp.breakpoint_laptop}) {{
  .block-container {{ max-width: 100%; }}
  .fap-header {{ flex-wrap: wrap; gap: var(--fap-space-2); }}
}}
@media (max-width: {sp.breakpoint_tablet}) {{
  [data-testid="stSidebar"] {{ width: 100% !important; }}
  .fap-footer {{ gap: var(--fap-space-2); }}
  .fap-kpi .value {{ font-size: 1.3rem; }}
}}
"""


def build_css(brand: Branding | None = None, mode: str = "auto") -> str:
    """The complete application stylesheet for ``mode`` (light|dark|auto).

    For 'auto', both the OS preference (prefers-color-scheme) and an explicit
    ``data-theme`` on the root are honoured; light and dark variable blocks are
    both emitted so a runtime toggle needs no re-render.
    """
    brand = brand or DEFAULT_BRANDING
    body = "".join((_base(brand), _sidebar(), _components(), _forms(),
                    _tables(), _a11y_and_motion(), _responsive(brand)))

    if mode == "light":
        roots = f":root, :root[data-theme=light] {{{_variables(brand, 'light')}\n}}"
    elif mode == "dark":
        roots = f":root, :root[data-theme=dark] {{{_variables(brand, 'dark')}\n}}"
    else:  # auto
        roots = (
            f":root {{{_variables(brand, 'light')}\n}}\n"
            f"@media (prefers-color-scheme: dark) {{ :root {{{_variables(brand, 'dark')}\n}} }}\n"
            f":root[data-theme=light] {{{_variables(brand, 'light')}\n}}\n"
            f":root[data-theme=dark] {{{_variables(brand, 'dark')}\n}}"
        )
    return f"<style id=\"fap-theme\">\n{roots}\n{body}\n</style>"


def apply(brand: Branding | None = None, mode: str = "auto") -> None:
    """Inject the stylesheet into the running app (the only Streamlit call)."""
    import streamlit as st
    st.markdown(build_css(brand, mode), unsafe_allow_html=True)
