"""Set Piece Analysis - the professional set-piece workspace (Phase 9.0).

A thin view over ``SetPieceService``: no business logic here. Capability-gated
through the platform PermissionService. Only navigation/selection lives in
session_state - every set piece, position, contact and import is persisted by the
service in the platform Database. Analytics dashboards, professional
visualizations, penalty analysis and Studio reports arrive in Phases 9.1-9.5 and
extend this page without a second engine.
"""
from __future__ import annotations

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.capabilities import Capability
from fap.identity.roles import Role
from fap.setpieces.models import (
    DELIVERY_TYPES, OCCUPANCY_ROLE_LABELS, PERSPECTIVES, PHASES,
    SET_PIECE_TYPE_LABELS, SET_PIECE_TYPES, SIDES, SetPieceFilter,
)
from fap.ui.page import Page, page_registry

SEL = "_setpiece_id"                    # selected set piece (detail view)
OPEN_REPORT = "_open_report_id"         # the Report Studio navigation key (reused)

_PROFILE_BLURBS = {
    "coach": "Short, clean and visual (8–12 pages): key threats, routines, dangerous players, "
             "recommendations and training focus.",
    "analyst": "The full dossier (30–60 pages): every section, every category, all visualizations "
               "and the appendix.",
    "executive": "Management summary (2–4 pages): headline KPIs, key risks and priority actions only.",
    "opposition": "Complete tactical opposition report across all set-piece categories.",
    "setpiece": "Set pieces only — every category, routines, intelligence and visualizations.",
    "penalty": "Penalties only — shooter/goalkeeper intelligence, placement and recommendations.",
}


def _profile_blurb(profile_id: str) -> str:
    return _PROFILE_BLURBS.get(profile_id, "")


@page_registry.register
class SetPieceAnalysisPage(Page):
    info = PluginInfo(id="set_piece_analysis", name="Set Piece Analysis", category="page")
    section = "Analysis"
    icon = "setpiece"
    order = 20
    min_role = Role.READ_ONLY           # view gated by capability below

    def render(self, shell) -> None:
        svc = getattr(shell.platform, "setpieces", None) if shell.platform else None
        perms = getattr(shell.platform, "permissions", None) if shell.platform else None
        if svc is None or perms is None:
            st.info("Set Piece platform unavailable.")
            return
        if not perms.can(shell.user, str(Capability.VIEW_SETPIECE)):
            st.warning("You do not have permission to view set-piece analysis.")
            return
        self._can_edit = perms.can(shell.user, str(Capability.EDIT_SETPIECE))
        self._can_report = perms.can(shell.user, str(Capability.CREATE_REPORT))

        st.title("Set Piece Analysis")

        selected = st.session_state.get(SEL)
        if selected and svc.get_set_piece(selected):
            self._detail(shell, svc, selected)
            return

        tabs = st.tabs(["Match Prep", "Overview", "Offensive", "Defensive", "Visuals",
                        "Intelligence", "Penalties", "Tag Set Piece", "Import", "Browse"])
        with tabs[0]:
            self._match_prep(shell, svc)
        with tabs[1]:
            self._overview(shell, svc)
        with tabs[2]:
            self._phase_dashboard(shell, svc, "offensive")
        with tabs[3]:
            self._phase_dashboard(shell, svc, "defensive")
        with tabs[4]:
            self._visuals(shell, svc)
        with tabs[5]:
            self._intelligence(shell, svc)
        with tabs[6]:
            self._penalties(shell, svc)
        with tabs[7]:
            self._tag(shell, svc)
        with tabs[8]:
            self._import(shell, svc)
        with tabs[9]:
            self._browse(shell, svc)

    # ---------------------------------------------------------------- dashboards
    def _overview(self, shell, svc) -> None:
        if not svc.dashboard(shell.user)["total"]:
            st.info("No set pieces yet. Use **Tag Set Piece** to add one manually, "
                    "or **Import** a CSV/Excel/JSON file.")
            return
        filt = self._filter_bar(shell, svc, key="ov")
        bundle = svc.analytics_overview(shell.user, filt, workspace_id=shell.workspace_id)
        self._render_analytics(bundle)
        self._report_button(shell, svc, filt, key="ov")

    def _phase_dashboard(self, shell, svc, phase: str) -> None:
        if not svc.dashboard(shell.user)["total"]:
            st.info("No set pieces yet.")
            return
        st.caption(f"{phase.title()} set pieces — "
                   f"{'your team attacking' if phase == 'offensive' else 'defending against'} dead balls.")
        filt = self._filter_bar(shell, svc, key=phase)
        method = svc.offensive_dashboard if phase == "offensive" else svc.defensive_dashboard
        bundle = method(shell.user, filt, workspace_id=shell.workspace_id)
        self._render_analytics(bundle)
        self._map_summaries(shell, svc, filt, phase)
        self._report_button(shell, svc, filt, key=phase, phase=phase)

    def _filter_bar(self, shell, svc, *, key: str) -> SetPieceFilter:
        opts = svc.filter_options(shell.user)

        def pick(col_label, col, c):
            values = opts.get(col, [])
            choice = c.selectbox(col_label, ["All", *values], key=f"spf_{key}_{col}")
            return "" if choice == "All" else choice

        a, b, c, d = st.columns(4)
        team = pick("Team", "team", a)
        competition = pick("Competition", "competition", b)
        season = pick("Season", "season", c)
        match_id = pick("Match", "match_id", d)
        e, f, g, h = st.columns(4)
        taker = pick("Taker", "taker", e)
        delivery_type = pick("Delivery", "delivery_type", f)
        outcome = pick("Outcome", "outcome", g)
        sp_type = pick("Type", "type", h)
        i, j = st.columns(2)
        half_choice = i.selectbox("Half", ["All", "1", "2"], key=f"spf_{key}_half")
        player = j.text_input("Player (in box)", key=f"spf_{key}_player")
        return SetPieceFilter(
            team=team, competition=competition, season=season, match_id=match_id,
            taker=taker, delivery_type=delivery_type, outcome=outcome, type=sp_type,
            half=int(half_choice) if half_choice != "All" else None, player=player.strip())

    def _render_analytics(self, bundle: dict) -> None:
        if not bundle["count"]:
            st.info("No set pieces match the current filters.")
            return
        ov, dr = bundle["overview"], bundle["derived"]
        r1 = st.columns(5)
        r1[0].metric("Total", ov["total"])
        r1[1].metric("Goals", ov["goals"])
        r1[2].metric("Shots", ov["shots"])
        r1[3].metric("xG", ov["xg"])
        r1[4].metric("Shot %", f"{ov['shot_pct']}%")
        r2 = st.columns(5)
        r2[0].metric("Goal %", f"{ov['goal_pct']}%")
        r2[1].metric("First Contact %", f"{ov['first_contact_pct']}%")
        r2[2].metric("Second Ball %", f"{ov['second_ball_pct']}%")
        r2[3].metric("Retention %", f"{ov['retention_pct']}%")
        r2[4].metric("Success Rate", f"{dr['success_rate']}%")
        r3 = st.columns(5)
        r3[0].metric("Goal Contribution", f"{dr['goal_contribution']}%")
        r3[1].metric("Chance Creation", f"{dr['chance_creation']}%")
        r3[2].metric("Avg in Box", ov["avg_players_in_box"] if ov["avg_players_in_box"] is not None else "—")
        r3[3].metric("Avg TT Shot", f"{ov['avg_time_to_shot']}s" if ov["avg_time_to_shot"] is not None else "—")
        r3[4].metric("Avg TT 1st", f"{ov['avg_time_to_first_contact']}s" if ov["avg_time_to_first_contact"] is not None else "—")

        bt = bundle["by_type"]
        if bt:
            st.subheader("By type")
            st.dataframe(
                [{"Type": SET_PIECE_TYPE_LABELS.get(t, t), "Count": s["count"],
                  "Shots": s["shots"], "Goals": s["goals"], "Shot %": s["shot_pct"],
                  "Goal %": s["goal_pct"], "1st Contact %": s["first_contact_pct"], "xG": s["xg"]}
                 for t, s in sorted(bt.items(), key=lambda kv: -kv[1]["count"])],
                use_container_width=True, hide_index=True)
        col1, col2 = st.columns(2)
        with col1:
            st.caption("Delivery type")
            dt = bundle["delivery"]["delivery_type"]
            st.dataframe([{"Delivery": k.title(), "Count": v} for k, v in dt.items()] or
                         [{"Delivery": "—", "Count": 0}], use_container_width=True, hide_index=True)
        with col2:
            st.caption("Outcomes")
            st.dataframe([{"Outcome": k.title(), "Count": v} for k, v in bundle["outcome"].items()]
                         or [{"Outcome": "—", "Count": 0}], use_container_width=True, hide_index=True)

    # ---------------------------------------------------------------- match prep (9.5)
    def _match_prep(self, shell, svc) -> None:
        st.subheader("Match Preparation & Reporting Center")
        st.caption("One click builds a complete, professional report from every module — "
                   "analytics, visualizations, intelligence and penalties — fully editable in "
                   "the existing Report Studio.")
        if not svc.dashboard(shell.user)["total"]:
            st.info("Add or import set pieces first, then generate a match-preparation report.")
            return
        if not self._can_report or getattr(shell.platform, "reports", None) is None:
            st.warning("You need report-creation permission to generate reports.")
            return
        profiles = svc.report_profiles(shell.user)
        a, b = st.columns([2, 1])
        prof = a.selectbox("Report profile", profiles,
                           format_func=lambda p: f"{p['label']}  ·  {p['pages']} pages",
                           key="mp_profile")
        themes = svc.theme_ids(shell.user) or ["opta_light", "opta_dark"]
        theme = b.selectbox("Theme", themes, key="mp_theme")
        with st.expander("Scope (optional filters)"):
            filt = self._filter_bar(shell, svc, key="mp")
        st.markdown(_profile_blurb(prof["id"]))
        if st.button("⚡ Generate Match Preparation Report", type="primary", key="mp_generate"):
            with st.spinner("Building report from analytics, visualizations and intelligence…"):
                try:
                    rec = svc.generate_match_report(shell.user, profile=prof["id"], filt=filt,
                                                    theme_id=theme, workspace_id=shell.workspace_id)
                    st.success(f"**{rec.title}** generated. Open it in **Report Studio** to review, "
                               "edit and export (PDF / HTML / Markdown / DOCX).")
                    st.session_state[OPEN_REPORT] = rec.id
                except Exception as exc:
                    st.error(f"Could not generate report: {exc}")

    # ---------------------------------------------------------------- penalties (9.4)
    def _penalties(self, shell, svc) -> None:
        st.caption("Complete penalty scouting: shooter & goalkeeper intelligence, team patterns "
                   "and shootout analysis. Penalty visualizations live in the Visuals tab.")
        filt = self._filter_bar(shell, svc, key="pen")
        shooters = svc.penalty_shooters(shell.user, filt, workspace_id=shell.workspace_id)
        keepers = svc.penalty_goalkeepers(shell.user, filt, workspace_id=shell.workspace_id)
        if not shooters and not keepers:
            st.info("No penalties tagged yet. Add penalties (Tag Set Piece → type Penalty) or "
                    "import them, then fill placement/goalkeeper detail.")
            return
        inner = st.tabs(["Shooter", "Goalkeeper", "Team", "Shootouts", "Intelligence"])
        with inner[0]:
            self._penalty_shooter(shell, svc, filt, shooters)
        with inner[1]:
            self._penalty_gk(shell, svc, filt, keepers)
        with inner[2]:
            self._penalty_team(shell, svc, filt)
        with inner[3]:
            self._penalty_shootouts(shell, svc, filt)
        with inner[4]:
            self._penalty_intel(shell, svc, filt)

    def _penalty_shooter(self, shell, svc, filt, shooters) -> None:
        if not shooters:
            st.info("No shooters tagged."); return
        who = st.selectbox("Shooter", shooters, key="pen_shooter_sel")
        p = svc.penalty_shooter(shell.user, who, filt, workspace_id=shell.workspace_id)
        if not p.get("n"):
            st.info("No penalties for this shooter."); return
        c = st.columns(5)
        c[0].metric("Penalties", p["n"]); c[1].metric("Conversion", f"{p['conversion_pct']}%")
        c[2].metric("xG vs Goals", p["xg_vs_goals"]); c[3].metric("Pref. corner", p["preferred_corner"] or "—")
        c[4].metric("Pref. height", p["preferred_height"] or "—")
        d = st.columns(4)
        d[0].metric("Power/placement", p["power_vs_placement"])
        d[1].metric("Body", p["body_orientation"] or "—")
        d[2].metric("Technique", p["technique"] or "—")
        d[3].metric("Under pressure", f"{p['pressure']['conversion_pct']}%")
        if p["pressure"]["changes_direction"]:
            st.warning(f"Changes direction under pressure: {p['pressure']['preferred_side_pressure']} "
                       f"(pressure) vs {p['pressure']['preferred_side_calm']} (calm).")

    def _penalty_gk(self, shell, svc, filt, keepers) -> None:
        if not keepers:
            st.info("No goalkeepers tagged."); return
        who = st.selectbox("Goalkeeper", keepers, key="pen_gk_sel")
        p = svc.penalty_goalkeeper(shell.user, who, filt, workspace_id=shell.workspace_id)
        if not p.get("n"):
            st.info("No penalties for this goalkeeper."); return
        c = st.columns(5)
        c[0].metric("Faced", p["n"]); c[1].metric("Save %", f"{p['save_pct']}%")
        c[2].metric("Dive pref", p["dive_preference"] or "—")
        c[3].metric("Stays central", f"{p['central_stay_freq']}%")
        c[4].metric("Correct guess", f"{p['correct_guess_pct']}%")
        d = st.columns(3)
        d[0].metric("Early dive", f"{p['early_dive_freq']}%")
        d[1].metric("Late dive", f"{p['late_dive_freq']}%")
        d[2].metric("Distribution", p["distribution_after"] or "—")

    def _penalty_team(self, shell, svc, filt) -> None:
        t = svc.penalty_team(shell.user, filt, workspace_id=shell.workspace_id)
        if not t.get("n"):
            st.info("No penalties."); return
        st.metric("Team conversion", f"{t['conversion_pct']}%")
        st.caption("Preferred takers")
        st.dataframe([{"Player": n, "Penalties": s["attempts"], "Goals": s["goals"],
                       "Conversion": f"{s['conversion_pct']}%"} for n, s in t["preferred_takers"]],
                     use_container_width=True, hide_index=True)
        cc = st.columns(2)
        with cc[0]:
            st.caption("By venue")
            st.dataframe([{"Venue": k, "Conv %": v["conversion_pct"]}
                          for k, v in t["home_vs_away"].items()] or [{"Venue": "—", "Conv %": 0}],
                         use_container_width=True, hide_index=True)
        with cc[1]:
            st.caption("League vs cup")
            st.dataframe([{"Context": k, "Conv %": v["conversion_pct"]}
                          for k, v in t["league_vs_cup"].items()] or [{"Context": "—", "Conv %": 0}],
                         use_container_width=True, hide_index=True)

    def _penalty_shootouts(self, shell, svc, filt) -> None:
        shootouts = svc.penalty_shootouts(shell.user, filt, workspace_id=shell.workspace_id)
        if not shootouts:
            st.info("No shootouts recorded."); return
        for s in shootouts:
            with st.container(border=True):
                st.markdown(f"**{' vs '.join(s['teams'])}** — score "
                            f"{'-'.join(str(v) for v in s['score'].values())}"
                            f"  ·  winner: {s['winner'] or '—'}"
                            f"{'  ·  sudden death' if s['sudden_death'] else ''}")
                st.dataframe([{"#": a["order"], "Team": a["team"], "Shooter": a["shooter"],
                               "Outcome": a["outcome"], "Pressure": a["pressure_index"]}
                              for a in s["sequence"]], use_container_width=True, hide_index=True)

    def _penalty_intel(self, shell, svc, filt) -> None:
        intel = svc.penalty_intelligence(shell.user, filt, workspace_id=shell.workspace_id)
        for group, title in (("shooter_insights", "Shooter"), ("goalkeeper_insights", "Goalkeeper"),
                             ("team_insights", "Team")):
            items = getattr(intel, group)
            if items:
                st.caption(title)
                for i in items:
                    self._insight(i)
        if intel.recommendations:
            st.subheader("Recommendations")
            for r in intel.recommendations:
                self._recommendation(r)
        if self._can_report and getattr(shell.platform, "reports", None) is not None:
            if st.button("📄 Create penalty report (Studio)", key="pen_report"):
                try:
                    rec = svc.create_penalty_report(shell.user, filt=filt,
                                                    workspace_id=shell.workspace_id)
                    st.success(f"Report created: {rec.title}. Open Report Studio to edit.")
                except Exception as exc:
                    st.error(f"Could not create report: {exc}")

    # ---------------------------------------------------------------- intelligence (9.3)
    def _intelligence(self, shell, svc) -> None:
        if not svc.dashboard(shell.user)["total"]:
            st.info("Add or import set pieces first — intelligence needs tagged data.")
            return
        st.caption("Deterministic, rule-based intelligence — routines, tendencies, insights and "
                   "coach recommendations derived from the analytics (no AI service).")
        filt = self._filter_bar(shell, svc, key="intel")
        intel = svc.intelligence(shell.user, filt, workspace_id=shell.workspace_id)
        if not intel.n_set_pieces:
            st.info("No set pieces match the current filters.")
            return

        if intel.narrative:
            st.subheader("Scouting narrative")
            for line in intel.narrative:
                st.markdown(f"> {line}")

        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Detected routines")
            from fap.setpieces.intelligence import ROUTINE_LABELS
            st.dataframe([{"Routine": ROUTINE_LABELS.get(r, r), "Count": n}
                          for r, n in sorted(intel.routines.items(), key=lambda kv: -kv[1])],
                         use_container_width=True, hide_index=True)
        with c2:
            st.subheader("Routine clusters")
            st.dataframe([{"Cluster": c.label, "Size": c.size, "Conv %": c.conversion_pct,
                           "xG": c.xg, "Conf": f"{int(c.confidence * 100)}%"}
                          for c in intel.clusters] or [{"Cluster": "—", "Size": 0}],
                         use_container_width=True, hide_index=True)

        st.subheader("Tendencies")
        ta, tb = st.columns(2)
        with ta:
            st.caption("Offensive")
            for i in intel.offensive_tendencies:
                self._insight(i)
        with tb:
            st.caption("Defensive")
            for i in intel.defensive_tendencies:
                self._insight(i)

        if intel.insights:
            st.subheader("Automatic insights")
            for i in intel.insights:
                self._insight(i)

        if intel.recommendations:
            st.subheader("Coach recommendations")
            for r in intel.recommendations:
                self._recommendation(r)

        st.divider()
        if self._can_report and getattr(shell.platform, "reports", None) is not None:
            if st.button("📄 Create intelligence report (Studio)", key="intel_report"):
                try:
                    rec = svc.create_intelligence_report(shell.user, filt=filt,
                                                         workspace_id=shell.workspace_id)
                    st.success(f"Report created: {rec.title}. Open Report Studio to edit.")
                except Exception as exc:
                    st.error(f"Could not create report: {exc}")

    @staticmethod
    def _insight(i) -> None:
        icon = {"success": "🟢", "warning": "🟡", "danger": "🔴"}.get(i.kind, "🔵")
        st.markdown(f"{icon} **{i.title}** — {i.text}  \n"
                    f"<span style='color:gray;font-size:0.85em'>confidence "
                    f"{int(i.confidence * 100)}% · evidence: {'; '.join(i.evidence) or '—'}</span>",
                    unsafe_allow_html=True)

    @staticmethod
    def _recommendation(r) -> None:
        badge = {"high": "🔴 HIGH", "medium": "🟡 MED", "low": "⚪ LOW"}.get(r.priority, r.priority)
        with st.container(border=True):
            st.markdown(f"**{r.action}**  ·  {badge}  ·  confidence {int(r.confidence * 100)}%")
            st.markdown(f"*Why:* {r.rationale}")
            meta = []
            if r.evidence:
                meta.append("evidence: " + "; ".join(r.evidence))
            if r.visualization_references:
                meta.append("see: " + ", ".join(r.visualization_references))
            if meta:
                st.caption("  ·  ".join(meta))

    # ---------------------------------------------------------------- visuals (9.2)
    def _visuals(self, shell, svc) -> None:
        if not svc.dashboard(shell.user)["total"]:
            st.info("Add or import set pieces first, then generate visualizations here.")
            return
        st.caption("Professional set-piece visualizations — rendered through the platform "
                   "visualization engine (theme-aware, high-resolution, Studio-embeddable).")
        try:
            catalog = svc.visual_catalog(shell.user)
        except Exception as exc:
            st.error(f"Visualization library unavailable: {exc}")
            return
        cats = sorted({v["category"] for v in catalog})
        a, b, c = st.columns([2, 2, 1])
        category = a.selectbox("Category", cats, key="spv_cat")
        in_cat = [v for v in catalog if v["category"] == category]
        viz = b.selectbox("Visualization", in_cat, format_func=lambda v: v["name"], key="spv_viz")
        themes = svc.theme_ids(shell.user) or ["opta_light", "opta_dark"]
        theme = c.selectbox("Theme", themes, key="spv_theme")
        filt = self._filter_bar(shell, svc, key="viz")

        if st.button("Render preview", type="primary", key="spv_render"):
            try:
                png = svc.render_visual(shell.user, viz["id"], filt, theme_id=theme, dpi=200,
                                        fmt="png", workspace_id=shell.workspace_id)
                st.image(png, use_container_width=True)
                d1, d2 = st.columns(2)
                d1.download_button("⬇ PNG (hi-res)", data=png, file_name=f"{viz['id']}.png",
                                   mime="image/png", key="spv_dlpng")
                d2.download_button(
                    "⬇ PDF", key="spv_dlpdf", file_name=f"{viz['id']}.pdf", mime="application/pdf",
                    data=svc.render_visual(shell.user, viz["id"], filt, theme_id=theme, dpi=300,
                                           fmt="pdf", workspace_id=shell.workspace_id))
            except Exception as exc:
                st.error(f"Render failed: {exc}")

        st.divider()
        self._add_to_report(shell, svc, viz, filt, theme)

    def _add_to_report(self, shell, svc, viz, filt, theme) -> None:
        if not (self._can_edit and self._can_report):
            return
        reports = getattr(shell.platform, "reports", None)
        if reports is None:
            return
        recs = reports.list(shell.user, workspace_id=shell.workspace_id)
        options = ["➕ New report"] + [r.title for r in recs]
        choice = st.selectbox("Embed into report", options, key="spv_report")
        if st.button("Add visualization to Report Studio", key="spv_embed"):
            try:
                if choice == "➕ New report":
                    rid = svc.create_report(shell.user, filt=filt, title="Set Piece Report",
                                            workspace_id=shell.workspace_id).id
                else:
                    rid = recs[options.index(choice) - 1].id
                svc.embed_visual(shell.user, rid, viz["id"], filt, theme_id=theme,
                                 title=viz["name"], workspace_id=shell.workspace_id)
                st.success(f"Added “{viz['name']}” to the report. Open Report Studio to edit.")
            except Exception as exc:
                st.error(f"Could not embed: {exc}")

    def _map_summaries(self, shell, svc, filt, phase: str) -> None:
        """Phase 9.1 exposes the map DATA pipeline; the pitch renderers land in
        9.2. Show the dataset sizes so the data is visible and verifiable."""
        with st.expander("Map datasets (rendered as pitch maps in Phase 9.2)"):
            kinds = [("Delivery landing", "delivery"), ("Shots", "shot"),
                     ("First contact", "first_contact"), ("Second ball", "second_ball"),
                     ("Delivery accuracy", "delivery_accuracy")]
            cols = st.columns(len(kinds))
            for col, (label, kind) in zip(cols, kinds):
                data = svc.map_data(shell.user, kind, filt, workspace_id=shell.workspace_id)
                col.metric(label, len(data))
            st.caption("These coordinate datasets feed the 9.2 delivery/shot/first-contact/"
                       "second-ball/accuracy maps directly.")

    def _report_button(self, shell, svc, filt, *, key: str, phase: str = "") -> None:
        if not self._can_report:
            return
        if st.button("📄 Create Studio report", key=f"sp_report_{key}"):
            try:
                use = filt if not phase else self._with_phase(filt, phase)
                rec = svc.create_report(shell.user, filt=use, workspace_id=shell.workspace_id,
                                        title=f"Set Piece Report{' — ' + phase.title() if phase else ''}")
                st.success(f"Report created: {rec.title}. Open it in Report Studio to edit.")
            except Exception as exc:
                st.error(f"Could not create report: {exc}")

    @staticmethod
    def _with_phase(filt: SetPieceFilter, phase: str) -> SetPieceFilter:
        from dataclasses import replace
        return replace(filt, phase=phase)

    # ---------------------------------------------------------------- tagging
    def _tag(self, shell, svc) -> None:
        if not self._can_edit:
            st.warning("You need edit permission to tag set pieces.")
            return
        st.caption("Manual tagging engine — records a set piece to the persistent store.")
        with st.form("sp_tag", clear_on_submit=True):
            a, b, c = st.columns(3)
            sp_type = a.selectbox("Type", SET_PIECE_TYPES,
                                  format_func=lambda t: SET_PIECE_TYPE_LABELS[t])
            phase = b.selectbox("Phase", PHASES, format_func=str.title)
            perspective = c.selectbox("Perspective", PERSPECTIVES,
                                      format_func=lambda p: "Own team" if p == "own" else "Opposition")
            d, e, f = st.columns(3)
            team = d.text_input("Team")
            opponent = e.text_input("Opponent")
            match_label = f.text_input("Match")
            g, h, i = st.columns(3)
            taker = g.text_input("Taker")
            side = h.selectbox("Side", SIDES, format_func=lambda s: s.title() or "—")
            delivery = i.selectbox("Delivery", DELIVERY_TYPES,
                                   format_func=lambda s: s.title() or "—")
            j, k, m = st.columns(3)
            end_x = j.number_input("Landing X (0–100)", 0.0, 100.0, 92.0, 0.5)
            end_y = k.number_input("Landing Y (0–100)", 0.0, 100.0, 50.0, 0.5)
            in_box = m.number_input("Players in box", 0, 20, 0, 1)
            n, o = st.columns(2)
            shot = n.checkbox("Shot")
            goal = o.checkbox("Goal")
            if st.form_submit_button("Add set piece", type="primary"):
                sp = svc.create_set_piece(
                    shell.user, type=sp_type, phase=phase, perspective=perspective,
                    team=team, opponent=opponent, match_label=match_label, taker=taker,
                    side=side, delivery_type=delivery, end_x=end_x, end_y=end_y,
                    players_in_box=int(in_box), shot=shot or goal, goal=goal,
                    workspace_id=shell.workspace_id)
                st.success(f"Added {SET_PIECE_TYPE_LABELS[sp_type]}. Open it in **Browse** "
                           "to tag box occupancy and contacts.")
                st.session_state[SEL] = sp.id
                st.rerun()

    # ---------------------------------------------------------------- import
    def _import(self, shell, svc) -> None:
        if not self._can_edit:
            st.warning("You need edit permission to import set pieces.")
            return
        st.caption("Provider-agnostic import — CSV, Excel or JSON. Columns are auto-detected "
                   "and normalized into the internal set-piece model.")
        a, b = st.columns(2)
        perspective = a.selectbox("Default perspective", PERSPECTIVES,
                                  format_func=lambda p: "Own team" if p == "own" else "Opposition",
                                  key="sp_imp_persp")
        phase = b.selectbox("Default phase", PHASES, format_func=str.title, key="sp_imp_phase")
        up = st.file_uploader("Set-piece file", type=["csv", "xlsx", "xls", "json"])
        if not up:
            return
        data = up.getvalue()
        try:
            preview = svc.preview_mapping(shell.user, data, up.name)
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
            return
        st.write(f"**{preview['rows']}** rows · detected **{len(preview['mapping'])}** fields")
        if preview["mapping"]:
            st.json(preview["mapping"], expanded=False)
        else:
            st.warning("No known columns detected — rows will use the defaults above. "
                       "Expected columns include type, phase, team, taker, end_x, end_y, outcome…")
        if st.button("Import file", type="primary"):
            result = svc.import_file(shell.user, data, up.name, perspective=perspective,
                                     phase=phase, workspace_id=shell.workspace_id)
            st.success(f"Imported {result.imported} of {result.batch.rows} set pieces "
                       f"({result.batch.skipped} skipped).")
            if result.errors:
                with st.expander(f"{len(result.errors)} row issue(s)"):
                    for err in result.errors[:50]:
                        st.text(err)

    # ---------------------------------------------------------------- browse
    def _browse(self, shell, svc) -> None:
        a, b, c = st.columns(3)
        f_type = a.selectbox("Type", ("", *SET_PIECE_TYPES),
                             format_func=lambda t: SET_PIECE_TYPE_LABELS.get(t, "All"))
        f_phase = b.selectbox("Phase", ("", *PHASES), format_func=lambda p: p.title() or "All")
        f_persp = c.selectbox("Perspective", ("", *PERSPECTIVES),
                             format_func=lambda p: {"": "All", "own": "Own", "opposition": "Opposition"}[p])
        filters = {k: v for k, v in
                   (("type", f_type), ("phase", f_phase), ("perspective", f_persp)) if v}
        items = svc.search(shell.user, filters=filters or None, workspace_id=shell.workspace_id)
        if not items:
            st.info("No set pieces match. Add or import some first.")
            return
        for sp in items[:200]:
            label = (f"{SET_PIECE_TYPE_LABELS.get(sp.type, sp.type)} · {sp.phase} · "
                     f"{sp.team or '—'} vs {sp.opponent or '—'}"
                     f"{' · ⚽' if sp.goal else (' · shot' if sp.shot else '')}")
            if st.button(label, key=f"sp_open_{sp.id}"):
                st.session_state[SEL] = sp.id
                st.rerun()

    # ---------------------------------------------------------------- detail
    def _detail(self, shell, svc, sp_id: str) -> None:
        sp = svc.get_set_piece(sp_id)
        if st.button("← Back"):
            st.session_state.pop(SEL, None)
            st.rerun()
        st.subheader(f"{SET_PIECE_TYPE_LABELS.get(sp.type, sp.type)} — "
                     f"{sp.team or '—'} vs {sp.opponent or '—'}")
        st.caption(f"{sp.phase} · {sp.perspective} · taker: {sp.taker or '—'} · "
                   f"delivery: {sp.delivery_type or '—'} · source: {sp.source}")

        positions = svc.list_positions(sp_id)
        contacts = svc.list_contacts(sp_id)
        c1, c2 = st.columns(2)
        c1.metric("Tagged positions", len(positions))
        c2.metric("Contacts", len(contacts))

        if not self._can_edit:
            return
        with st.expander("Add box position (occupancy)"):
            with st.form(f"pos_{sp_id}", clear_on_submit=True):
                a, b, c = st.columns(3)
                team = a.selectbox("Team", ("attack", "defence"), key=f"pt_{sp_id}")
                role = b.selectbox("Role", ("", *OCCUPANCY_ROLE_LABELS),
                                   format_func=lambda r: OCCUPANCY_ROLE_LABELS.get(r, "Auto (from X/Y)"),
                                   key=f"pr_{sp_id}")
                player = c.text_input("Player", key=f"pp_{sp_id}")
                d, e, f = st.columns(3)
                x = d.number_input("X", 0.0, 100.0, 92.0, 0.5, key=f"px_{sp_id}")
                y = e.number_input("Y", 0.0, 100.0, 50.0, 0.5, key=f"py_{sp_id}")
                is_gk = f.checkbox("Goalkeeper", key=f"pg_{sp_id}")
                if st.form_submit_button("Add position"):
                    svc.add_position(shell.user, sp_id, team=team, role=role, player=player,
                                     x=x, y=y, is_gk=is_gk)
                    st.rerun()
        if positions:
            st.dataframe(
                [{"team": p.team, "role": OCCUPANCY_ROLE_LABELS.get(p.role, p.role),
                  "player": p.player, "zone": p.zone, "x": p.x, "y": p.y} for p in positions],
                use_container_width=True, hide_index=True)
