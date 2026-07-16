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


def _chrome() -> str:
    """Reset Streamlit's native chrome so the branded shell owns the top.

    Root cause fix: Streamlit's native header ([data-testid=stHeader]) is a
    fixed 60px OPAQUE bar at z-index 999990 that painted over the branding, and
    the default top padding was gone. We collapse that bar (its only controls -
    Deploy/menu - are non-essential for a branded deployment; the sidebar
    collapse control lives in the sidebar, not here), then let the sticky shell
    header provide the top spacing. No negative margins anywhere.
    """
    return """
/* neutralize the native 60px header bar - it overlapped the branding */
[data-testid="stHeader"] { background: transparent !important; height: 0 !important;
  min-height: 0 !important; box-shadow: none !important; }
[data-testid="stToolbar"] { display: none !important; }
/* the branded sticky header now owns the top; give it a little breathing room */
[data-testid="stMainBlockContainer"], .block-container { padding-top: 0.6rem !important; }
/* reclaim the empty 60px strip above the sidebar logos (keep collapse control) */
[data-testid="stSidebarHeader"] { padding: 6px 8px 0 !important; height: auto !important;
  min-height: 0 !important; }
[data-testid="stSidebarUserContent"] { padding-top: 2px !important; }
"""


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
.block-container {{ max-width: {brand.spacing.content_max_width}; }}
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
}
/* pin the expanded sidebar to the configured width so it never drags wide and
   squeezes the main column; when collapsed (aria-expanded=false) the rule drops
   out and Streamlit's native collapse takes over. */
[data-testid="stSidebar"]:not([aria-expanded="false"]) { width: var(--fap-sidebar-width) !important; }
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
  text-transform: uppercase; letter-spacing: 0.08em; margin: 14px 4px 6px; font-weight: 600; }
/* sidebar rhythm: brand, selectors, nav buttons all align on one clean grid */
[data-testid="stSidebar"] .fap-brandbar { padding: 2px 4px 12px; margin-bottom: 8px;
  border-bottom: 1px solid var(--fap-border); }
[data-testid="stSidebar"] .fap-brand { margin: 6px 4px 2px; font-size: 0.95rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.4rem; }
[data-testid="stSidebar"] .stButton { margin-bottom: 2px; }
[data-testid="stSidebar"] .stButton > button {
  justify-content: flex-start; text-align: left; font-weight: 500;
  padding: 6px 12px; border: 1px solid transparent; background: transparent;
}
[data-testid="stSidebar"] .stButton > button:hover {
  background: var(--fap-surface-alt); border-color: var(--fap-border); }
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: color-mix(in srgb, var(--fap-primary) 14%, transparent);
  color: var(--fap-primary); border-color: transparent;
  box-shadow: inset 3px 0 0 var(--fap-primary); font-weight: 600;
}
[data-testid="stSidebar"] [data-testid="stTextInput"],
[data-testid="stSidebar"] [data-baseweb="select"] { margin-bottom: 4px; }
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
.fap-brand { display: flex; align-items: center; gap: var(--fap-space-2);
  font-size: 1.05rem; font-weight: 750; color: var(--fap-text); margin-bottom: 4px; }
.fap-topbar { display: flex; align-items: center; justify-content: flex-end;
  gap: var(--fap-space-2); color: var(--fap-text-muted); font-size: 0.82rem; }
.fap-section { display: flex; align-items: center; gap: var(--fap-space-2); }
.fap-logo { display: inline-block; vertical-align: middle; object-fit: contain; }
.fap-logos { display: flex; align-items: center; gap: var(--fap-space-3); }
.fap-logos .sep { color: var(--fap-text-subtle); font-weight: 400; }
.fap-brandbar { display: flex; align-items: center; gap: var(--fap-space-3);
  padding: 2px 0 10px; }
.fap-brandbar .titles { line-height: 1.2; }
.fap-brandbar .titles b { color: var(--fap-text); font-size: 0.98rem; }
.fap-brandbar .titles span { color: var(--fap-text-muted); font-size: 0.72rem; }
/* sticky professional top header - owns the top of the page, stays on scroll */
.fap-shell-header {
  position: sticky; top: 0; z-index: 90;
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--fap-space-4); padding: 10px 18px; margin-bottom: var(--fap-space-4);
  background: var(--fap-surface);
  border: 1px solid var(--fap-border); border-radius: var(--fap-radius-lg);
  box-shadow: var(--fap-shadow-sm);
  overflow: hidden;                 /* defensive: never spill a narrow column */
}
.fap-shell-header .left { display: flex; align-items: center; gap: var(--fap-space-3); min-width: 0; }
.fap-shell-header .titles { display: flex; flex-direction: column; line-height: 1.25; min-width: 0; }
.fap-shell-header .titles b { font-size: 0.98rem; color: var(--fap-text); }
.fap-shell-header .crumbs { font-size: 0.78rem; color: var(--fap-text-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fap-shell-header .right { display: flex; align-items: center; gap: var(--fap-space-3);
  color: var(--fap-text-muted); font-size: 0.82rem; white-space: nowrap;
  flex-shrink: 0; min-width: 0; }
.fap-shell-header .left { flex: 1 1 auto; overflow: hidden; }
.fap-shell-header .fap-logos img { height: 34px; }
.fap-shell-header .sep { color: var(--fap-text-subtle); }
.fap-login { text-align: center; padding: 8px 0 4px; }
.fap-login .fap-logos { justify-content: center; margin-bottom: 14px; }
.fap-login h2 { margin: 6px 0 2px; }
.fap-login .powered { color: var(--fap-text-muted); font-size: 0.85rem; }
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
/* Pin the professional sidebar width only where there is room; below that let
   Streamlit's native collapse/overlay behave (never force a full-width sidebar
   that squeezes the main column). */
@media (min-width: 769px) {{
  [data-testid="stSidebar"]:not([aria-expanded="false"]) {{ width: var(--fap-sidebar-width) !important; }}
}}
@media (min-width: {sp.breakpoint_desktop}) {{
  .block-container {{ max-width: {sp.content_max_width}; }}
}}
@media (max-width: {sp.breakpoint_laptop}) {{
  .block-container {{ max-width: 100%; }}
}}
@media (max-width: {sp.breakpoint_tablet}) {{
  .fap-shell-header {{ flex-wrap: wrap; gap: var(--fap-space-2); padding: 10px 12px; }}
  .fap-shell-header .right {{ flex-wrap: wrap; }}
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
    body = "".join((_chrome(), _base(brand), _sidebar(), _components(), _forms(),
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
