"""Team Comparison Visualization Workspace (Open Play, team-match-stats datasets).

The team-stats counterpart of ``scouting_viz_workspace``: a professional workspace
that turns a team-comparison stat table into dedicated Open Play charts. It reuses
the pure renderers in ``fap.openplay.team_compare`` (matplotlib, theme-driven), the
existing ThemeManager for themes, and the existing ExportEngine for PNG/PDF. It
NEVER touches event data — no x/y/event_type — and runs no event engine.

The component is a thin view: all rendering lives in ``team_compare``. It stores
only selections + PNG bytes in session state (never matplotlib figures), and closes
every figure after export.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from fap.openplay import team_compare as tc
from fap.theme import components as C
from fap.utils.text import slugify


def _themes(shell):
    """Resolve the figure ThemeManager the same way the scouting/event viz
    workspaces do: the service registry is the source of truth; fall back to the
    platform attribute for direct-construction contexts (tests)."""
    plat = getattr(shell, "platform", None)
    tm = None
    if plat is not None:
        services = getattr(plat, "services", None)
        if services is not None:
            try:
                tm = services.get("themes")
            except Exception:
                tm = None
        if tm is None:
            tm = getattr(plat, "themes", None)
    if tm is None:
        return None, []
    try:
        return tm, tm.ids()
    except Exception:
        return None, []


def _export_engine():
    from fap.visuals.export import ExportEngine
    return ExportEngine()


def _stash_render(fig, title: str, ex, *, stash_key: str) -> None:
    import matplotlib.pyplot as plt
    try:
        png = ex.export(fig, title, fmt="png").data
        try:
            pdf = ex.export(fig, title, fmt="pdf").data
        except Exception:
            pdf = None
    finally:
        plt.close(fig)
    st.session_state[stash_key] = {"png": png, "pdf": pdf, "title": title}


def _show_stash(stash_key: str, *, key: str) -> None:
    data = st.session_state.get(stash_key)
    if not data:
        return
    png, pdf, title = data["png"], data.get("pdf"), data["title"]
    st.image(png, use_container_width=True)
    slug = slugify(title) or "team-comparison"
    cols = st.columns(2)
    cols[0].download_button("Download PNG", png, file_name=f"{slug}.png",
                            mime="image/png", key=f"{key}_png", use_container_width=True)
    if pdf is not None:
        cols[1].download_button("Download PDF", pdf, file_name=f"{slug}.pdf",
                                mime="application/pdf", key=f"{key}_pdf",
                                use_container_width=True)


def render_team_compare_workspace(shell, dataset, *, key: str = "team_cmp") -> None:
    """The full team-comparison workspace over a team-match-stats dataset.

    Reads the dataset's persisted semantic schema from ``dataset.document`` (never
    re-inferring, never the event pipeline) and draws Open Play comparison charts."""
    doc = dataset.document if isinstance(getattr(dataset, "document", None), dict) else {}
    schema = doc.get("team_stats_schema") or {}
    if not schema.get("teams"):
        C.render_alert("This dataset has no team columns to compare.", "warning")
        return

    all_teams = [str(t) for t in schema.get("teams", [])]
    C.render_section_title(
        dataset.name, eyebrow="Team Comparison",
        subtitle=" vs ".join(all_teams[:4]) or "team match stats", icon_name="analysis")
    summary = doc.get("team_stats_summary") or {}
    st.caption(
        f"{len(all_teams)} teams  ·  {summary.get('stat_count', len(schema.get('stats', [])))} "
        f"statistics  ·  {summary.get('category_count', 0)} categories  ·  "
        "team-level match stats (not event data)")

    _render_comparison(
        shell, all_teams=all_teams, dataset_name=dataset.name, key=key,
        make_cmp=lambda teams: tc.TeamComparison.from_document(
            doc, dataset_name=dataset.name, teams=teams),
        note_dataset="team_match_stats")


def render_event_match_stats(shell, frame, *, name: str, key: str = "ev_match") -> None:
    """Aggregate a two-team EVENT frame into a match-stats comparison and render the
    same team_compare charts — so a StatsBomb-style match gets a Team Stats sheet
    (possession, shots, passes, tackles, …) PLUS the computed PPDA and Field Tilt."""
    from fap.openplay.match_stats import build_match_stats
    schema = build_match_stats(frame)
    if schema is None or not schema.stats:
        C.render_alert("A match-stats comparison needs a single match with exactly two "
                       "teams in the active event dataset.", "info")
        return
    C.render_section_title(
        name or "Match Stats", eyebrow="Match Stats Comparison", icon_name="analysis",
        subtitle=" vs ".join(schema.teams))
    st.caption(f"{len(schema.stats)} statistics computed from the match events  ·  "
               "PPDA & Field Tilt derived (standard definitions)")
    _render_comparison(
        shell, all_teams=list(schema.teams), dataset_name=name or "Match Stats", key=key,
        make_cmp=lambda teams: tc.TeamComparison.from_schema(
            schema, dataset_name=name or "Match Stats", teams=teams),
        note_dataset="events")


def _render_comparison(shell, *, all_teams, dataset_name, key, make_cmp,
                       note_dataset) -> None:
    """Shared team-comparison UI (theme/teams/chart/statistics + display panel + note),
    used by both a saved team-stats dataset and an on-the-fly event aggregation."""
    tm, theme_ids = _themes(shell)
    if tm is None or not theme_ids:
        C.render_alert("Chart themes are unavailable in this session.", "warning")
        return

    # ---- controls: theme + teams + chart + statistics ----
    default_theme = "opta_dark" if "opta_dark" in theme_ids else theme_ids[0]
    c1, c2 = st.columns([1, 2])
    theme_id = c1.selectbox(
        "Theme", theme_ids,
        index=theme_ids.index(st.session_state.get(f"{key}_theme", default_theme))
        if st.session_state.get(f"{key}_theme", default_theme) in theme_ids else 0,
        key=f"{key}_theme")
    teams = c2.multiselect("Teams", all_teams,
                           default=st.session_state.get(f"{key}_teams", all_teams[:2]),
                           key=f"{key}_teams") or all_teams[:2]
    theme = tm.get(theme_id)

    cmp = make_cmp(teams)
    if not cmp.stats:
        C.render_alert("No statistics to visualize.", "warning")
        return

    chart_meta = {c["id"]: c for c in tc.CHART_TYPES}
    chart_ids = [c["id"] for c in tc.CHART_TYPES]
    ch1, ch2 = st.columns([1, 2])
    chart_id = ch1.selectbox("Chart", chart_ids,
                             format_func=lambda i: chart_meta[i]["label"],
                             key=f"{key}_chart")
    labels = cmp.stat_labels()
    meta = chart_meta[chart_id]
    options: dict[str, Any] = {}
    if chart_id == "donut":
        # single-statistic chart: default to a percentage row when present
        pct = next((s for s in cmp.stats if s.unit == tc.PERCENT), None)
        default_label = None
        if pct is not None:
            for lbl in labels:
                if cmp.resolve(lbl) is pct:
                    default_label = lbl
                    break
        stat_label = ch2.selectbox("Statistic", labels,
                                   index=labels.index(default_label) if default_label in labels else 0,
                                   key=f"{key}_stat")
        options["stat"] = stat_label
    else:
        default_stats = st.session_state.get(f"{key}_stats") or labels[:8]
        picked = ch2.multiselect("Statistics", labels,
                                 default=[s for s in default_stats if s in labels],
                                 key=f"{key}_stats")
        options["stats"] = picked or labels[:8]

    if chart_id == "diverging" and len(teams) != 2:
        C.render_alert("Head to head needs exactly two teams selected.", "info")

    # capability-gated Display panel (shared model) — presentation only.
    from fap.ui.components.display_panel import render_display_controls
    options["display"] = render_display_controls(
        tc.capabilities_for(chart_id), {}, key=f"{key}_disp_{chart_id}",
        defaults=tc.display_defaults_for(chart_id))

    stash_key = f"{key}_stash"
    if st.button("Render chart", type="primary", key=f"{key}_render",
                 use_container_width=True):
        try:
            ex = _export_engine()
            fig = tc.render(chart_id, cmp, theme, options)
            title = f"{dataset_name} · {meta['label']}"
            _stash_render(fig, title, ex, stash_key=stash_key)
        except Exception as exc:
            C.render_alert(f"Could not render the chart: {exc}", "warning")

    _show_stash(stash_key, key=key)
    _team_compare_note(cmp, chart_id, options, key=f"{key}_method", note_dataset=note_dataset)


def _team_compare_note(cmp, chart_id: str, options: dict, *, key: str,
                       note_dataset: str = "team_match_stats") -> None:
    """Data & Methodology note for a team-comparison chart: the statistics actually
    plotted, the calculation (raw values vs share/percentage), the teams and scope —
    from the live comparison. No coordinates (team stats are not spatial)."""
    from fap.ui.components.display_panel import render_methodology_note
    from fap.visuals.methodology import build_note
    meta = {c["id"]: c for c in tc.CHART_TYPES}.get(chart_id, {"label": chart_id})
    if chart_id == "donut":
        fields = [options.get("stat")] if options.get("stat") else []
    else:
        fields = list(options.get("stats") or [])
    share = chart_id in ("share", "donut", "radar")
    metric = f"{meta['label']} · " + ("team share of the row total" if share else "raw statistic values")
    src = ("aggregated from match events (PPDA/Field Tilt derived, standard definitions)"
           if note_dataset == "events" else "team match stats")
    note = build_note(
        dataset=f"{note_dataset} · {src}", fields=[str(f) for f in fields if f], filters=None,
        metric=metric, pitch_based=False, scope="Team comparison · " + " vs ".join(cmp.teams),
        population=f"{len(cmp.teams)} teams · {len(cmp.stats)} statistics")
    render_methodology_note(note, key=key)


__all__ = ["render_team_compare_workspace", "render_event_match_stats"]
