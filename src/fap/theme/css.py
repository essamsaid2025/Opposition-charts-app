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
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: color-mix(in srgb, var(--fap-primary) 16%, transparent);
  color: var(--fap-primary);
  border-color: color-mix(in srgb, var(--fap-primary) 22%, transparent);
  box-shadow: inset 4px 0 0 var(--fap-primary),
    0 0 0 1px color-mix(in srgb, var(--fap-primary) 12%, transparent),
    0 2px 12px color-mix(in srgb, var(--fap-primary) 18%, transparent);
  font-weight: 650;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover { transform: none; }
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
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: var(--fap-primary); color: var(--fap-primary); box-shadow: var(--fap-shadow-sm); }
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
                    _tables(), _studio(), _a11y_and_motion(), _responsive(brand)))

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
