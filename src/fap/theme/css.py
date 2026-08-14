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
  --fap-raised: {s.raised};
  --fap-hover: {s.hover};
  --fap-border: {s.border};
  --fap-border-strong: {s.border_strong};
  --fap-text: {s.text};
  --fap-text-muted: {s.text_muted};
  --fap-text-subtle: {s.text_subtle};
  --fap-overlay: {s.overlay};
  --fap-font-sans: {ty.font_sans};
  --fap-font-mono: {ty.font_mono};
  --fap-feature-tabular: {ty.feature_tabular};
  --fap-weight-medium: {ty.weight_medium};
  --fap-weight-semibold: {ty.weight_semibold};
  --fap-weight-bold: {ty.weight_bold};
  --fap-weight-black: {ty.weight_black};
  --fap-text-2xs: {ty.size_2xs};
  --fap-text-xs: {ty.size_xs};
  --fap-text-sm: {ty.size_sm};
  --fap-text-lg: {ty.size_lg};
  --fap-text-xl: {ty.size_xl};
  --fap-text-2xl: {ty.size_2xl};
  --fap-tracking-wider: {ty.tracking_wider};
  --fap-radius-xs: {sp.radius_xs};
  --fap-radius-sm: {sp.radius_sm};
  --fap-radius-md: {sp.radius_md};
  --fap-radius-lg: {sp.radius_lg};
  --fap-radius-xl: {sp.radius_xl};
  --fap-radius-2xl: {sp.radius_2xl};
  --fap-radius-full: {sp.radius_full};
  --fap-sidebar-width: {sp.sidebar_width};
  --fap-rail-expanded: 248px;
  --fap-rail-collapsed: 72px;
  --fap-rail-width: 248px;
  --fap-header-height: {sp.header_height};
  --fap-shadow-xs: {sp.shadow_xs};
  --fap-shadow-sm: {sp.shadow_sm};
  --fap-shadow-md: {sp.shadow_md};
  --fap-shadow-lg: {sp.shadow_lg};
  --fap-shadow-xl: {sp.shadow_xl};
  --fap-space-1: {sp.space_1};
  --fap-space-2: {sp.space_2};
  --fap-space-3: {sp.space_3};
  --fap-space-4: {sp.space_4};
  --fap-space-5: {sp.space_5};
  --fap-space-6: {sp.space_6};
  --fap-transition-fast: {sp.transition_fast};
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
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}}
.block-container {{ max-width: {brand.spacing.content_max_width}; padding-top: 0.6rem; }}
h1, h2, h3, h4 {{ color: var(--fap-text); font-weight: {ty.weight_bold};
  letter-spacing: {ty.tracking_tight}; line-height: {ty.line_tight}; }}
h1 {{ font-size: {ty.size_2xl}; font-weight: {ty.weight_bold};
  letter-spacing: {ty.tracking_tight}; }}
h2 {{ font-size: {ty.size_xl}; font-weight: {ty.weight_bold}; }}
h3 {{ font-size: {ty.size_lg}; font-weight: {ty.weight_semibold}; }}
p, .stMarkdown, [data-testid="stCaptionContainer"] {{ font-weight: {ty.weight_normal}; }}
a {{ color: var(--fap-primary); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code, pre {{ font-family: var(--fap-font-mono); }}
hr, [data-testid="stDivider"] {{ border-color: var(--fap-border); opacity: 0.9; }}
::selection {{ background: color-mix(in srgb, var(--fap-primary) 26%, transparent); }}
/* quiet, professional scrollbars */
* {{ scrollbar-width: thin; scrollbar-color: var(--fap-border-strong) transparent; }}
*::-webkit-scrollbar {{ width: 10px; height: 10px; }}
*::-webkit-scrollbar-thumb {{ background: var(--fap-border-strong);
  border-radius: 999px; border: 2px solid transparent; background-clip: padding-box; }}
*::-webkit-scrollbar-thumb:hover {{ background: var(--fap-text-subtle); background-clip: padding-box; }}
/* tabular figures wherever numbers carry meaning */
.fap-metric .value, .fap-kpi .value, .fap-stat-tile .v, [data-testid="stMetricValue"],
.stDataFrame td {{ font-feature-settings: var(--fap-feature-tabular); }}
/* denser main-content vertical rhythm (SaaS analytics density, not a form) */
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] {{ gap: 0.7rem; }}
[data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] {{ gap: 0.7rem; }}
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
.fap-nav-section { color: var(--fap-text-subtle); font-size: 0.68rem;
  text-transform: uppercase; letter-spacing: var(--fap-tracking-wider);
  margin: 16px 6px 6px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.fap-nav-section::after { content: ""; flex: 1; height: 1px; background: var(--fap-border); opacity: 0.7; }
/* sidebar rhythm: brand, selectors, nav buttons all align on one clean grid */
[data-testid="stSidebar"] { box-shadow: inset -1px 0 0 var(--fap-border); }
[data-testid="stSidebar"] .fap-brandbar { padding: 2px 4px 12px; margin-bottom: 8px;
  border-bottom: 1px solid var(--fap-border); }
[data-testid="stSidebar"] .fap-brand { margin: 6px 4px 2px; font-size: 0.95rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.3rem; }
[data-testid="stSidebar"] .stButton { margin-bottom: 1px; }
[data-testid="stSidebar"] .stButton > button {
  justify-content: flex-start; text-align: left; font-weight: 500;
  padding: 7px 12px; border: 1px solid transparent; background: transparent;
  border-radius: var(--fap-radius-md); color: var(--fap-text-muted);
  transition: background var(--fap-transition-fast), color var(--fap-transition-fast),
    border-color var(--fap-transition-fast), transform var(--fap-transition-fast);
}
[data-testid="stSidebar"] .stButton > button:hover {
  background: var(--fap-hover); border-color: var(--fap-border);
  color: var(--fap-text); transform: translateX(2px); }
/* Active nav item: NEUTRAL surface + a single thin accent bar and an accent icon —
   the accent guides the eye, it never becomes an orange pill. No wash, no glow. */
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: var(--fap-hover);
  color: var(--fap-text);
  border-color: var(--fap-border);
  box-shadow: inset 3px 0 0 var(--fap-primary);
  font-weight: 650;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"]::before { color: var(--fap-primary); }
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
  transform: none; background: var(--fap-surface-alt); border-color: var(--fap-border-strong); }
[data-testid="stSidebar"] [data-testid="stTextInput"],
[data-testid="stSidebar"] [data-baseweb="select"] { margin-bottom: 4px; }
/* collapsible section groups (native expander used as a nav group) */
[data-testid="stSidebar"] [data-testid="stExpander"] { border: none; background: transparent; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary { padding: 4px 6px;
  color: var(--fap-text-subtle); font-size: 0.68rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: var(--fap-tracking-wider); }
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
  border-radius: var(--fap-radius-md); padding: 13px 15px;
  box-shadow: var(--fap-shadow-xs); transition: box-shadow var(--fap-transition),
  transform var(--fap-transition), border-color var(--fap-transition);
}
.fap-card:hover { box-shadow: var(--fap-shadow-md); }
.fap-card.clickable { cursor: pointer; }
.fap-card.clickable:hover { transform: translateY(-2px); box-shadow: var(--fap-shadow-lg);
  border-color: color-mix(in srgb, var(--fap-primary) 40%, var(--fap-border)); }
.fap-kpi { text-align: left; }
.fap-kpi .label { color: var(--fap-text-muted); font-size: 0.8rem; }
.fap-kpi .value { color: var(--fap-text); font-size: 1.6rem; font-weight: var(--fap-weight-bold); margin-top: 2px; }
.fap-kpi .delta.up { color: var(--fap-success); }
.fap-kpi .delta.down { color: var(--fap-danger); }
.fap-badge {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px;
  border-radius: var(--fap-radius-full); font-size: 0.72rem; font-weight: 650;
  line-height: 1.5; white-space: nowrap; border: 1px solid transparent;
  vertical-align: middle;
}
.fap-badge .fap-icon { margin-left: -1px; }
.fap-badge.success { background: color-mix(in srgb, var(--fap-success) 15%, transparent);
  color: var(--fap-success); border-color: color-mix(in srgb, var(--fap-success) 28%, transparent); }
.fap-badge.warning { background: color-mix(in srgb, var(--fap-warning) 15%, transparent);
  color: var(--fap-warning); border-color: color-mix(in srgb, var(--fap-warning) 28%, transparent); }
.fap-badge.danger  { background: color-mix(in srgb, var(--fap-danger) 15%, transparent);
  color: var(--fap-danger); border-color: color-mix(in srgb, var(--fap-danger) 28%, transparent); }
.fap-badge.info    { background: color-mix(in srgb, var(--fap-info) 15%, transparent);
  color: var(--fap-info); border-color: color-mix(in srgb, var(--fap-info) 28%, transparent); }
.fap-badge.neutral { background: var(--fap-surface-alt); color: var(--fap-text-muted);
  border-color: var(--fap-border); }
.fap-badge.captain { background: color-mix(in srgb, var(--fap-primary) 16%, transparent);
  color: var(--fap-primary); border-color: color-mix(in srgb, var(--fap-primary) 34%, transparent); font-weight: 700; }
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
  gap: var(--fap-space-4); padding: 11px 20px; margin-bottom: var(--fap-space-4);
  background: color-mix(in srgb, var(--fap-surface) 92%, transparent);
  backdrop-filter: saturate(140%) blur(8px);
  border: 1px solid var(--fap-border); border-radius: var(--fap-radius-lg);
  box-shadow: var(--fap-shadow-sm);
  overflow: hidden;                 /* defensive: never spill a narrow column */
}
.fap-shell-header .left { display: flex; align-items: center; gap: var(--fap-space-3); min-width: 0; }
.fap-shell-header .titles { display: flex; flex-direction: column; line-height: 1.2; min-width: 0; gap: 1px; }
.fap-shell-header .titles b { font-size: 0.98rem; color: var(--fap-text); }
.fap-shell-header .crumbs { font-size: 0.75rem; color: var(--fap-text-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fap-shell-header .crumbs .fap-breadcrumb b { color: var(--fap-text); font-weight: 600; }
.fap-shell-header .right { display: flex; align-items: center; gap: var(--fap-space-3);
  color: var(--fap-text-muted); font-size: 0.82rem; white-space: nowrap;
  flex-shrink: 0; min-width: 0; }
.fap-shell-header .left { flex: 1 1 auto; overflow: hidden; }
.fap-shell-header .fap-logos img { height: 34px; }
.fap-shell-header .sep { color: var(--fap-text-subtle); }
.fap-shell-header .mod-chip { display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; border-radius: var(--fap-radius-md); flex: 0 0 auto;
  background: color-mix(in srgb, var(--fap-primary) 14%, transparent); color: var(--fap-primary); }
.fap-shell-header .mod-title { font-size: 1.12rem; font-weight: var(--fap-weight-black);
  letter-spacing: -0.02em; color: var(--fap-text); line-height: 1.2; }
.fap-shell-header .hbtn { display: inline-flex; align-items: center; justify-content: center;
  position: relative; width: 34px; height: 34px; border-radius: var(--fap-radius-md);
  color: var(--fap-text-muted); background: transparent; border: 1px solid transparent;
  cursor: pointer; transition: all var(--fap-transition-fast); }
.fap-shell-header .hbtn:hover { background: var(--fap-hover); color: var(--fap-text);
  border-color: var(--fap-border); }
.fap-shell-header .hbtn.has { color: var(--fap-text); }
.fap-shell-header .chip-count { position: absolute; top: -3px; right: -3px; min-width: 15px; height: 15px;
  padding: 0 3px; border-radius: 999px; background: var(--fap-danger); color: #fff;
  font-size: 0.62rem; font-weight: 800; display: inline-flex; align-items: center; justify-content: center;
  box-shadow: 0 0 0 2px var(--fap-surface); }
.fap-shell-header .hsep { width: 1px; height: 22px; background: var(--fap-border); flex: 0 0 auto; }
.fap-shell-header .user { display: inline-flex; align-items: center; gap: 8px; }
.fap-shell-header .uava { display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 999px; flex: 0 0 auto;
  background: var(--fap-primary); color: var(--fap-on-primary); font-size: 0.72rem; font-weight: 800; }
.fap-shell-header .uinfo { display: flex; align-items: center; gap: 8px; }
.fap-shell-header .uinfo b { color: var(--fap-text); font-size: 0.85rem; font-weight: 700; }
.fap-login { text-align: center; padding: 8px 0 4px; }
.fap-login .fap-logos { justify-content: center; margin-bottom: 14px; }
.fap-login h2 { margin: 6px 0 2px; }
.fap-login .powered { color: var(--fap-text-muted); font-size: 0.85rem; }

/* ---- page/section heading block ---------------------------------------- */
.fap-page-head { display: flex; align-items: center; gap: var(--fap-space-3);
  margin: 0 0 var(--fap-space-3); }
.fap-page-head .fap-title-chip { display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; border-radius: var(--fap-radius-md);
  background: color-mix(in srgb, var(--fap-primary) 14%, transparent);
  color: var(--fap-primary); flex: 0 0 auto; }
.fap-page-head .eyebrow { color: var(--fap-primary); font-size: 0.68rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: var(--fap-tracking-wider); margin-bottom: 2px; }
.fap-page-head .title { margin: 0; font-size: var(--fap-text-2xl); font-weight: var(--fap-weight-black);
  letter-spacing: -0.02em; line-height: 1.15; }
.fap-page-head .subtitle { color: var(--fap-text-muted); font-size: 0.9rem; margin-top: 3px; }

/* ---- metric cards + grid (dense, StatsBomb/Hudl KPI tiles) -------------- */
.fap-metric-grid { display: grid; gap: var(--fap-space-2);
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr)); margin-bottom: var(--fap-space-2); }
.fap-metric { display: flex; flex-direction: column; gap: 6px; min-height: 84px;
  padding: 12px 14px; cursor: default; }
.fap-metric:hover { transform: translateY(-2px); box-shadow: var(--fap-shadow-md);
  border-color: color-mix(in srgb, var(--fap-primary) 30%, var(--fap-border)); }
.fap-metric .top { display: flex; align-items: center; gap: 7px; }
.fap-metric .label { color: var(--fap-text-muted); font-size: 0.7rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em; }
.fap-metric .value { color: var(--fap-text); font-size: 2.15rem; font-weight: var(--fap-weight-extrabold);
  letter-spacing: -0.03em; line-height: 1.02; }
.fap-metric .foot { display: flex; align-items: center; gap: 8px; margin-top: auto; }
.fap-metric .hint { color: var(--fap-text-subtle); font-size: 0.72rem; }
.fap-metric-chip { display: inline-flex; align-items: center; justify-content: center;
  width: 26px; height: 26px; border-radius: var(--fap-radius-sm);
  background: var(--fap-surface-alt); color: var(--fap-text-muted); flex: 0 0 auto; }
.fap-metric-chip.accent-primary { background: color-mix(in srgb, var(--fap-primary) 15%, transparent); color: var(--fap-primary); }
.fap-metric-chip.accent-success { background: color-mix(in srgb, var(--fap-success) 15%, transparent); color: var(--fap-success); }
.fap-metric-chip.accent-warning { background: color-mix(in srgb, var(--fap-warning) 15%, transparent); color: var(--fap-warning); }
.fap-metric-chip.accent-danger  { background: color-mix(in srgb, var(--fap-danger) 15%, transparent); color: var(--fap-danger); }
.fap-metric-chip.accent-info    { background: color-mix(in srgb, var(--fap-info) 15%, transparent); color: var(--fap-info); }
.fap-trend { display: inline-flex; align-items: center; gap: 2px; font-size: 0.78rem; font-weight: 700;
  padding: 1px 7px; border-radius: var(--fap-radius-full); }
.fap-trend.up { color: var(--fap-success); background: color-mix(in srgb, var(--fap-success) 14%, transparent); }
.fap-trend.down { color: var(--fap-danger); background: color-mix(in srgb, var(--fap-danger) 14%, transparent); }
.fap-trend.flat { color: var(--fap-text-muted); background: var(--fap-surface-alt); }
.fap-stat-tile { display: flex; flex-direction: column; gap: 2px; padding: 10px 14px;
  background: var(--fap-surface); border: 1px solid var(--fap-border); border-radius: var(--fap-radius-md); }
.fap-stat-tile .v { font-size: 1.25rem; font-weight: var(--fap-weight-bold); color: var(--fap-text); }
.fap-stat-tile .v .sub { font-size: 0.8rem; color: var(--fap-text-subtle); margin-left: 3px; font-weight: 600; }
.fap-stat-tile .l { font-size: 0.72rem; color: var(--fap-text-muted); text-transform: uppercase; letter-spacing: 0.03em; }

/* ---- alerts ------------------------------------------------------------ */
.fap-alert { display: flex; gap: 10px; padding: 12px 14px; border-radius: var(--fap-radius-md);
  border: 1px solid var(--fap-border); background: var(--fap-surface); margin-bottom: var(--fap-space-3);
  border-left-width: 3px; }
.fap-alert .ico { flex: 0 0 auto; margin-top: 1px; }
.fap-alert .title { font-weight: 700; margin-bottom: 1px; }
.fap-alert .msg { color: var(--fap-text-muted); font-size: 0.86rem; }
.fap-alert.info    { border-left-color: var(--fap-info); }    .fap-alert.info .ico { color: var(--fap-info); }
.fap-alert.success { border-left-color: var(--fap-success); } .fap-alert.success .ico { color: var(--fap-success); }
.fap-alert.warning { border-left-color: var(--fap-warning); } .fap-alert.warning .ico { color: var(--fap-warning); }
.fap-alert.danger  { border-left-color: var(--fap-danger); }  .fap-alert.danger .ico { color: var(--fap-danger); }

/* ---- empty state ------------------------------------------------------- */
.fap-empty { display: flex; flex-direction: column; align-items: center; text-align: center;
  gap: 8px; padding: 40px 24px; border: 1px dashed var(--fap-border); border-radius: var(--fap-radius-lg);
  background: color-mix(in srgb, var(--fap-surface-alt) 50%, transparent); }
.fap-empty .art { display: inline-flex; align-items: center; justify-content: center;
  width: 64px; height: 64px; border-radius: var(--fap-radius-full);
  background: var(--fap-surface); border: 1px solid var(--fap-border); color: var(--fap-text-subtle);
  box-shadow: var(--fap-shadow-sm); margin-bottom: 4px; }
.fap-empty .title { font-size: 1.05rem; font-weight: 700; color: var(--fap-text); }
.fap-empty .desc { color: var(--fap-text-muted); font-size: 0.88rem; max-width: 420px; }
.fap-empty .cta-hint { color: var(--fap-text-subtle); font-size: 0.8rem; margin-top: 4px; }

/* ---- skeleton loaders -------------------------------------------------- */
.fap-skeleton { display: flex; flex-direction: column; gap: 10px; }
.sk-line, .sk-avatar { position: relative; overflow: hidden; border-radius: var(--fap-radius-sm);
  background: var(--fap-surface-alt); }
.sk-line { height: 12px; }
.sk-avatar { width: 48px; height: 48px; border-radius: var(--fap-radius-full); margin-bottom: 6px; }
.fap-sk-card { display: flex; flex-direction: column; gap: 8px; }
.sk-line::after, .sk-avatar::after { content: ""; position: absolute; inset: 0;
  transform: translateX(-100%);
  background: linear-gradient(90deg, transparent,
    color-mix(in srgb, var(--fap-text) 8%, transparent), transparent);
  animation: fap-shimmer 1.3s infinite; }

/* ---- avatars ----------------------------------------------------------- */
.fap-avatar { display: inline-flex; align-items: center; justify-content: center;
  border-radius: var(--fap-radius-full); overflow: hidden; background: var(--fap-surface-alt);
  color: var(--fap-text-muted); font-weight: 700; flex: 0 0 auto; }
.fap-avatar img { width: 100%; height: 100%; object-fit: cover; }
.fap-avatar.ring-success { box-shadow: 0 0 0 2px var(--fap-surface), 0 0 0 4px var(--fap-success); }
.fap-avatar.ring-danger  { box-shadow: 0 0 0 2px var(--fap-surface), 0 0 0 4px var(--fap-danger); }
.fap-avatar.ring-warning { box-shadow: 0 0 0 2px var(--fap-surface), 0 0 0 4px var(--fap-warning); }

/* ---- player cards + card grid ------------------------------------------ */
.fap-card-grid { display: grid; gap: var(--fap-space-3);
  grid-template-columns: repeat(auto-fill, minmax(216px, 1fr)); }
.fap-player-card { padding: 0; overflow: hidden; display: flex; flex-direction: column; }
.fap-player-card .photo { position: relative; aspect-ratio: 4 / 3; width: 100%;
  background: linear-gradient(160deg, var(--fap-surface-alt), var(--fap-surface));
  display: flex; align-items: center; justify-content: center; }
.fap-player-card .photo img { width: 100%; height: 100%; object-fit: cover; }
.fap-player-card .photo.empty .ini { font-size: 2rem; font-weight: var(--fap-weight-black);
  color: var(--fap-text-subtle); letter-spacing: 0.04em; }
.fap-player-card .photo .num { position: absolute; top: 8px; left: 10px;
  font-size: 1.4rem; font-weight: var(--fap-weight-black); color: var(--fap-text);
  background: color-mix(in srgb, var(--fap-surface) 70%, transparent);
  border-radius: var(--fap-radius-sm); padding: 0 8px; backdrop-filter: blur(4px); line-height: 1.4; }
.fap-player-card .body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 8px; }
.fap-player-card .name { font-size: 1.02rem; font-weight: 750; letter-spacing: -0.01em;
  color: var(--fap-text); line-height: 1.2; }
.fap-player-card .badges { display: flex; flex-wrap: wrap; gap: 4px; }
.fap-player-card .meta { display: flex; flex-wrap: wrap; gap: 6px 12px; }
.fap-player-card .meta .m { display: inline-flex; align-items: center; gap: 4px;
  color: var(--fap-text-muted); font-size: 0.78rem; }
.fap-player-card .meta .m .fap-icon { color: var(--fap-text-subtle); }

/* ---- chips & progress -------------------------------------------------- */
.fap-chip { display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px;
  border-radius: var(--fap-radius-full); font-size: 0.78rem; font-weight: 600;
  background: var(--fap-surface); border: 1px solid var(--fap-border); color: var(--fap-text-muted);
  cursor: pointer; transition: all var(--fap-transition-fast); }
.fap-chip:hover { border-color: var(--fap-border-strong); color: var(--fap-text); }
.fap-chip.active { background: color-mix(in srgb, var(--fap-primary) 14%, transparent);
  color: var(--fap-primary); border-color: color-mix(in srgb, var(--fap-primary) 34%, transparent); }
.fap-progress { display: flex; flex-direction: column; gap: 4px; }
.fap-progress .pl { font-size: 0.76rem; color: var(--fap-text-muted); }
.fap-progress .track { height: 7px; border-radius: var(--fap-radius-full);
  background: var(--fap-surface-alt); overflow: hidden; }
.fap-progress .fill { height: 100%; border-radius: var(--fap-radius-full); background: var(--fap-primary);
  transition: width var(--fap-transition-slow, 320ms ease); }
.fap-progress.success .fill { background: var(--fap-success); }
.fap-progress.warning .fill { background: var(--fap-warning); }
.fap-progress.danger .fill { background: var(--fap-danger); }

/* ---- activity feed ----------------------------------------------------- */
.fap-activity { padding: 4px 4px; }
.fap-activity-row { display: flex; align-items: center; gap: 10px; padding: 9px 10px;
  border-radius: var(--fap-radius-sm); }
.fap-activity-row:hover { background: var(--fap-hover); }
.fap-activity-row + .fap-activity-row { border-top: 1px solid var(--fap-border); }
.fap-activity-row code { background: var(--fap-surface-alt); color: var(--fap-text);
  padding: 1px 7px; border-radius: var(--fap-radius-xs); font-size: 0.76rem; }
.fap-activity-row .who { color: var(--fap-text-muted); font-size: 0.82rem; }
.fap-activity-row .ts { margin-left: auto; color: var(--fap-text-subtle); font-size: 0.75rem; white-space: nowrap; }
"""


def _forms() -> str:
    return """
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  border-radius: var(--fap-radius-md); font-weight: 600;
  border: 1px solid var(--fap-border); transition: all var(--fap-transition-fast);
  box-shadow: var(--fap-shadow-xs);
  /* explicit themed surface: Streamlit's base theme is light, so a secondary button
     with no background leaks white in dark mode. Sidebar/rail buttons override this. */
  background: var(--fap-surface); color: var(--fap-text);
}
.stButton > button:hover, .stDownloadButton > button:hover {
  background: var(--fap-hover); border-color: var(--fap-primary);
  color: var(--fap-primary); box-shadow: var(--fap-shadow-sm); }
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button {
  background: var(--fap-primary); border-color: var(--fap-primary); color: var(--fap-on-primary);
}
.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button:hover {
  background: var(--fap-primary-hover); border-color: var(--fap-primary-hover);
  color: var(--fap-on-primary); box-shadow: var(--fap-shadow-md); transform: translateY(-1px); }
.stButton > button:active, .stDownloadButton > button:active { transform: translateY(0); }
/* inputs: consistent radius, quiet borders, branded focus ring */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-baseweb="select"] > div, [data-testid="stTextArea"] textarea,
[data-baseweb="input"] { border-radius: var(--fap-radius-md) !important; }
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea, [data-baseweb="select"] > div {
  background: var(--fap-surface) !important; border-color: var(--fap-border) !important; }
[data-testid="stTextInput"] input:focus, [data-testid="stNumberInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
  border-color: var(--fap-primary) !important;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--fap-primary) 22%, transparent) !important; }
[data-baseweb="checkbox"] svg, [data-baseweb="radio"] svg { color: var(--fap-primary); }
label, [data-testid="stWidgetLabel"] p { font-weight: 600 !important; color: var(--fap-text) !important; }
[data-testid="stFileUploaderDropzone"] {
  border-radius: var(--fap-radius-lg); border: 1.5px dashed var(--fap-border);
  background: var(--fap-surface-alt); transition: border-color var(--fap-transition-fast); }
[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--fap-primary); }
/* segmented radio / tabs / metric / expander: native widgets, branded */
[data-testid="stTabs"] [data-baseweb="tab-list"] { gap: 2px; border-bottom: 1px solid var(--fap-border);
  background: transparent; }
[data-testid="stTabs"] [data-baseweb="tab"] { border-radius: var(--fap-radius-sm) var(--fap-radius-sm) 0 0;
  color: var(--fap-text-muted); font-weight: 600; padding: 8px 14px; }
[data-testid="stTabs"] [data-baseweb="tab"]:hover { color: var(--fap-text); background: var(--fap-hover); }
[data-testid="stTabs"] [aria-selected="true"] { color: var(--fap-primary) !important; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"] { background: var(--fap-primary); height: 2.5px; }
[data-testid="stMetric"] { background: var(--fap-surface); border: 1px solid var(--fap-border);
  border-radius: var(--fap-radius-md); padding: 11px 14px; box-shadow: var(--fap-shadow-xs);
  transition: transform var(--fap-transition), box-shadow var(--fap-transition), border-color var(--fap-transition); }
[data-testid="stMetric"]:hover { transform: translateY(-2px); box-shadow: var(--fap-shadow-md);
  border-color: color-mix(in srgb, var(--fap-primary) 30%, var(--fap-border)); }
[data-testid="stMetricLabel"] { color: var(--fap-text-muted); }
[data-testid="stMetricLabel"] p { font-size: 0.7rem !important; font-weight: 600 !important;
  text-transform: uppercase; letter-spacing: 0.04em; }
[data-testid="stMetricValue"] { font-weight: var(--fap-weight-extrabold); letter-spacing: -0.03em;
  font-size: 2.05rem; line-height: 1.05; }
[data-testid="stExpander"] { border: 1px solid var(--fap-border); border-radius: var(--fap-radius-lg);
  background: var(--fap-surface); box-shadow: var(--fap-shadow-xs); overflow: hidden; }
[data-testid="stExpander"] summary:hover { color: var(--fap-primary); }
[data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] { background: var(--fap-primary); }
[data-baseweb="tag"] { background: color-mix(in srgb, var(--fap-primary) 16%, transparent) !important;
  color: var(--fap-primary) !important; border-radius: var(--fap-radius-sm) !important; }
[data-testid="stToast"] { border-radius: var(--fap-radius-md); border: 1px solid var(--fap-border); }

/* ============================================================================
   COMPREHENSIVE native-widget theming — every FAP token flips per mode, so ONE
   set of rules themes BOTH light and dark. !important beats Streamlit's baked
   base-theme styles. Stable BaseWeb/testid selectors only (no generated classes).
   ============================================================================ */
/* every BaseWeb input/select/textarea surface (covers select, multiselect, text,
   number, date, time, and their inner wrappers) */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"],
[data-baseweb="select"] > div, [data-testid="stTextInput"] > div > div,
[data-testid="stNumberInput"] > div > div, [data-testid="stDateInput"] > div > div,
[data-testid="stTimeInput"] > div > div {
  background: var(--fap-surface) !important; border-color: var(--fap-border) !important;
  color: var(--fap-text) !important; }
[data-baseweb="input"] input, [data-baseweb="base-input"] input, textarea, [role="spinbutton"] {
  background: transparent !important; color: var(--fap-text) !important; }
input::placeholder, textarea::placeholder, [data-baseweb="select"] [class*="placeholder"] {
  color: var(--fap-text-subtle) !important; }
/* select value + chevron */
[data-baseweb="select"] { color: var(--fap-text) !important; }
[data-baseweb="select"] svg, [data-baseweb="input"] svg { fill: var(--fap-text-muted) !important;
  color: var(--fap-text-muted) !important; }
/* number-input +/- steppers */
[data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"] {
  background: var(--fap-surface) !important; color: var(--fap-text-muted) !important;
  border-color: var(--fap-border) !important; }
[data-testid="stNumberInputStepUp"]:hover, [data-testid="stNumberInputStepDown"]:hover {
  background: var(--fap-hover) !important; color: var(--fap-primary) !important; }
/* radio + checkbox + toggle: labels readable, marks branded */
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label,
[data-testid="stRadio"] [role="radiogroup"] div { color: var(--fap-text) !important; }
[data-baseweb="radio"] [data-checked="true"] div, [data-baseweb="checkbox"] [data-checked="true"] > div,
[data-baseweb="checkbox"] [aria-checked="true"] { background: var(--fap-primary) !important;
  border-color: var(--fap-primary) !important; }
[data-baseweb="radio"] div, [data-baseweb="checkbox"] div { border-color: var(--fap-border-strong) !important; }
/* slider: rail neutral, filled track + thumb branded */
[data-baseweb="slider"] [role="slider"] { background: var(--fap-primary) !important; }
[data-baseweb="slider"] > div > div { background: var(--fap-surface-alt) !important; }
[data-baseweb="slider"] [data-testid="stThumbValue"] { color: var(--fap-text) !important; }
/* file uploader: dropzone (kept) + browse button surface */
[data-testid="stFileUploader"] button, [data-testid="stFileUploaderDropzone"] button {
  background: var(--fap-surface) !important; color: var(--fap-text) !important;
  border-color: var(--fap-border) !important; }
/* expander header surface + code blocks + captions */
[data-testid="stExpander"] summary { background: var(--fap-surface) !important; color: var(--fap-text) !important; }
[data-testid="stExpander"] details { background: var(--fap-surface) !important; }
pre, code, [data-testid="stCode"] { background: var(--fap-surface-alt) !important; color: var(--fap-text) !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--fap-text-muted) !important; }
/* the whole widget-baseweb popover trigger (Theme/Account/etc.) uses the button surface */
[data-testid="stPopover"] > div > button, [data-testid="stPopover"] button[kind="secondary"] {
  background: var(--fap-surface) !important; color: var(--fap-text) !important;
  border-color: var(--fap-border) !important; }
"""


def _tables() -> str:
    return """
[data-testid="stTable"], .stDataFrame, [data-testid="stDataFrame"] {
  border-radius: var(--fap-radius-md); overflow: hidden; border: 1px solid var(--fap-border); }
[data-testid="stTable"] thead th, .stDataFrame thead th {
  position: sticky; top: 0; z-index: 1;
  background: var(--fap-surface-alt); color: var(--fap-text-muted);
  font-weight: 700; font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.03em;
  border-bottom: 1px solid var(--fap-border-strong);
}
[data-testid="stTable"] tbody tr:nth-child(even) { background: color-mix(in srgb, var(--fap-surface-alt) 45%, transparent); }
[data-testid="stTable"] tbody tr:hover, .stDataFrame tbody tr:hover { background: var(--fap-hover); }
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
@keyframes fap-shimmer { 100% { transform: translateX(100%); } }
@keyframes fap-spin { to { transform: rotate(360deg); } }
.fap-spin { animation: fap-spin 0.9s linear infinite; transform-origin: center; display: inline-flex; }
/* main content blocks fade in for a polished, non-janky page load */
[data-testid="stMainBlockContainer"] > div > [data-testid="stVerticalBlock"] { animation: fap-fade-in var(--fap-transition); }
"""


def _studio() -> str:
    """Report Studio workspace chrome: the sticky toolbar, the editor rail with
    section cards + drag handles, the outline, and the A4 preview stage."""
    return """
.fap-studio-toolbar { display: flex; align-items: center; gap: var(--fap-space-3);
  padding: 10px 14px; margin-bottom: var(--fap-space-3); background: var(--fap-surface);
  border: 1px solid var(--fap-border); border-radius: var(--fap-radius-lg);
  box-shadow: var(--fap-shadow-sm); position: sticky; top: 0; z-index: 20; flex-wrap: wrap; }
.fap-studio-toolbar .rt-title { font-size: 1.05rem; font-weight: var(--fap-weight-bold);
  letter-spacing: -0.01em; color: var(--fap-text); }
.fap-studio-toolbar .rt-meta { color: var(--fap-text-muted); font-size: 0.76rem; }
.fap-studio-toolbar .spacer { flex: 1 1 auto; }
.fap-rail-head { display: flex; align-items: center; gap: 8px; margin: 4px 0 8px;
  font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: var(--fap-tracking-wider); color: var(--fap-text-subtle); }
.fap-rail-head::after { content: ""; flex: 1; height: 1px; background: var(--fap-border); }
/* section cards in the editor rail */
.fap-sec-card { display: flex; align-items: center; gap: 10px; padding: 9px 11px;
  border: 1px solid var(--fap-border); border-radius: var(--fap-radius-md);
  background: var(--fap-surface); box-shadow: var(--fap-shadow-xs); }
.fap-sec-card .grip { color: var(--fap-text-subtle); display: flex; flex: 0 0 auto; }
.fap-sec-card .idx { width: 20px; text-align: center; font-size: 11px; font-weight: 800;
  color: var(--fap-text-subtle); flex: 0 0 auto; }
.fap-sec-card .name { flex: 1 1 auto; font-weight: 600; font-size: 0.88rem; color: var(--fap-text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fap-sec-card.hidden .name { text-decoration: line-through; color: var(--fap-text-subtle); }
/* outline / table of contents */
.fap-outline { display: flex; flex-direction: column; gap: 2px; }
.fap-outline .oi { display: flex; align-items: center; gap: 8px; padding: 5px 8px;
  border-radius: var(--fap-radius-sm); color: var(--fap-text-muted); font-size: 0.82rem; }
.fap-outline .oi:hover { background: var(--fap-hover); color: var(--fap-text); }
.fap-outline .oi .n { width: 18px; color: var(--fap-text-subtle); font-size: 0.72rem;
  font-weight: 700; text-align: center; }
.fap-outline .oi.h1 { font-weight: 700; color: var(--fap-text); }
.fap-outline .oi.muted { opacity: 0.55; }
/* A4 preview stage header */
.fap-stage-bar { display: flex; align-items: center; gap: var(--fap-space-3);
  padding: 8px 12px; background: var(--fap-surface-alt); border: 1px solid var(--fap-border);
  border-bottom: none; border-radius: var(--fap-radius-lg) var(--fap-radius-lg) 0 0;
  color: var(--fap-text-muted); font-size: 0.8rem; }
.fap-stage-bar .pg { font-weight: 700; color: var(--fap-text); }
.fap-stage-wrap { border: 1px solid var(--fap-border); border-top: none;
  border-radius: 0 0 var(--fap-radius-lg) var(--fap-radius-lg); overflow: hidden;
  box-shadow: var(--fap-shadow-md); }

/* ---- Data Hub: health grid, compatibility, preview table --------------- */
.fap-health-grid { display: grid; gap: 8px;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.fap-health-axis { display: flex; align-items: center; gap: 9px; padding: 9px 11px;
  border: 1px solid var(--fap-border); border-radius: var(--fap-radius-md); background: var(--fap-surface); }
.fap-health-axis .dot { width: 11px; height: 11px; border-radius: 999px; flex: 0 0 auto; }
.fap-health-axis .dot.green { background: var(--fap-success); }
.fap-health-axis .dot.yellow { background: var(--fap-warning); }
.fap-health-axis .dot.red { background: var(--fap-danger); }
.fap-health-axis .lbl { font-weight: 600; font-size: 0.84rem; color: var(--fap-text); }
.fap-health-axis .sub { font-size: 0.72rem; color: var(--fap-text-subtle); margin-left: auto; }
.fap-compat-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px;
  border-radius: var(--fap-radius-sm); }
.fap-compat-row + .fap-compat-row { border-top: 1px solid var(--fap-border); }
.fap-compat-row .mod { font-weight: 600; color: var(--fap-text); min-width: 120px; }
.fap-compat-row .why { color: var(--fap-text-muted); font-size: 0.8rem; }
.fap-dh-table { width: 100%; border-collapse: collapse; font-size: 0.8rem;
  font-feature-settings: var(--fap-feature-tabular); }
.fap-dh-table th { position: sticky; top: 0; background: var(--fap-surface-alt);
  color: var(--fap-text-muted); text-transform: uppercase; font-size: 0.68rem;
  letter-spacing: 0.03em; text-align: left; padding: 7px 10px;
  border-bottom: 1px solid var(--fap-border-strong); white-space: nowrap; }
.fap-dh-table td { padding: 6px 10px; border-bottom: 1px solid var(--fap-border);
  color: var(--fap-text); white-space: nowrap; }
.fap-dh-table tr:hover td { background: var(--fap-hover); }
.fap-dh-table td.cell-error { background: color-mix(in srgb, var(--fap-danger) 20%, transparent);
  color: var(--fap-danger); font-weight: 600; }
.fap-dh-table td.cell-warning { background: color-mix(in srgb, var(--fap-warning) 18%, transparent);
  color: var(--fap-warning); }
.fap-dh-scroll { max-height: 460px; overflow: auto; border: 1px solid var(--fap-border);
  border-radius: var(--fap-radius-md); }
.fap-dh-card { display: flex; flex-direction: column; gap: 8px; }
.fap-dh-card .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.fap-dh-card .nm { font-weight: 750; font-size: 1rem; color: var(--fap-text); }
.fap-dh-card .meta { display: flex; flex-wrap: wrap; gap: 4px 14px; color: var(--fap-text-muted);
  font-size: 0.78rem; }
/* sidebar Current Dataset indicator (single source of truth) */
.fap-active-ds { border: 1px solid var(--fap-border); border-radius: var(--fap-radius-md);
  background: var(--fap-surface); padding: 9px 11px; margin: 2px 0 6px;
  box-shadow: var(--fap-shadow-xs); }
.fap-active-ds .nm { font-weight: 700; font-size: 0.88rem; color: var(--fap-text);
  margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fap-active-ds .mt { font-size: 0.74rem; color: var(--fap-text-muted); margin-top: 1px; }
.fap-active-ds.empty { display: flex; flex-direction: column; color: var(--fap-text-muted);
  font-size: 0.82rem; font-weight: 600; }
.fap-active-ds.empty span { font-weight: 400; font-size: 0.74rem; color: var(--fap-text-subtle);
  margin-top: 2px; }
/* player visualization workspace context bar */
.fap-viz-context { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px;
  padding: 9px 13px; margin-bottom: var(--fap-space-3); border: 1px solid var(--fap-border);
  border-radius: var(--fap-radius-md); background: var(--fap-surface-alt); font-size: 0.84rem;
  color: var(--fap-text-muted); }
.fap-viz-context b { color: var(--fap-text); }
.fap-viz-context .fap-icon { color: var(--fap-text-subtle); }
/* visualization catalog cards */
.fap-viz-card { border: 1px solid var(--fap-border); border-radius: var(--fap-radius-md);
  background: var(--fap-surface); padding: 10px 12px; margin-bottom: 4px;
  box-shadow: var(--fap-shadow-xs); }
.fap-viz-card .h { display: flex; align-items: center; gap: 7px; font-size: 0.9rem;
  color: var(--fap-text); }
.fap-viz-card .h .fap-icon { color: var(--fap-primary); }
.fap-viz-card .h b { font-weight: 700; }
.fap-viz-card .d { color: var(--fap-text-muted); font-size: 0.78rem; margin: 3px 0 4px;
  min-height: 1.1em; }
.fap-viz-card .e { color: var(--fap-text-subtle); font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.03em; }
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


def _app_shell() -> str:
    """Phase 13.2 professional application shell - Concept B (Hudl Sportscode).

    A fixed rail (keyed st.container ``.st-key-fap_rail``) with a dual-logo brand
    block, a pill search, uppercase section labels, chunky 48px navigation rows,
    muted compact recent rows, and a footer status card. The navigation rows are
    REAL st.buttons (native, always clickable in Streamlit) styled here to look
    like desktop nav items - the per-row icon is a CSS mask, the active page is the
    ``[kind="primary"]`` button (filled pill + 4px accent bar + glow); the click
    runs Python in-session (no href, no query params, no browser navigation). The
    brand block, section labels and footer are non-interactive HTML. Native sidebar
    + its collapse control are hidden. Width var --fap-rail-width drives the 280/72
    collapse (0.3s). Theme-token colours only; transitions only."""
    return """
/* retire Streamlit's native sidebar AND its collapse control - the shell owns nav */
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"], [data-testid="collapsedControl"],
button[data-testid="stSidebarCollapseButton"] { display: none !important; }

/* main content sits to the RIGHT of the fixed rail and reflows when it collapses */
[data-testid="stAppViewContainer"] { margin-left: var(--fap-rail-width, 280px);
  transition: margin-left 0.3s ease; }
[data-testid="stMainBlockContainer"], .block-container {
  padding-left: var(--fap-space-6) !important; padding-right: var(--fap-space-6) !important; }

/* ---- the fixed rail ---- */
/* the WHOLE rail scrolls as one column (robust: no reliance on Streamlit's nested
   wrappers keeping a flex chain intact), so every element - including the footer
   and the last nav items - is always reachable. */
.st-key-fap_rail { position: fixed; inset: 0 auto 0 0; z-index: 1000;
  width: var(--fap-rail-width, 280px); background: var(--fap-surface);
  border-right: 1px solid var(--fap-border); box-shadow: var(--fap-shadow-lg);
  overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain;
  transition: width 0.3s ease; padding: 0 0 var(--fap-space-4) !important; }
.st-key-fap_rail_nav { padding: var(--fap-space-2) var(--fap-space-3); }
.st-key-fap_rail_footer { margin-top: var(--fap-space-2); }
/* brand stays pinned at the top while the rest scrolls */
.st-key-fap_rail .nv-brand { position: sticky; top: 0; z-index: 3; background: var(--fap-surface); }

/* ---- 1) brand block: FC Masar x Right To Dream, centred + divider accent ---- */
.nv-brand { padding: 14px 16px 12px; border-bottom: 1px solid var(--fap-border); position: relative; }
.nv-brand::after { content: ""; position: absolute; left: 16px; right: 16px; bottom: -1px; height: 2px;
  background: var(--fap-primary); border-radius: 2px; opacity: .9; }
.nv-brand.collapsed { padding: 12px 0; display: flex; justify-content: center; }
.nv-logos { display: flex; align-items: center; justify-content: center; gap: 12px; }
.nv-logos img.nv-logo { height: 30px; width: auto; object-fit: contain; display: block; }
.nv-logo-sep { width: 1px; height: 22px; background: var(--fap-border); }
.nv-brand-title { text-align: center; margin-top: 9px; font-size: 13px; font-weight: 800; line-height: 1.2;
  letter-spacing: -.01em; color: var(--fap-text); }
.nv-brand-sub { text-align: center; margin-top: 3px; font-size: 10px; font-weight: 600; letter-spacing: .06em;
  color: var(--fap-text-subtle); }

/* ---- 3) search pill (styled st.text_input; icon inside) ---- */
.st-key-fap_rail [data-testid="stTextInput"] { padding: var(--fap-space-4) var(--fap-space-4) var(--fap-space-2); }
.st-key-_nav_search [data-testid="stTextInputRootElement"] { position: relative; }
.st-key-_nav_search [data-testid="stTextInputRootElement"]::before { content: ""; position: absolute; left: 16px;
  top: 50%; transform: translateY(-50%); width: 16px; height: 16px; z-index: 3; pointer-events: none;
  background-color: var(--fap-text-subtle); -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center; -webkit-mask-size: contain; mask-size: contain; }
.st-key-_nav_search [data-baseweb="input"], .st-key-_nav_search [data-baseweb="base-input"] {
  height: 46px; border-radius: 14px; background: var(--fap-bg) !important; border: 1px solid var(--fap-border);
  transition: border-color 150ms ease, box-shadow 150ms ease; }
.st-key-_nav_search input { height: 44px; padding-left: 38px !important; background: transparent !important;
  font-size: var(--fap-text-sm); border: 0 !important; }
.st-key-_nav_search [data-testid="stTextInputRootElement"]:focus-within [data-baseweb="input"] {
  border-color: var(--fap-primary); box-shadow: 0 0 0 3px color-mix(in srgb, var(--fap-primary) 18%, transparent); }

/* ---- 4) section titles ---- */
.nv-sec { margin: 13px 12px 6px; color: var(--fap-text-subtle); font-size: 11px; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase; }

/* ---- navigation rows = REAL st.buttons, styled as desktop nav items ----
   The button IS the row (native, always clickable in Streamlit). No overlay. */
.st-key-fap_rail .stButton { margin: 2px 0; }
.st-key-fap_rail .stButton > button { display: flex; align-items: center; justify-content: flex-start;
  width: 100%; min-height: 38px; text-align: left; font-weight: 500; font-size: 13.5px;
  padding: 0 12px; border: 1px solid transparent; background: transparent; border-radius: 10px;
  color: var(--fap-text-muted); white-space: nowrap; overflow: hidden;
  transition: background 150ms ease, color 150ms ease, transform 150ms ease, box-shadow 200ms ease; }
.st-key-fap_rail .stButton > button:hover { background: var(--fap-hover); color: var(--fap-text);
  transform: translateX(3px); }
.st-key-fap_rail .stButton > button::before { content: ""; display: inline-block; flex: 0 0 auto;
  width: 18px; height: 18px; margin-right: 11px; background-color: currentColor;
  -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat; -webkit-mask-position: center;
  mask-position: center; -webkit-mask-size: contain; mask-size: contain; }
/* active page: BOLD solid-orange fill with on-primary text (matches the reference) */
.st-key-fap_rail .stButton > button[kind="primary"] {
  background: var(--fap-primary); color: var(--fap-on-primary); font-weight: 700; transform: none;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--fap-primary) 30%, transparent); }
.st-key-fap_rail .stButton > button[kind="primary"]:hover {
  background: var(--fap-primary-hover); color: var(--fap-on-primary); transform: none; }
/* recent rows: smaller, muted (keyed by st-key-rec_ prefix) */
.st-key-fap_rail [class*="st-key-rec_"] button { min-height: 32px; font-size: 12.5px;
  color: var(--fap-text-subtle); font-weight: 500; }
.st-key-fap_rail [class*="st-key-rec_"] button::before { width: 15px; height: 15px; margin-right: 10px; }
/* collapsible SECTION headers (dropdowns): a real button styled as a section label
   with a chevron that flips down/right with the open state (keyed by st-key-grp_) */
.st-key-fap_rail [class*="st-key-grp_"] .stButton > button { min-height: 28px; margin-top: 10px;
  padding: 0 10px; background: transparent; color: var(--fap-text-subtle); font-size: 11px;
  font-weight: 700; letter-spacing: .12em; text-transform: uppercase; transform: none; }
.st-key-fap_rail [class*="st-key-grp_"] .stButton > button:hover { background: transparent;
  color: var(--fap-text); transform: none; box-shadow: none; }
.st-key-fap_rail [class*="st-key-grp_"] .stButton > button::before { width: 13px; height: 13px;
  margin-right: 9px; opacity: .75; }

/* ---- 6) footer status card ---- */
.nv-footer { padding: var(--fap-space-4); }
.nv-card { border: 1px solid var(--fap-border); border-radius: 14px; background: var(--fap-bg); padding: 14px; }
.nv-card-title { font-size: 10.5px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;
  color: var(--fap-text-subtle); }
.nv-card-ds { font-size: 14px; font-weight: 700; color: var(--fap-text); margin: 6px 0 4px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nv-card-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--fap-text-muted); }
.nv-badge { background: var(--fap-surface); border: 1px solid var(--fap-border); border-radius: 6px;
  padding: 1px 7px; font-weight: 600; }
.nv-rows { color: var(--fap-text-muted); }
.nv-card-grid { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; margin: 12px 0; padding-top: 12px;
  border-top: 1px solid var(--fap-border); font-size: 12px; }
.nv-card-grid .k { color: var(--fap-text-subtle); }
.nv-card-grid .v { text-align: right; color: var(--fap-text); font-weight: 600; }
.nv-status { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px;
  font-size: 11px; font-weight: 600; }
.nv-status.ok { background: color-mix(in srgb, var(--fap-success) 16%, transparent); color: var(--fap-success); }
.nv-status.off { background: color-mix(in srgb, var(--fap-danger) 16%, transparent); color: var(--fap-danger); }
.nv-status-dot { width: 7px; height: 7px; border-radius: 999px; display: inline-block; }
.nv-status-dot.ok { background: var(--fap-success); }
.nv-status-dot.off { background: var(--fap-danger); }
.nv-footer.collapsed { display: flex; justify-content: center; padding: var(--fap-space-4) 0; }

/* ---- 7/header) sticky header; collapse + theme are icon st.buttons ---- */
.st-key-fap_header { position: sticky; top: 0; z-index: 900; background: var(--fap-bg);
  border-bottom: 1px solid var(--fap-border); padding: var(--fap-space-2) var(--fap-space-3);
  margin-bottom: var(--fap-space-4); }
.st-key-fap_header [data-testid="stHorizontalBlock"] { gap: var(--fap-space-3); align-items: center; }
.st-key-fap_header .stButton button { display: flex; align-items: center; justify-content: center;
  height: 40px; min-height: 40px; width: 100%; background: transparent; border: 1px solid transparent;
  color: var(--fap-text-muted); border-radius: var(--fap-radius-md); padding: 0;
  transition: background 150ms ease, color 150ms ease; }
.st-key-fap_header .stButton button:hover { background: var(--fap-hover); color: var(--fap-text); }
.st-key-fap_header .stButton button::before { content: ""; display: inline-block; width: 20px; height: 20px;
  background-color: currentColor; -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat;
  -webkit-mask-position: center; mask-position: center; -webkit-mask-size: contain; mask-size: contain; }
.fap-hdr-titles { display: flex; align-items: center; gap: var(--fap-space-3); }
.fap-hdr-titles .mod-chip { display: flex; align-items: center; color: var(--fap-primary); }
.fap-hdr-titles .titles { display: flex; flex-direction: column; line-height: 1.15; }
.fap-hdr-titles .crumbs { font-size: 11px; color: var(--fap-text-muted); }
.fap-hdr-titles .mod-title { font-size: 1.15rem; font-weight: var(--fap-weight-bold); letter-spacing: -.01em; }
.fap-hdr-user { display: flex; align-items: center; justify-content: flex-end; gap: var(--fap-space-3); }
.fap-hdr-user .hbtn { display: flex; align-items: center; justify-content: center; height: 40px; width: 40px;
  border-radius: var(--fap-radius-md); color: var(--fap-text-muted); position: relative; }
.fap-hdr-user .hbtn:hover { background: var(--fap-hover); color: var(--fap-text); }
.fap-hdr-user .bell.has { color: var(--fap-primary); }
.fap-hdr-user .chip-count { position: absolute; top: 2px; right: 2px; background: var(--fap-primary);
  color: var(--fap-on-primary); font-size: .6rem; font-weight: 700; border-radius: 999px; min-width: 15px;
  height: 15px; display: flex; align-items: center; justify-content: center; padding: 0 3px; }
.fap-hdr-user .hsep { width: 1px; height: 22px; background: var(--fap-border); }
.fap-hdr-user .user { display: flex; align-items: center; gap: var(--fap-space-2); }
.fap-hdr-user .uava { width: 34px; height: 34px; border-radius: 999px; background: var(--fap-primary);
  color: var(--fap-on-primary); display: flex; align-items: center; justify-content: center; font-weight: 700;
  font-size: .74rem; flex: 0 0 auto; }
.fap-hdr-user .uinfo { display: flex; flex-direction: column; line-height: 1.15; }
.fap-hdr-user .uinfo b { font-size: .82rem; font-weight: 600; }

/* narrow screens: force the compact rail so the layout never breaks (desktop-first) */
@media (max-width: 900px) { :root { --fap-rail-width: var(--fap-rail-collapsed) !important; } }
"""

def _dashboard() -> str:
    """The dashboard 'command center': a greeting hero, clickable action cards, a
    recent-analysis list and a compact activity feed. Every surface is token-driven
    (restrained radius, subtle borders, low shadow) so it reads as a premium
    analytical workspace rather than a generic SaaS dashboard."""
    return """
/* ---- greeting hero ---- */
.fap-hero { display: flex; flex-direction: column; gap: 2px; padding: 2px 2px 6px; }
.fap-hero .eyebrow { font-size: var(--fap-text-2xs); font-weight: var(--fap-weight-bold);
  letter-spacing: var(--fap-tracking-wider); text-transform: uppercase; color: var(--fap-text-subtle); }
.fap-hero .greet { font-size: 1.6rem; font-weight: var(--fap-weight-black);
  letter-spacing: var(--fap-tracking-tight); line-height: 1.1; color: var(--fap-text); }
.fap-hero .sub { font-size: var(--fap-text-sm); color: var(--fap-text-muted); margin-top: 2px; }
.fap-hero .ctx { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 8px;
  font-size: var(--fap-text-xs); color: var(--fap-text-subtle); }
.fap-hero .ctx b { color: var(--fap-text-muted); font-weight: var(--fap-weight-semibold); }
/* ---- section label (dashboard blocks) ---- */
.fap-dash-h { display: flex; align-items: center; gap: 8px; font-size: var(--fap-text-2xs);
  font-weight: var(--fap-weight-bold); letter-spacing: var(--fap-tracking-wider);
  text-transform: uppercase; color: var(--fap-text-subtle); margin: 6px 2px 8px; }
.fap-dash-h::after { content: ""; flex: 1; height: 1px; background: var(--fap-border); opacity: .8; }
/* ---- action cards (clickable module launchers) ---- */
.fap-action-card { position: relative; display: flex; flex-direction: column; gap: 8px;
  padding: 14px 16px; min-height: 118px; background: var(--fap-surface);
  border: 1px solid var(--fap-border); border-radius: var(--fap-radius-md);
  box-shadow: var(--fap-shadow-xs); transition: border-color var(--fap-transition-fast),
    box-shadow var(--fap-transition-fast), transform var(--fap-transition-fast); }
.fap-action-card .chip { display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: var(--fap-radius-sm); background: var(--fap-surface-alt);
  color: var(--fap-primary); border: 1px solid var(--fap-border); }
.fap-action-card .t { font-size: var(--fap-text-base, 0.9375rem); font-weight: var(--fap-weight-bold);
  color: var(--fap-text); line-height: 1.2; }
.fap-action-card .d { font-size: var(--fap-text-xs); color: var(--fap-text-muted); line-height: 1.4; }
.fap-action-card .go { position: absolute; top: 14px; right: 14px; color: var(--fap-text-subtle);
  opacity: 0; transform: translateX(-2px); transition: opacity var(--fap-transition-fast),
    transform var(--fap-transition-fast); }
/* the whole card is one clickable target. The click surface is a real st.button
   (native, keyboard-accessible) whose ELEMENT CONTAINER (st-key-dashbtn_*) is pulled
   OUT OF FLOW and stretched over the card — so no native button box reserves space
   below the card (the previous "white rectangle" defect) and none of its chrome
   shows. No href, no scripts, no fragile generated-class selectors. */
[class*="st-key-dash_action_"] { position: relative; }
[class*="st-key-dashbtn_"] { position: absolute !important; inset: 0 !important; margin: 0 !important;
  z-index: 4; width: auto !important; }
[class*="st-key-dashbtn_"] .stButton, [class*="st-key-dashbtn_"] [data-testid="stButton"] {
  width: 100%; height: 100%; margin: 0; }
[class*="st-key-dashbtn_"] button {
  width: 100% !important; height: 100% !important; min-height: 0 !important; padding: 0 !important;
  opacity: 0; border: none !important; background: transparent !important; box-shadow: none !important; }
[class*="st-key-dash_action_"]:hover .fap-action-card { border-color: color-mix(in srgb,
  var(--fap-primary) 45%, var(--fap-border)); box-shadow: var(--fap-shadow-md); transform: translateY(-1px); }
[class*="st-key-dash_action_"]:hover .fap-action-card .chip { color: var(--fap-primary);
  border-color: color-mix(in srgb, var(--fap-primary) 45%, var(--fap-border)); }
[class*="st-key-dash_action_"]:hover .fap-action-card .go { opacity: 1; transform: none; }
/* keyboard focus draws the ring on the card, not the invisible button */
[class*="st-key-dash_action_"]:focus-within .fap-action-card {
  border-color: var(--fap-primary); box-shadow: 0 0 0 2px color-mix(in srgb,
  var(--fap-primary) 35%, transparent); }
/* ---- recent-analysis list ---- */
.fap-recent { display: flex; flex-direction: column; }
.fap-recent-row { position: relative; display: flex; align-items: center; gap: 12px;
  padding: 9px 6px; border-bottom: 1px solid var(--fap-border); }
.fap-recent-row:last-child { border-bottom: none; }
.fap-recent-row .ic { display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: var(--fap-radius-sm); background: var(--fap-surface-alt);
  color: var(--fap-text-muted); flex: 0 0 auto; border: 1px solid var(--fap-border); }
.fap-recent-row .main { flex: 1; min-width: 0; }
.fap-recent-row .nm { font-size: var(--fap-text-sm); font-weight: var(--fap-weight-semibold);
  color: var(--fap-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fap-recent-row .mt { font-size: var(--fap-text-xs); color: var(--fap-text-subtle); }
.fap-recent-row .go { color: var(--fap-text-subtle); flex: 0 0 auto; }
[class*="st-key-dash_recent_"] { position: relative; }
[class*="st-key-dashrec_"] { position: absolute !important; inset: 0 !important; margin: 0 !important;
  z-index: 4; width: auto !important; }
[class*="st-key-dashrec_"] button { width: 100% !important; height: 100% !important; min-height: 0 !important;
  opacity: 0; border: none !important; background: transparent !important; box-shadow: none !important; }
[class*="st-key-dash_recent_"]:hover .fap-recent-row { background: var(--fap-hover);
  border-radius: var(--fap-radius-sm); }
[class*="st-key-dash_recent_"]:focus-within .fap-recent-row { background: var(--fap-hover);
  border-radius: var(--fap-radius-sm); box-shadow: inset 0 0 0 1px color-mix(in srgb,
  var(--fap-primary) 35%, transparent); }
[class*="st-key-dash_recent_"]:hover .fap-recent-row .go { color: var(--fap-primary); }
/* (activity-feed rows reuse the existing .fap-activity styles in _components) */
"""


def _overlays() -> str:
    """Theme the widgets Streamlit renders in a PORTAL at the <body> root — outside
    ``.stApp`` — which otherwise fall back to Streamlit's light base theme and leak
    white surfaces in dark mode (selectbox/multiselect dropdowns, popovers, calendars,
    tooltips). Uses only stable BaseWeb/testid selectors + FAP tokens (which live on
    :root, so they resolve at the document root too) — never generated class names."""
    return """
/* selectbox / multiselect dropdown menus (portal) */
[data-baseweb="popover"] [data-baseweb="menu"], ul[role="listbox"], [role="listbox"] {
  background: var(--fap-surface) !important; border: 1px solid var(--fap-border) !important;
  border-radius: var(--fap-radius-md) !important; box-shadow: var(--fap-shadow-lg) !important;
  color: var(--fap-text) !important; }
[role="option"] { background: transparent !important; color: var(--fap-text) !important; }
[role="option"]:hover, [role="option"][aria-selected="true"], li[role="option"]:hover {
  background: var(--fap-hover) !important; color: var(--fap-text) !important; }
/* the closed select control value text + chevron */
[data-baseweb="select"] { color: var(--fap-text) !important; }
[data-baseweb="select"] svg { fill: var(--fap-text-muted) !important; color: var(--fap-text-muted) !important; }
/* st.popover / dropdown panels (Theme, Account, …) */
[data-testid="stPopoverBody"], [data-baseweb="popover"] [data-testid="stVerticalBlock"] {
  background: var(--fap-surface) !important; }
[data-testid="stPopoverBody"] {
  border: 1px solid var(--fap-border) !important; border-radius: var(--fap-radius-lg) !important;
  box-shadow: var(--fap-shadow-lg) !important; }
/* date picker + tooltips */
[data-baseweb="calendar"], [data-baseweb="datepicker"] {
  background: var(--fap-surface) !important; color: var(--fap-text) !important; }
[data-baseweb="tooltip"], [role="tooltip"] {
  background: var(--fap-secondary) !important; color: #fff !important; border-radius: var(--fap-radius-sm) !important; }
"""


def build_css(brand: Branding | None = None, mode: str = "auto") -> str:
    """The complete application stylesheet for ``mode`` (light|dark|auto).

    For 'auto', both the OS preference (prefers-color-scheme) and an explicit
    ``data-theme`` on the root are honoured; light and dark variable blocks are
    both emitted so a runtime toggle needs no re-render.
    """
    brand = brand or DEFAULT_BRANDING
    body = "".join((_chrome(), _base(brand), _sidebar(), _components(), _forms(),
                    _tables(), _studio(), _dashboard(), _overlays(), _a11y_and_motion(),
                    _responsive(brand), _app_shell()))

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
    # @import MUST be the first rule in the sheet. Inter with a full weight range
    # for the type hierarchy (regular body -> black KPI numbers); system fallback
    # is baked into font_sans so a blocked font host degrades gracefully.
    font_import = ("@import url('https://fonts.googleapis.com/css2?"
                   "family=Inter:wght@400;500;600;700;800;900&display=swap');\n")
    return f"<style id=\"fap-theme\">\n{font_import}{roots}\n{body}\n</style>"


def apply(brand: Branding | None = None, mode: str = "auto") -> None:
    """Inject the stylesheet into the running app (the only Streamlit call)."""
    import streamlit as st
    st.markdown(build_css(brand, mode), unsafe_allow_html=True)
