"""Teams page (T1) — create and manage club/academy squads (U19, U17, First Team…).

A Team groups players and (in later phases) owns team matches, media, charts and notes. This
foundation covers: create team, list teams with roster counts, edit a team's info + crest, and a
basic roster (add members referencing existing players by their unique operational id). Reuses the
shared TeamService/ImageStorage — no duplicate persistence. View is gated by role, edits by
Performance-Analyst+ (same convention as Scouting/Players).
"""
from __future__ import annotations

import html as _html

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.roles import Role
from fap.scouting import identity as _ident
from fap.theme import components as C
from fap.theme import icon
from fap.ui.page import Page, page_registry

_KINDS = {"club": "Club / First Team", "academy": "Academy", "opponent": "Opponent"}


def _data_uri(data: bytes | None, mime: str = "image/png") -> str:
    import base64
    return f"data:{mime};base64," + base64.b64encode(data).decode() if data else ""


def _age_from_dob(dob: str) -> int | None:
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(dob)[:10])
        t = _dt.date.today()
        return t.year - d.year - ((t.month, t.day) < (d.month, d.day))
    except Exception:
        return None


def _initials(name: str) -> str:
    return "".join(p[:1] for p in str(name or "Player").split()[:2]).upper() or "?"
_SEL = "_teams_selected"
_MEMBER = "_teams_member"          # a roster player opened for analysis/portfolio


@page_registry.register
class TeamsPage(Page):
    info = PluginInfo(id="teams", name="Teams", category="page")
    section = "Squad"
    icon = "teams"
    order = 7                       # after Players (5) and Scouting
    min_role = Role.READ_ONLY

    def render(self, shell) -> None:
        svc = getattr(shell.platform, "teams", None) if shell.platform else None
        if svc is None:
            C.render_alert("Teams service is unavailable in this session.", "warning")
            return
        self._can_edit = shell.user.role >= Role.PERFORMANCE_ANALYST
        C.render_section_title("Teams", eyebrow="Squad", icon_name="teams",
                               subtitle="Club and academy squads — group players, store team "
                                        "info and (soon) matches, media and analysis.")
        selected = st.session_state.get(_SEL)
        if selected and svc.get_team(selected) is not None:
            self._team_detail(shell, svc, selected)
        else:
            st.session_state.pop(_SEL, None)
            self._teams_overview(shell, svc)

    # ---------------------------------------------------------------- overview
    def _teams_overview(self, shell, svc) -> None:
        if self._can_edit:
            with st.expander("Create a team", expanded=False):
                c = st.columns([3, 2, 2])
                name = c[0].text_input("Team name", key="tm_new_name",
                                       placeholder="e.g. First Team, U19, U17")
                kind = c[1].selectbox("Kind", list(_KINDS), format_func=lambda k: _KINDS[k],
                                      key="tm_new_kind")
                age = c[2].selectbox("Age group", [""] + list(_ident.AGE_GROUPS),
                                     format_func=lambda a: a or "—", key="tm_new_age",
                                     disabled=(kind != "academy"))
                c2 = st.columns([2, 2])
                comp = c2[0].text_input("Competition", key="tm_new_comp")
                season = c2[1].text_input("Season", key="tm_new_season", placeholder="2025/26")
                if st.button("Create team", type="primary", key="tm_new_btn"):
                    try:
                        t = svc.create_team(shell.user, name, kind=kind,
                                            age_group=(age if kind == "academy" else ""),
                                            competition=comp, season=season)
                        st.session_state[_SEL] = t.id
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))

        summaries = svc.team_summaries()
        if not summaries:
            C.render_empty_state("No teams yet", "Create an opponent to scout, or a club / academy "
                                 "squad of your own, above.", icon_name="teams")
            return
        from fap.teams.models import team_group
        # two groups: Opponents (scouting focus) and Our teams (Club + Academy)
        groups = [("opponents", "Opponents", "Teams you scout — their data, videos, info and players."),
                  ("our_teams", "Our teams", "Your club and academy squads.")]
        for gkey, gtitle, gsub in groups:
            in_group = [s for s in summaries if team_group(s["kind"]) == gkey]
            if not in_group:
                continue
            st.markdown(f"#### {gtitle}  ·  {len(in_group)}")
            st.caption(gsub)
            for s in in_group:
                cols = st.columns([5, 1], vertical_alignment="center")
                tag = _KINDS.get(s["kind"], s["kind"]) + (f" · {s['age_group']}" if s["age_group"] else "")
                meta = " · ".join(x for x in (tag, s["competition"], s["season"],
                                              f"{s['members']} player(s)",
                                              f"{s.get('matches', 0)} match(es)") if x)
                cols[0].markdown(f"**{_html.escape(s['name'])}**<br>"
                                 f"<span style='color:var(--fap-text-muted)'>{_html.escape(meta)}</span>",
                                 unsafe_allow_html=True)
                if cols[1].button("Open", key=f"tm_open_{s['id']}", use_container_width=True):
                    st.session_state[_SEL] = s["id"]
                    st.rerun()

        # T5: team-level comparison table (records across all teams)
        comp = [c for c in svc.teams_comparison() if c["played"] > 0]
        if len(comp) >= 2:
            st.markdown("#### Compare teams")
            import pandas as pd
            df = pd.DataFrame([{"Team": c["name"], "Players": c["players"], "P": c["played"],
                                "W": c["wins"], "D": c["draws"], "L": c["losses"], "GF": c["gf"],
                                "GA": c["ga"], "GD": c["gd"], "Pts": c["points"],
                                "Win%": c["win_pct"]} for c in comp])
            st.dataframe(df, use_container_width=True, hide_index=True)

    # ---------------------------------------------------------------- detail
    def _team_detail(self, shell, svc, team_id) -> None:
        t = svc.get_team(team_id)
        # a roster player opened -> their own Analysis + Portfolio page (same viz system as scouting)
        sel_member = st.session_state.get(_MEMBER)
        if sel_member:
            member = next((m for m in svc.list_members(team_id) if m.id == sel_member), None)
            if member is not None:
                self._player_detail(shell, svc, t, member)
                return
            st.session_state.pop(_MEMBER, None)
        if st.button("← All teams", key="tm_back"):
            st.session_state.pop(_SEL, None); st.rerun()

        head = st.columns([1, 5], vertical_alignment="center")
        crest = svc.crest_bytes(team_id)
        if crest:
            head[0].image(crest, width=72)
        tag = _KINDS.get(t.kind, t.kind) + (f" · {t.age_group}" if t.age_group else "")
        head[1].markdown(f"### {_html.escape(t.name)}\n"
                         f"<span style='color:var(--fap-text-muted)'>"
                         f"{_html.escape(' · '.join(x for x in (tag, t.competition, t.season) if x))}"
                         f"</span>", unsafe_allow_html=True)

        # Style of Play is only meaningful for OUR squads (club/academy), not scouted opponents.
        sections = [
            ("Overview", lambda: self._overview_tab(shell, svc, t)),
            ("Data", lambda: self._data_tab(shell, svc, t)),
        ]
        if t.kind != "opponent":
            sections.append(("Style of Play", lambda: self._style_tab(shell, svc, t)))
        sections += [
            ("Roster", lambda: self._roster(shell, svc, t)),
            ("Matches", lambda: self._matches(shell, svc, t)),
            ("Media", lambda: self._media_section(shell, svc, t, match_id="")),
            ("Info & crest", lambda: self._info(shell, svc, t)),
        ]
        for tab, (_, render) in zip(st.tabs([s[0] for s in sections]), sections):
            with tab:
                render()

    # ---------------------------------------------------------------- overview (T5)
    def _overview_tab(self, shell, svc, t) -> None:
        rec = svc.team_record(t.id)
        n_players = len(svc.list_members(t.id))
        is_opp = (t.kind == "opponent")
        C.render_metric_row([
            C.metric_card_html("Players", str(n_players), icon_name="players", accent="primary",
                               hint=("scouted" if is_opp else "in squad")),
            C.metric_card_html("Matches", str(rec["played"]), icon_name="match", accent="info",
                               hint="with a score"),
            C.metric_card_html("Record", f"{rec['wins']}-{rec['draws']}-{rec['losses']}",
                               icon_name="pulse", accent="success", hint="W-D-L"),
            C.metric_card_html("Points", str(rec["points"]), icon_name="star", accent="primary",
                               hint=f"{rec['win_pct']}% win rate"),
        ])
        C.render_metric_row([
            C.metric_card_html("Goals for", str(rec["gf"]), icon_name="target", accent="success"),
            C.metric_card_html("Goals against", str(rec["ga"]), icon_name="shield", accent="danger"),
            C.metric_card_html("Goal diff", f"{rec['gd']:+d}" if rec["played"] else "0",
                               icon_name="analysis", accent="info"),
            C.metric_card_html("Linked data", str(len(svc.list_linked_datasets(t.id))),
                               icon_name="datasets", accent="neutral", hint="data files"),
        ])
        # recent matches (form) — last five, most recent first
        matches = sorted(svc.list_matches(t.id), key=lambda mt: (mt.match_date or ""), reverse=True)[:5]
        if matches:
            C.render_dossier_label("Recent matches", icon=icon("clock", 13))
            for mt in matches:
                res = mt.result or "·"
                kind = {"W": "success", "L": "danger", "D": "warning"}.get(res, "neutral")
                line = " · ".join(x for x in (mt.match_date, f"vs {mt.opponent}" if mt.opponent else "",
                                              mt.competition) if x)
                sc = f"  {C.badge_html(mt.scoreline, kind)}" if mt.scoreline else ""
                st.markdown(f"{C.badge_html(res, kind)} &nbsp; {_html.escape(line)}{sc}",
                            unsafe_allow_html=True)
        st.caption("Record is computed from matches that have a score recorded (nothing assumed).")

    # ---------------------------------------------------------------- style of play
    _PILLAR_STYLE = {                       # (icon name, accent) per style pillar
        "Build-up & Possession": ("target", "primary"),
        "High Press": ("shield", "warning"),
        "Fast Recovery": ("pulse", "info"),
        "Attacking Output": ("star", "success"),
    }

    @staticmethod
    def _fmt_metric(md, v) -> str:
        """Format a metric value for its unit; em-dash when unavailable."""
        if v is None:
            return "—"
        v = float(v)
        if md.unit == "percent":
            return f"{v:.0f}%"
        if md.unit == "xg":
            return f"{v:.2f}"
        if md.unit == "ratio":
            return f"{v:.1f}"
        return f"{v:.0f}" if v.is_integer() else f"{v:.1f}"

    def _style_card(self, md, value, last5, allavg) -> str:
        """A KPI card for one style metric: scope value, a trend pill vs the team's
        rolling (all-match) average, and last-5 / average context in the hint."""
        val_s = self._fmt_metric(md, value)
        delta, direction = None, "flat"
        if value is not None and allavg is not None:
            diff = float(value) - float(allavg)
            if abs(diff) > 1e-9:
                improved = (diff > 0) if md.higher_is_better else (diff < 0)
                direction = "up" if improved else "down"
                sign = "+" if diff > 0 else "−"
                delta = f"{sign}{self._fmt_metric(md, abs(diff))} vs avg"
        parts = []
        if last5 is not None:
            parts.append(f"L5 {self._fmt_metric(md, last5)}")
        if allavg is not None:
            parts.append(f"avg {self._fmt_metric(md, allavg)}")
        hint = " · ".join(parts) if parts else (md.help or "")
        icon_name, accent = self._PILLAR_STYLE.get(md.pillar, ("pulse", "neutral"))
        return C.metric_card_html(md.name, val_s, delta=delta, direction=direction,
                                  icon_name=icon_name, accent=accent, hint=hint)

    def _style_tab(self, shell, svc, t) -> None:
        from fap.teams import style as S

        st.markdown("**Style of Play** — how this squad expresses our identity: building play, "
                    "possession, high pressing and fast ball recovery. Every metric is computed "
                    "from each match's linked event data and tracked across matches.")
        series = svc.team_style(t.id)
        played = series.played
        if not played:
            C.render_empty_state(
                "No match data yet",
                "Link event data to this team's matches (Matches tab → “Link active dataset”) to see "
                "style metrics. Each linked match becomes one data point.", icon_name="analysis")
            unresolved = [m for m in series.per_match if not m.resolved]
            if unresolved:
                st.caption(f"{len(unresolved)} linked match(es) couldn't be matched to "
                           f"“{_html.escape(t.name)}” inside the data — check the team name and the "
                           "opponent set on those matches.")
            return

        scope = st.radio("Scope", ["Last match", "Last 5 matches", "All matches"],
                         horizontal=True, key=f"style_scope_{t.id}")
        if scope == "Last match":
            subset = played[-1:]
        elif scope == "Last 5 matches":
            subset = series.window(5)
        else:
            subset = played
        scope_avg = series.averages(subset)
        last5_avg = series.averages(series.window(5))
        all_avg = series.averages(played)

        incl = " · ".join((m.label or m.opponent or m.match_id) for m in subset[-5:])
        note = f"{len(subset)} match(es) in scope · {len(played)} with data"
        if scope != "All matches" and incl:
            note += f" — {_html.escape(incl)}"
        st.caption(note)

        for pillar in S.PILLARS:
            C.render_dossier_label(pillar, icon=icon("pulse", 13))
            cards = [self._style_card(md, scope_avg.get(md.key), last5_avg.get(md.key),
                                      all_avg.get(md.key)) for md in S.metrics_in(pillar)]
            C.render_metric_row(cards)

        st.divider()
        C.render_dossier_label("Trend across matches", icon=icon("clock", 13))
        labels = {md.key: md.name for md in S.METRICS}
        pick = st.selectbox("Metric", list(labels), format_func=lambda k: labels[k],
                            key=f"style_metric_{t.id}")
        md = S.metric(pick)
        pts = series.trend(pick, window=3)
        if any(p["raw"] is not None for p in pts):
            import pandas as pd
            chart_df = pd.DataFrame(
                [{"match": p["label"], md.name: p["raw"], "Rolling avg": p["rolling"]}
                 for p in pts]).set_index("match")
            st.line_chart(chart_df)
            note = md.help or ""
            if not md.higher_is_better:
                note = ("Lower is better for this metric. " + note).strip()
            if note:
                st.caption(note)
        else:
            st.caption("This metric isn't available in the linked data (missing columns) — "
                       "nothing is shown rather than a fabricated value.")

        with st.expander("Data & methodology"):
            st.markdown(
                "- **Source**: each match's linked event data (active-dataset independent). Only "
                "matches whose data resolves to this team contribute.\n"
                "- **Possession, Pass accuracy, Field Tilt, PPDA** reuse the platform's two-team "
                "match-stats engine (the same one used for opponent comparison).\n"
                "- **xG** is the frozen Internal xG Model v1.0, summed over our shots — shown only "
                "when the data supports it.\n"
                "- **Progressive passes, turnovers, counter-press regains, recoveries** reuse the "
                "shared football selectors — no metric is redefined here.\n"
                "- A metric that can't be computed shows “—”; nothing is fabricated.")

    # ---------------------------------------------------------------- data (linked datasets)
    def _data_tab(self, shell, svc, t) -> None:
        """Link Data Hub datasets (e.g. an opposition team's data file) to this team.
        Links are stored on the team and read BY id, so the data keeps showing even
        after a different dataset is activated in the Data Hub — same as scouting."""
        st.markdown("**Linked data**")
        st.caption("Link this team's data file(s) from the Data Hub. A link stays with the team, "
                   "and its data keeps showing even after you activate a different dataset in the hub.")

        if self._can_edit:
            available = svc.available_datasets(shell.workspace_id)
            linked_ids = {l["dataset_id"] for l in svc.list_linked_datasets(t.id)}
            choices = [d for d in available if d.id not in linked_ids]
            if choices:
                labels = {d.id: (d.name + (f" · {d.rows:,} rows" if getattr(d, "rows", 0) else ""))
                          for d in choices}
                c = st.columns([4, 2, 1], vertical_alignment="bottom")
                pick = c[0].selectbox("Data Hub dataset", list(labels),
                                      format_func=lambda i: labels[i], key=f"tm_ds_pick_{t.id}")
                mid = c[1].text_input("Match id (optional)", key=f"tm_ds_mid_{t.id}",
                                      help="Restrict to one match inside the dataset, if it holds many.")
                if c[2].button("Link", type="primary", key=f"tm_ds_link_{t.id}",
                               use_container_width=True):
                    try:
                        svc.link_dataset(shell.user, t.id, pick, match_id=mid.strip())
                        st.toast("Dataset linked")
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
            else:
                st.caption("No unlinked datasets in this workspace. Import one in the Data Hub, "
                           "then link it here.")

        links = svc.list_linked_datasets(t.id, user=shell.user)
        if not links:
            C.render_empty_state("No linked data", "Link this team's dataset above to analyse it "
                                 "here — independent of the active dataset.", icon_name="datasets")
            return
        for l in links:
            cols = st.columns([5, 2, 1], vertical_alignment="center")
            badges = [C.badge_html("Active now", "success")] if l["is_active"] else []
            badges.append(C.badge_html("Available", "info") if l["available"]
                          else C.badge_html("Missing from hub", "danger"))
            meta = " · ".join(x for x in (
                (f"{l['current_rows']:,} rows" if l.get("current_rows") else ""),
                (f"match {l['match_id']}" if l.get("match_id") else ""),
                (f"linked {l['linked_at'][:10]}" if l.get("linked_at") else "")) if x)
            cols[0].markdown(
                f"**{_html.escape(l.get('current_name') or l.get('dataset_name', ''))}** &nbsp; "
                f"{' '.join(badges)}<br><span style='color:var(--fap-text-muted)'>"
                f"{_html.escape(meta)}</span>", unsafe_allow_html=True)
            if l["available"] and cols[1].button("Analyse", key=f"tm_ds_an_{t.id}_{l['dataset_id']}",
                                                  use_container_width=True):
                st.session_state[f"tm_ds_sel_{t.id}"] = l["dataset_id"]
                st.rerun()
            if self._can_edit and cols[2].button("Unlink", key=f"tm_ds_rm_{t.id}_{l['dataset_id']}",
                                                  use_container_width=True):
                svc.unlink_dataset(shell.user, t.id, l["dataset_id"])
                st.session_state.pop(f"tm_ds_sel_{t.id}", None)
                st.rerun()

        sel = st.session_state.get(f"tm_ds_sel_{t.id}")
        sel_link = next((l for l in links if l["dataset_id"] == sel and l["available"]), None)
        if sel_link is None:
            st.caption("Select **Analyse** on a linked dataset to explore it (independent of the "
                       "active dataset in the Data Hub).")
            return
        st.divider()
        self._data_analysis(shell, svc, t, sel_link)

    @staticmethod
    def _distinct_count(df, cols) -> int:
        for col in cols:
            if col in df.columns:
                return int(df[col].astype(str).str.strip().replace("", None).dropna().nunique())
        return 0

    def _data_analysis(self, shell, svc, t, link) -> None:
        """Explore a team's linked dataset — summary, preview and the full visualization
        workspace — read BY id and rendered independent of the active dataset."""
        frame = svc.team_dataset_frame(t.id, link["dataset_id"])
        if frame is None:
            C.render_alert("This dataset has no readable rows (it may have been removed).", "warning")
            return
        df = frame
        if link.get("match_id") and "match_id" in df.columns:
            df = df[df["match_id"].astype(str) == str(link["match_id"])]
        st.markdown(f"**Analysing:** {_html.escape(link.get('current_name') or '')}")
        c = st.columns(4)
        c[0].metric("Rows", f"{len(df):,}")
        c[1].metric("Columns", len(df.columns))
        c[2].metric("Players", self._distinct_count(df, ("player", "player_name", "player.name")))
        c[3].metric("Matches", self._distinct_count(df, ("match_id",)))
        with st.expander("Data preview", expanded=False):
            st.dataframe(df.head(50), use_container_width=True, hide_index=True)
        st.caption("Tip: set **Render scope → Whole match** for team-level maps and networks.")
        from fap.ui.components.viz_workspace import render_visualization_workspace

        def _save(png, title, viz_id):
            svc.add_chart(shell.user, t.id, png, "image/png", title=title, kind="chart")

        render_visualization_workspace(
            shell, frame=df, player_name=t.name,
            key=f"tmdsviz_{t.id}_{link['dataset_id']}",
            on_assign=(_save if self._can_edit else None),
            dataset_context=(link["dataset_id"], link.get("current_name") or t.name))

    # ---------------------------------------------------------------- media (T4)
    def _media_section(self, shell, svc, t, match_id: str = "") -> None:
        if self._can_edit:
            add = st.radio("Add", ["Note", "Video link", "Video upload", "Chart / image"],
                           horizontal=True, key=f"tmm_type_{t.id}_{match_id}")
            if add == "Note":
                ti = st.text_input("Title", key=f"tmm_nt_{t.id}_{match_id}")
                bo = st.text_area("Note", key=f"tmm_nb_{t.id}_{match_id}", height=80)
                if st.button("Add note", key=f"tmm_nadd_{t.id}_{match_id}"):
                    try:
                        svc.add_note(shell.user, t.id, title=ti, body=bo, match_id=match_id)
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
            elif add == "Video link":
                vt = st.text_input("Title", key=f"tmm_vt_{t.id}_{match_id}")
                vu = st.text_input("Video URL (YouTube / Vimeo / Hudl / …)",
                                   key=f"tmm_vu_{t.id}_{match_id}")
                if st.button("Add video", key=f"tmm_vadd_{t.id}_{match_id}"):
                    try:
                        svc.add_video(shell.user, t.id, url=vu, title=vt, match_id=match_id)
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
            elif add == "Video upload":
                vt = st.text_input("Title", key=f"tmm_vft_{t.id}_{match_id}")
                vf = st.file_uploader("Video file", type=["mp4", "mov", "webm", "m4v", "avi", "mkv"],
                                      key=f"tmm_vfu_{t.id}_{match_id}")
                if vf is not None and st.button("Upload video", key=f"tmm_vfadd_{t.id}_{match_id}"):
                    try:
                        svc.add_video(shell.user, t.id, title=(vt or vf.name), data=vf.getvalue(),
                                      filename=vf.name, mime=vf.type or "video/mp4", match_id=match_id)
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
            else:
                ct = st.text_input("Title", key=f"tmm_ct_{t.id}_{match_id}")
                up = st.file_uploader("Chart / image", type=["png", "jpg", "jpeg", "webp"],
                                      key=f"tmm_cu_{t.id}_{match_id}")
                if up is not None and st.button("Add chart / image", key=f"tmm_cadd_{t.id}_{match_id}"):
                    svc.add_chart(shell.user, t.id, up.getvalue(), up.type or "image/png",
                                  title=ct, match_id=match_id)
                    st.rerun()
        media = svc.list_media(t.id, match_id=match_id)
        if not media:
            st.caption("No notes, videos or charts yet.")
            return
        for md in media:
            cols = st.columns([6, 1], vertical_alignment="center")
            if md.kind == "note":
                cols[0].markdown(f"**{_html.escape(md.title or 'Note')}**  \n"
                                 f"{_html.escape(md.body)}")
            elif md.kind in ("chart", "image"):
                data = svc.media_bytes(md)
                if data:
                    cols[0].image(data, caption=md.title or md.kind, width=300)
                else:
                    cols[0].caption(md.title or md.kind)
            else:  # video / clip
                if md.file_id:                              # uploaded file → inline player
                    data = svc.media_bytes(md)
                    cols[0].caption(md.title or "Uploaded video")
                    if data:
                        cols[0].video(data)
                elif md.url:
                    cols[0].markdown(f"[{_html.escape(md.title or 'Video')}]({md.url})")
                else:
                    cols[0].caption(md.title or "Uploaded video")
            if self._can_edit and cols[1].button("Delete", key=f"tmm_del_{md.id}",
                                                  use_container_width=True):
                svc.delete_media(shell.user, md.id)
                st.rerun()

    # ---------------------------------------------------------------- matches (T3)
    def _matches(self, shell, svc, t) -> None:
        matches = svc.list_matches(t.id)
        if self._can_edit:
            with st.expander("Add a match", expanded=not matches):
                c = st.columns([3, 2, 2])
                opp = c[0].text_input("Opponent", key=f"tmch_opp_{t.id}", placeholder="e.g. Barcelona")
                date = c[1].text_input("Date", key=f"tmch_date_{t.id}", placeholder="2025-09-14")
                venue = c[2].selectbox("Venue", ["home", "away", "neutral"], key=f"tmch_venue_{t.id}")
                c2 = st.columns([2, 1, 1, 2])
                comp = c2[0].text_input("Competition", key=f"tmch_comp_{t.id}")
                us = c2[1].number_input("Us", min_value=0, max_value=99, step=1, value=0,
                                        key=f"tmch_us_{t.id}")
                them = c2[2].number_input("Them", min_value=0, max_value=99, step=1, value=0,
                                          key=f"tmch_them_{t.id}")
                form = c2[3].text_input("Formation", key=f"tmch_form_{t.id}", placeholder="4-3-3")
                notes = st.text_area("Match notes", key=f"tmch_notes_{t.id}", height=80)
                score_set = st.checkbox("Record the score", key=f"tmch_hasscore_{t.id}", value=False)
                if st.button("Add match", type="primary", key=f"tmch_add_{t.id}"):
                    try:
                        svc.create_match(shell.user, t.id, opponent=opp, match_date=date,
                                         competition=comp, venue=venue, formation=form, notes=notes,
                                         our_score=(us if score_set else None),
                                         opp_score=(them if score_set else None))
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
        if not matches:
            C.render_empty_state("No matches yet", "Add a match above (e.g. vs Barcelona).",
                                 icon_name="flag")
            return
        st.caption(f"{len(matches)} match(es)")
        for mt in matches:
            head = " · ".join(x for x in (mt.match_date, mt.competition,
                                          {"home": "Home", "away": "Away", "neutral": "Neutral"}.get(mt.venue, "")) if x)
            score = f"  {mt.scoreline} ({mt.result})" if mt.scoreline else ""
            with st.expander(f"vs {mt.opponent}{score}  —  {head}".strip(" -")):
                self._match_detail(shell, svc, t, mt)

    def _match_detail(self, shell, svc, t, mt) -> None:
        if not self._can_edit:
            st.write(mt.notes or "_No notes._")
            if mt.formation:
                st.caption(f"Formation: {mt.formation}")
            return
        c = st.columns([2, 2, 2])
        opp = c[0].text_input("Opponent", value=mt.opponent, key=f"md_opp_{mt.id}")
        date = c[1].text_input("Date", value=mt.match_date, key=f"md_date_{mt.id}")
        venue = c[2].selectbox("Venue", ["home", "away", "neutral"],
                               index=["home", "away", "neutral"].index(mt.venue)
                               if mt.venue in ("home", "away", "neutral") else 0, key=f"md_venue_{mt.id}")
        c2 = st.columns([2, 1, 1, 2])
        comp = c2[0].text_input("Competition", value=mt.competition, key=f"md_comp_{mt.id}")
        us = c2[1].number_input("Us", 0, 99, int(mt.our_score) if mt.our_score is not None else 0,
                                key=f"md_us_{mt.id}")
        them = c2[2].number_input("Them", 0, 99, int(mt.opp_score) if mt.opp_score is not None else 0,
                                  key=f"md_them_{mt.id}")
        form = c2[3].text_input("Formation", value=mt.formation, key=f"md_form_{mt.id}")
        notes = st.text_area("Match notes", value=mt.notes, key=f"md_notes_{mt.id}", height=100)
        has_score = st.checkbox("Score recorded", value=(mt.our_score is not None),
                                key=f"md_hasscore_{mt.id}")
        # link the match data (an event dataset) — stored permanently, active-independent
        mid = st.text_input("Match id in the dataset (optional)", value=mt.match_id, key=f"md_mid_{mt.id}")
        linked = mt.dataset_id
        try:
            active = shell.wm.active_dataset(shell.user) if shell.wm else None
        except Exception:
            active = None
        b = st.columns([1, 1, 2, 1])
        if b[0].button("Save", type="primary", key=f"md_save_{mt.id}"):
            svc.update_match(shell.user, mt.id, opponent=opp, match_date=date, competition=comp,
                             venue=venue, formation=form, notes=notes, match_id=mid,
                             our_score=(us if has_score else None),
                             opp_score=(them if has_score else None))
            st.rerun()
        if active is not None and b[1].button("Link active dataset", key=f"md_link_{mt.id}"):
            svc.update_match(shell.user, mt.id, dataset_id=active.id)
            st.rerun()
        if linked and b[2].button("Unlink data", key=f"md_unlink_{mt.id}"):
            svc.update_match(shell.user, mt.id, dataset_id="")
            st.rerun()
        if b[3].button("Delete", key=f"md_del_{mt.id}"):
            svc.delete_match(shell.user, mt.id); st.rerun()
        if linked:
            st.caption(f"Data linked (dataset id {linked[:8]}) — stays linked regardless of the "
                       "active dataset.")
        st.divider()
        st.markdown("**Match media** — notes, clips, videos and charts for this match")
        self._media_section(shell, svc, t, match_id=mt.id)
        self._match_player_analysis(shell, svc, t, mt)

    # ---------------------------------------------------------------- player analysis (T6)
    def _match_player_analysis(self, shell, svc, t, mt) -> None:
        """Generate charts for a roster player from this match's LINKED data and save them to that
        player's portfolio. Reuses the existing player visualization workspace + Save-to-player."""
        st.divider()
        st.markdown("**Player analysis & portfolio** — charts per player from this match's data")
        if not mt.dataset_id:
            st.caption("Link this match to its event dataset (above) to generate player charts.")
            return
        roster = svc.list_members(t.id)
        if not roster:
            st.caption("Add players to the roster first.")
            return
        opts = {m.id: (m.player_name or m.operational_id or "player") for m in roster}
        pick = st.selectbox("Player", list(opts), format_func=lambda i: opts[i], key=f"mp_pl_{mt.id}")
        member = next((m for m in roster if m.id == pick), None)
        frame = svc.match_player_frame(mt.id, member.player_name if member else "")
        # the viz workspace expects the match's dataset to be the active query context (same as the
        # scouting evidence "Open") — set it so its scope/rendering align with this match's data.
        try:
            if shell.wm is not None:
                shell.wm.set_active_dataset(shell.user, mt.dataset_id)
        except Exception:
            pass
        if frame is None:
            st.caption("No events for this player in the linked match data.")
        else:
            from fap.scouting.catalog import curate_for_scouting
            from fap.ui.components.viz_workspace import render_visualization_workspace

            def _save(png, title, viz_id, mid=mt.id, memid=pick):
                svc.add_chart(shell.user, t.id, png, "image/png", title=title,
                              match_id=mid, member_id=memid, kind="chart")

            render_visualization_workspace(
                shell, frame=frame, player_name=(member.player_name if member else "player"),
                key=f"teamviz_{mt.id}_{pick}",
                on_assign=(_save if self._can_edit else None), curate=curate_for_scouting)
        # this player's saved charts for THIS match (their portfolio grows across matches)
        saved = svc.list_media(t.id, match_id=mt.id, member_id=pick, kind="chart")
        if saved:
            st.markdown(f"**{opts[pick]} — saved charts for this match ({len(saved)}):**")
            for md in saved:
                b = svc.media_bytes(md)
                pc = st.columns([6, 1], vertical_alignment="center")
                if b:
                    pc[0].image(b, caption=md.title or "chart", width=260)
                else:
                    pc[0].caption(md.title or "chart")
                if self._can_edit and pc[1].button("Delete", key=f"mp_del_{md.id}",
                                                    use_container_width=True):
                    svc.delete_media(shell.user, md.id)
                    st.rerun()

    def _existing_players(self, shell, exclude) -> list[dict]:
        """Players already registered elsewhere (scouting + first-team), for the roster picker.
        UI-only reuse of the other platform services — the Teams service stays decoupled."""
        out: list[dict] = []
        plat = getattr(shell, "platform", None)
        for svc_name, source, label in (("scouting", "scouting", "Scouting"),
                                        ("players", "first_team", "First Team")):
            svc2 = getattr(plat, svc_name, None) if plat else None
            if svc2 is None or not hasattr(svc2, "search"):
                continue
            try:
                for p in (svc2.search(shell.user) or []):
                    if p.id in exclude:
                        continue
                    out.append({"key": f"{source}:{p.id}", "name": p.name, "player_id": p.id,
                                "operational_id": _ident.operational_id_of(p),
                                "source": source, "label": label})
            except Exception:
                continue
        return out

    def _roster(self, shell, svc, t) -> None:
        members = svc.list_members(t.id)
        exclude = {m.player_id for m in members if m.player_id}
        if self._can_edit:
            # T2: pick from players already in your scouting / first-team database (reuse id + name)
            pool = self._existing_players(shell, exclude)
            with st.expander("Add players from your database", expanded=bool(pool) and not members):
                if pool:
                    labels = {p["key"]: f"{p['name']} · {p['operational_id'] or 'no id'} · {p['label']}"
                              for p in pool}
                    picks = st.multiselect("Pick existing players", [p["key"] for p in pool],
                                           format_func=lambda k: labels[k], key=f"tm_pick_{t.id}")
                    if picks and st.button("Add selected to roster", key=f"tm_pickadd_{t.id}"):
                        by_key = {p["key"]: p for p in pool}
                        for k in picks:
                            pk = by_key[k]
                            svc.add_member(shell.user, t.id, player_name=pk["name"],
                                           operational_id=pk["operational_id"],
                                           player_id=pk["player_id"], source=pk["source"])
                        st.rerun()
                else:
                    st.caption("No players found in your scouting / first-team database yet "
                               "(or all of them are already in this roster).")
            with st.expander("Add a new player manually", expanded=not members and not pool):
                st.caption("Enter the player profile now; you can update every field later from the player's Overview.")
                c = st.columns([3, 2, 1, 2])
                nm = c[0].text_input("Player name", key=f"tm_mn_{t.id}")
                oid = c[1].text_input("Operational id (optional)", key=f"tm_moid_{t.id}",
                                      placeholder="leave blank to auto-generate")
                sh = c[2].text_input("No.", key=f"tm_msh_{t.id}")
                role = c[3].text_input("Role/position", key=f"tm_mrole_{t.id}")
                p1 = st.columns(4)
                second_role = p1[0].text_input("Secondary position", key=f"tm_mrole2_{t.id}")
                dob = p1[1].text_input("Date of birth", placeholder="YYYY-MM-DD", key=f"tm_mdob_{t.id}")
                nationality = p1[2].text_input("Nationality", key=f"tm_mnat_{t.id}")
                foot = p1[3].selectbox("Preferred foot", ["", "Right", "Left", "Both"],
                                       format_func=lambda x: x or "Select", key=f"tm_mfoot_{t.id}")
                p2 = st.columns(4)
                height = p2[0].number_input("Height (cm)", 0, 250, 0, key=f"tm_mheight_{t.id}")
                weight = p2[1].number_input("Weight (kg)", 0, 200, 0, key=f"tm_mweight_{t.id}")
                joined = p2[2].text_input("Joined date", placeholder="YYYY-MM-DD", key=f"tm_mjoined_{t.id}")
                contract = p2[3].text_input("Contract end", placeholder="YYYY-MM-DD", key=f"tm_mcontract_{t.id}")
                p3 = st.columns(3)
                availability = p3[0].selectbox("Availability", ["available", "injured", "suspended", "unavailable"], key=f"tm_mavailability_{t.id}")
                phone = p3[1].text_input("Phone", key=f"tm_mphone_{t.id}")
                email = p3[2].text_input("Email", key=f"tm_memail_{t.id}")
                p4 = st.columns(2)
                emergency = p4[0].text_input("Emergency contact", key=f"tm_memergency_{t.id}")
                agent = p4[1].text_input("Agent / representative", key=f"tm_magent_{t.id}")
                profile_notes = st.text_area("Player notes", key=f"tm_mnotes_{t.id}", height=80)
                if st.button("Add to roster", key=f"tm_madd_{t.id}"):
                    try:
                        m = svc.add_member(shell.user, t.id, player_name=nm, operational_id=oid,
                                           shirt_number=sh, role=role, secondary_role=second_role,
                                           date_of_birth=dob, nationality=nationality, preferred_foot=foot,
                                           height_cm=(height or None), weight_kg=(weight or None),
                                           joined_date=joined, contract_end=contract,
                                           availability=availability, phone=phone, email=email,
                                           emergency_contact=emergency, agent=agent, notes=profile_notes)
                        st.toast(f"Added {m.player_name or 'player'} · {m.operational_id}")
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
                pfx = "ACD" if t.kind == "academy" else "CLB"
                st.caption(f"Leave the id blank and each new player gets a unique **{pfx}-** id "
                           "automatically. (Later phases: pick from your existing scouting / "
                           "first-team players.)")
            self._import_roster(shell, svc, t)
        if not members:
            C.render_empty_state("Empty roster", "Add players above.", icon_name="players")
            return
        self._roster_view(shell, svc, t, members)

    def _roster_view(self, shell, svc, t, members) -> None:
        """The premium squad view — Grid (photo cards) / List (rows) / Table — the same
        look the standalone Players page used, fed from the team roster."""
        head = st.columns([2, 2], vertical_alignment="center")
        head[0].caption(f"{len(members)} player(s) — open one for the dashboard, analysis & portfolio")
        view = head[1].radio("View", ["Grid", "List", "Table"], horizontal=True,
                             key=f"tm_rv_{t.id}", label_visibility="collapsed")
        if view == "Table":
            rows = [{"#": m.shirt_number or "", "Name": m.player_name,
                     "ID": m.operational_id, "Position": m.role,
                     "Age": _age_from_dob(m.date_of_birth) or "",
                     "Nationality": m.nationality, "Foot": (m.preferred_foot or "").title(),
                     "Availability": (m.availability or "available").title()} for m in members]
            st.dataframe(rows, use_container_width=True, hide_index=True)
            return
        if view == "List":
            for m in members:
                self._member_row(shell, svc, t, m)
            return
        cols = st.columns(3)
        for i, m in enumerate(members):
            with cols[i % 3]:
                self._member_card(shell, svc, t, m)

    def _member_card(self, shell, svc, t, m) -> None:
        age = _age_from_dob(m.date_of_birth)
        st.markdown(C.player_card_html(
            _html.escape(m.player_name or m.operational_id or "Player"),
            number=(m.shirt_number or None), position=m.role or "",
            nationality=m.nationality or "", age=(f"{age} yrs" if age is not None else ""),
            contract=(f"exp {m.contract_end}" if m.contract_end else ""),
            minutes=(m.operational_id or ""),
            photo_uri=_data_uri(svc.member_photo_bytes(m.id)),
            status=(m.availability or "available")), unsafe_allow_html=True)
        b = st.columns([3, 1]) if self._can_edit else [st]
        if b[0].button("Open profile", key=f"tm_gopen_{m.id}", use_container_width=True):
            st.session_state[_MEMBER] = m.id; st.rerun()
        if self._can_edit and b[1].button("✕", key=f"tm_grm_{m.id}", use_container_width=True,
                                          help="Remove from roster"):
            svc.remove_member(shell.user, m.id); st.rerun()

    def _member_row(self, shell, svc, t, m) -> None:
        with st.container(border=True):
            c = st.columns([1, 3, 2, 1], vertical_alignment="center")
            photo = svc.member_photo_bytes(m.id)
            if photo:
                c[0].image(photo, use_container_width=True)
            else:
                c[0].markdown(C.avatar_html(initials=_initials(m.player_name), size=46),
                              unsafe_allow_html=True)
            num = f"#{m.shirt_number} " if m.shirt_number else ""
            c[1].markdown(f"**{num}{_html.escape(m.player_name or m.operational_id or 'Player')}**  \n"
                          f"{_html.escape(m.role or '—')} · {_age_from_dob(m.date_of_birth) or '—'} · "
                          f"{_html.escape(m.nationality or '—')}")
            avail = (m.availability or "available").title()
            c[2].markdown(
                C.badge_html(avail, "success" if avail.lower() == "available" else "warning")
                + (f"<br><span style='color:var(--fap-text-muted);font-size:.8rem'>"
                   f"{_html.escape(m.operational_id or '')}</span>" if m.operational_id else ""),
                unsafe_allow_html=True)
            if c[3].button("Open", key=f"tm_lopen_{m.id}", use_container_width=True):
                st.session_state[_MEMBER] = m.id; st.rerun()

    def _import_roster(self, shell, svc, t) -> None:
        """Bulk-import a roster from a CSV/Excel file — at minimum a column of
        names. Reuses the shared roster-import component and the same
        ``add_member`` service as the manual form (no duplicate persistence).
        Each row becomes a squad player; a blank operational id is auto-assigned."""
        from fap.ui.components.roster_import import FieldSpec, render_roster_import

        source = "first_team" if t.kind == "club" else "scouting"
        with st.expander("Import roster from CSV / Excel", expanded=False):
            st.caption("Upload a squad list — a **Name** column is all that's required; "
                       "any other columns below are matched automatically.")
            specs = [
                FieldSpec("player_name", "Name",
                          ("name", "player", "player name", "full name"), required=True),
                FieldSpec("shirt_number", "Shirt number",
                          ("number", "no", "shirt", "shirt no", "squad number")),
                FieldSpec("role", "Position", ("position", "pos", "primary position")),
                FieldSpec("secondary_role", "Secondary position",
                          ("secondary position", "other position")),
                FieldSpec("operational_id", "Operational id", ("id", "player id", "op id")),
                FieldSpec("date_of_birth", "Date of birth",
                          ("dob", "birth date", "born")),
                FieldSpec("nationality", "Nationality", ("nation", "country")),
                FieldSpec("preferred_foot", "Preferred foot", ("foot",),
                          choices=("Right", "Left", "Both")),
                FieldSpec("height_cm", "Height (cm)", ("height", "height cm"), kind="int"),
                FieldSpec("weight_kg", "Weight (kg)", ("weight", "weight kg"), kind="int"),
                FieldSpec("joined_date", "Joined date", ("joined", "join date", "signed")),
                FieldSpec("contract_end", "Contract end",
                          ("contract", "contract until", "contract expiry")),
                FieldSpec("availability", "Availability", (),
                          choices=("available", "injured", "suspended", "unavailable")),
                FieldSpec("agent", "Agent", ("representative",)),
                FieldSpec("email", "Email", ()),
                FieldSpec("phone", "Phone", ("mobile",)),
                FieldSpec("notes", "Notes", ("note", "comment")),
            ]

            def create_row(row: dict) -> None:
                name = str(row.pop("player_name", "")).strip()
                svc.add_member(shell.user, t.id, player_name=name, source=source, **row)

            render_roster_import(key=f"tm_import_{t.id}", specs=specs,
                                 create_row=create_row, noun="player",
                                 can_edit=self._can_edit)

    # ---------------------------------------------------------------- player page (T6)
    def _player_detail(self, shell, svc, t, member) -> None:
        """A roster player's own page — the SAME visualization system as scouting, plus a
        portfolio of every chart saved for them across the team's matches."""
        if st.button("← Back to team", key=f"pd_back_{member.id}"):
            st.session_state.pop(_MEMBER, None); st.rerun()
        # premium player hero (same look as the Players page) + snapshot counts
        self._member_hero(shell, svc, t, member)
        if self._can_edit:
            with st.expander("Edit player info", expanded=False):
                self._edit_player_profile(shell, svc, member)
        tabs = st.tabs(["Dashboard", "Analysis", "Development", "Evidence", "Media", "Reports"])
        with tabs[0]:
            self._player_overview(shell, svc, member)
        with tabs[1]:
            self._player_analysis(shell, svc, t, member)
        with tabs[2]:
            self._player_development(shell, svc, t, member)
        with tabs[3]:
            self._player_evidence(svc, t, member)
        with tabs[4]:
            self._player_media(shell, svc, t, member)
        with tabs[5]:
            self._player_reports(svc, member)

    def _member_hero(self, shell, svc, t, member) -> None:
        """The premium dossier hero (photo/crest/identity/badges/context) + snapshot
        counts — the same look the standalone Players page used, fed from the roster
        member and this team's linked-match data."""
        stats = svc.player_dashboard(t.id, member.id)
        media = svc.list_media(t.id, member_id=member.id)
        counts = {"video": 0, "chart": 0, "note": 0}
        for md in media:
            counts[md.kind] = counts.get(md.kind, 0) + 1
        badges = ""
        if member.shirt_number:
            badges += C.badge_html(f"#{member.shirt_number}", "neutral") + " "
        avail = (member.availability or "available").title()
        badges += C.badge_html(avail, "success" if avail.lower() == "available" else "warning")
        src = {"scouting": "Scouted", "first_team": "First team"}.get(member.source, "")
        if src:
            badges += " " + C.badge_html(src, "info")
        oid = member.operational_id or (f"ID {member.player_id[:8]}" if member.player_id else "")
        age = _age_from_dob(member.date_of_birth)
        ctx = [("Age", str(age) if age is not None else "—"),
               ("Nationality", _html.escape(member.nationality or "—")),
               ("Foot", (member.preferred_foot or "").title() or "—"),
               ("Shirt", f"#{member.shirt_number}" if member.shirt_number else "—")]
        C.render_player_hero(
            _html.escape(member.player_name or "Player"),
            position_line=_html.escape("  ·  ".join(x for x in (member.role or "Player", t.name) if x)),
            photo_uri=_data_uri(svc.member_photo_bytes(member.id)),
            initials=_initials(member.player_name),
            logo_uri=_data_uri(svc.crest_bytes(t.id)),
            badges_html=badges, operational_id=_html.escape(oid), context=ctx)
        C.render_snapshot_counts([
            (icon("match", 16), str(stats["appearances"]), "Matches"),
            (icon("datasets", 16), str(stats["linked_matches"]), "Data sources"),
            (icon("video", 16), str(counts.get("video", 0)), "Videos"),
            (icon("grid", 16), str(counts.get("chart", 0)), "Saved visuals"),
            (icon("text", 16), str(counts.get("note", 0)), "Notes"),
            (icon("layers", 16), str(stats["events"]), "Player events"),
        ])

    def _player_analysis(self, shell, svc, t, member) -> None:
        """Per-match visualization — rendered from the match's LINKED dataset BY ID
        (active-independent: it does not change, and does not need, the globally active
        dataset), reusing the shared player viz workspace."""
        matches = [mt for mt in svc.list_matches(t.id) if mt.dataset_id]
        if not matches:
            C.render_alert("No matches with linked data yet. In the Matches tab, add a match and "
                           "link its event dataset — then generate this player's charts here.", "info")
            return
        labels = {mt.id: (f"vs {mt.opponent}" + (f" · {mt.match_date}" if mt.match_date else ""))
                  for mt in matches}
        mid = st.selectbox("Match", list(labels), format_func=lambda i: labels[i],
                           key=f"pd_m_{member.id}")
        mt = next((x for x in matches if x.id == mid), None)
        frame = svc.match_player_frame(mid, member.player_name)
        if frame is None:
            C.render_alert(f"No events for {member.player_name or 'this player'} in that "
                           "match's data (the name may differ in the dataset).", "info")
            return
        from fap.scouting.catalog import curate_for_scouting
        from fap.ui.components.viz_workspace import render_visualization_workspace

        def _save(png, title, viz_id, mid=mid, memid=member.id):
            svc.add_chart(shell.user, t.id, png, "image/png", title=title,
                          match_id=mid, member_id=memid, kind="chart")

        ds_name = labels[mid]
        render_visualization_workspace(
            shell, frame=frame, player_name=(member.player_name or "player"),
            key=f"pdviz_{member.id}_{mid}",
            on_assign=(_save if self._can_edit else None), curate=curate_for_scouting,
            dataset_context=(mt.dataset_id, ds_name))   # active-INDEPENDENT

    def _player_development(self, shell, svc, t, member) -> None:
        """The player's progression across the team's linked matches — if you attach 5
        matches (5 datasets), you see the trend across all 5. Active-independent."""
        prog = svc.player_progression(t.id, member.id)
        if len(prog) < 1:
            C.render_alert("No linked-match data for this player yet. Add matches with linked "
                           "event datasets (Matches tab) to build a development trend.", "info")
            return
        st.caption(f"{len(prog)} match(es) with data for {member.player_name or 'this player'} · "
                   "oldest → newest. Every value is counted from that match's own dataset.")
        metric_labels = {"events": "Events", "minutes": "Minutes", "passes": "Passes",
                         "pass_completion": "Pass %", "progressive_passes": "Progressive passes",
                         "key_passes": "Key passes", "crosses": "Crosses",
                         "final_third_passes": "Final-third passes", "take_ons": "Take-ons",
                         "shots": "Shots", "shots_on_target": "Shots on target",
                         "xg": "xG", "goals": "Goals", "assists": "Assists",
                         "tackles": "Tackles", "interceptions": "Interceptions",
                         "recoveries": "Recoveries"}
        metric = st.selectbox("Metric", list(metric_labels),
                              format_func=lambda k: metric_labels[k], key=f"pdev_metric_{member.id}")
        import pandas as pd
        rows = []
        for i, m in enumerate(prog, 1):
            lab = (f"vs {m['opponent']}" if m['opponent'] else f"Match {i}")
            if m.get("match_date"):
                lab += f"\n{m['match_date']}"
            rows.append({"Match": lab, metric_labels[metric]: m.get(metric)})
        chart_df = pd.DataFrame(rows).set_index("Match")
        st.line_chart(chart_df, use_container_width=True)
        # full per-match table + the linked dataset behind each point (transparency)
        table = [{"Match": (f"vs {m['opponent']}" if m['opponent'] else f"Match {i}"),
                  "Date": m.get("match_date", ""), "Score": m.get("scoreline", ""),
                  **{metric_labels[k]: m.get(k) for k in metric_labels}}
                 for i, m in enumerate(prog, 1)]
        st.dataframe(table, use_container_width=True, hide_index=True)

    def _player_evidence(self, svc, t, member) -> None:
        """Match-level evidence, mirroring Scouting's evidence separation."""
        matches = [m for m in svc.list_matches(t.id) if m.dataset_id]
        C.render_dossier_label(f"Match evidence ({len(matches)})")
        if not matches:
            C.render_alert("No linked match data yet. Link a dataset in the team's Matches tab.", "info")
            return
        for mt in matches:
            frame = svc.match_player_frame(mt.id, member.player_name)
            event_count = len(frame) if frame is not None else 0
            title = f"vs {mt.opponent}" if mt.opponent else "Match"
            meta = " · ".join(x for x in (mt.match_date, mt.competition,
                                           f"{event_count} player events") if x)
            st.markdown(C.evidence_card_html(_html.escape(title), _html.escape(meta)),
                        unsafe_allow_html=True)

    def _player_media(self, shell, svc, t, member) -> None:
        """Player-scoped notes, videos (link or uploaded file) and saved visual evidence,
        grouped under the match each item belongs to."""
        if self._can_edit:
            with st.expander("Add player media", expanded=False):
                kind = st.radio("Add", ["Note", "Video link", "Video upload"], horizontal=True,
                                key=f"pmed_kind_{member.id}")
                title = st.text_input("Title", key=f"pmed_title_{member.id}")
                # optionally file the item under one of the team's matches
                matches = svc.list_matches(t.id)
                mopts = {"": "General (no match)"} | {
                    mt.id: (f"vs {mt.opponent}" if mt.opponent else "Match")
                           + (f" · {mt.match_date}" if mt.match_date else "") for mt in matches}
                mid = st.selectbox("Match (optional)", list(mopts),
                                   format_func=lambda k: mopts[k], key=f"pmed_match_{member.id}")
                if kind == "Note":
                    body = st.text_area("Note", key=f"pmed_body_{member.id}", height=90)
                    if st.button("Add note", key=f"pmed_note_{member.id}"):
                        try:
                            svc.add_note(shell.user, t.id, title=title, body=body,
                                         member_id=member.id, match_id=mid)
                            st.rerun()
                        except ValueError as exc:
                            st.warning(str(exc))
                elif kind == "Video link":
                    url = st.text_input("Video URL", key=f"pmed_url_{member.id}")
                    if st.button("Add video", key=f"pmed_video_{member.id}"):
                        try:
                            svc.add_video(shell.user, t.id, title=title, url=url,
                                          member_id=member.id, match_id=mid)
                            st.rerun()
                        except ValueError as exc:
                            st.warning(str(exc))
                else:
                    up = st.file_uploader("Video file",
                                          type=["mp4", "mov", "webm", "m4v", "avi", "mkv"],
                                          key=f"pmed_vfile_{member.id}")
                    if up is not None and st.button("Upload video", key=f"pmed_vup_{member.id}"):
                        try:
                            svc.add_video(shell.user, t.id, title=(title or up.name),
                                          data=up.getvalue(), filename=up.name,
                                          mime=up.type or "video/mp4",
                                          member_id=member.id, match_id=mid)
                            st.rerun()
                        except ValueError as exc:
                            st.warning(str(exc))
        media = svc.list_media(t.id, member_id=member.id)
        if not media:
            st.caption("No player media or saved visualizations yet.")
            return
        # group everything under the match it belongs to (charts/videos/notes), general last
        labels = {mt.id: (f"vs {mt.opponent}" if mt.opponent else "Match")
                        + (f" · {mt.match_date}" if mt.match_date else "")
                  for mt in svc.list_matches(t.id)}
        groups: dict[str, list] = {}
        for md in media:
            groups.setdefault(md.match_id or "", []).append(md)
        ordered = [k for k in labels if k in groups] + (["" ] if "" in groups else [])
        C.render_dossier_label(f"Player media ({len(media)})")
        for gid in ordered:
            items = groups.get(gid, [])
            if not items:
                continue
            st.markdown(f"**{_html.escape(labels.get(gid, 'General'))}** "
                        f"<span style='color:var(--fap-text-muted)'>· {len(items)} item(s)</span>",
                        unsafe_allow_html=True)
            for md in items:
                self._render_player_media_item(shell, svc, md)

    def _render_player_media_item(self, shell, svc, md) -> None:
        cols = st.columns([6, 1], vertical_alignment="center")
        if md.kind == "note":
            cols[0].markdown(f"**{_html.escape(md.title or 'Note')}**  \n{_html.escape(md.body)}")
        elif md.kind in ("chart", "image"):
            data = svc.media_bytes(md)
            if data:
                cols[0].image(data, caption=md.title or "Visualization", width=320)
        elif md.kind in ("video", "clip"):
            if md.file_id:                                  # uploaded file → inline player
                data = svc.media_bytes(md)
                if data:
                    cols[0].caption(md.title or "Uploaded video")
                    cols[0].video(data)
                else:
                    cols[0].caption(md.title or "Uploaded video")
            elif md.url:
                cols[0].markdown(f"[{_html.escape(md.title or 'Video')}]({md.url})")
        if self._can_edit and cols[1].button("Delete", key=f"pmed_del_{md.id}"):
            svc.delete_media(shell.user, md.id); st.rerun()

    def _player_reports(self, svc, member) -> None:
        """Portable club-player dashboard export."""
        stats = svc.player_dashboard(member.team_id, member.id)
        rows = ["Metric,Value", *[f"{key.replace('_', ' ').title()},{value}"
                                    for key, value in stats.items() if key != "pass_completion"]]
        if stats["pass_completion"] is not None:
            rows.append(f"Pass completion,{stats['pass_completion']}%")
        st.caption("Player performance summary. Visual evidence remains available in Media.")
        st.download_button("Download player performance summary", "\n".join(rows),
                           file_name=f"{(member.player_name or 'player').replace(' ', '_')}_summary.csv",
                           mime="text/csv", key=f"preport_{member.id}")

    def _player_overview(self, shell, svc, member) -> None:
        """The premium player dashboard (same look as the Players page): a profile
        dossier grid + performance analytics from the team's linked matches."""
        stats = svc.player_dashboard(member.team_id, member.id)
        charts = len(svc.player_portfolio(member.team_id, member.id))

        # ---- profile dossier grid (icon + label + value tiles) ----
        C.render_dossier_label("Player profile", icon=icon("user", 13))
        age = _age_from_dob(member.date_of_birth)
        _v = lambda x: "—" if x in (None, "", []) else str(x)      # noqa: E731
        tiles = [
            C.dossier_stat_html("Age", _v(age), icon=icon("calendar", 15)),
            C.dossier_stat_html("Foot", (member.preferred_foot or "").title() or "—", icon=icon("ball", 15)),
            C.dossier_stat_html("Height", f"{member.height_cm}" if member.height_cm else "—",
                                sub="cm" if member.height_cm else "", icon=icon("line-straight", 15)),
            C.dossier_stat_html("Weight", f"{member.weight_kg}" if member.weight_kg else "—",
                                sub="kg" if member.weight_kg else "", icon=icon("layers", 15)),
            C.dossier_stat_html("Position", _html.escape(member.role or "—"), icon=icon("map-pin", 15)),
            C.dossier_stat_html("Nationality", _html.escape(member.nationality or "—"), icon=icon("flag", 15)),
            C.dossier_stat_html("Shirt", f"#{member.shirt_number}" if member.shirt_number else "—",
                                icon=icon("jersey", 15)),
            C.dossier_stat_html("Contract", _v(member.contract_end), icon=icon("book", 15)),
        ]
        C.render_dossier_grid(tiles)

        C.render_dossier_label("Performance dashboard", icon=icon("analysis", 13))
        top = st.columns(4)
        top[0].metric("Appearances", stats["appearances"])
        top[1].metric("Minutes", stats["minutes"] if stats["appearances"] else "—")
        top[2].metric("Goals", stats["goals"])
        top[3].metric("Assists", stats["assists"])
        performance = st.columns(4)
        performance[0].metric("Passes", stats["passes"])
        performance[1].metric("Pass completion", f"{stats['pass_completion']}%" if stats["pass_completion"] is not None else "—")
        performance[2].metric("Shots", stats["shots"])
        performance[3].metric("Events", stats["events"])
        st.caption(f"{stats['team_matches']} team match(es) recorded · {stats['linked_matches']} linked to event data · {charts} saved chart(s)")
        if stats["linked_matches"]:
            st.caption("Minutes are calculated from the latest recorded event minute in each linked match.")
        if not stats["linked_matches"]:
            C.render_alert("Link match event data in the Matches tab to populate appearances and performance metrics.", "info")
        st.markdown("#### Player snapshot")
        snapshot = st.columns(4)
        snapshot[0].markdown(f"**Number**  \n{_html.escape('#' + member.shirt_number) if member.shirt_number else '—'}")
        snapshot[1].markdown(f"**Position**  \n{_html.escape(member.role or '—')}")
        snapshot[2].markdown(f"**Availability**  \n{_html.escape((member.availability or 'available').title())}")
        snapshot[3].markdown(f"**Contract end**  \n{_html.escape(member.contract_end or '—')}")
        if not self._can_edit:
            details = [
                ("Operational ID", member.operational_id), ("Secondary position", member.secondary_role),
                ("Date of birth", member.date_of_birth), ("Nationality", member.nationality),
                ("Preferred foot", member.preferred_foot),
                ("Height", f"{member.height_cm} cm" if member.height_cm else ""),
                ("Weight", f"{member.weight_kg} kg" if member.weight_kg else ""),
                ("Joined", member.joined_date), ("Contract end", member.contract_end),
                ("Phone", member.phone), ("Email", member.email), ("Emergency contact", member.emergency_contact),
                ("Agent / representative", member.agent),
            ]
            for label, value in details:
                if value:
                    st.markdown(f"**{label}:** {_html.escape(str(value))}")
            if member.notes:
                st.markdown("**Notes**")
                st.write(member.notes)

    def _edit_player_profile(self, shell, svc, member) -> None:
        """The editing form is intentionally separate from the performance dashboard."""
        st.markdown("**Player photo**")
        photo = svc.member_photo_bytes(member.id)
        if photo:
            st.image(photo, width=96)
        upload = st.file_uploader("Upload player photo", type=["png", "jpg", "jpeg", "webp"],
                                  key=f"po_photo_{member.id}")
        if upload is not None and st.button("Save player photo", key=f"po_photo_save_{member.id}"):
            try:
                svc.set_member_photo(shell.user, member.id, upload.getvalue(), upload.type or "image/png")
                st.toast("Player photo saved")
                st.rerun()
            except ValueError as exc:
                st.warning(str(exc))
        c = st.columns(4)
        name = c[0].text_input("Player name", value=member.player_name, key=f"po_name_{member.id}")
        number = c[1].text_input("Squad number", value=member.shirt_number, key=f"po_no_{member.id}")
        role = c[2].text_input("Primary position", value=member.role, key=f"po_role_{member.id}")
        secondary = c[3].text_input("Secondary position", value=member.secondary_role, key=f"po_role2_{member.id}")
        c2 = st.columns(4)
        dob = c2[0].text_input("Date of birth", value=member.date_of_birth, placeholder="YYYY-MM-DD", key=f"po_dob_{member.id}")
        nationality = c2[1].text_input("Nationality", value=member.nationality, key=f"po_nat_{member.id}")
        foots = ["", "Right", "Left", "Both"]
        foot = c2[2].selectbox("Preferred foot", foots, index=foots.index(member.preferred_foot) if member.preferred_foot in foots else 0, key=f"po_foot_{member.id}")
        availability_options = ["available", "injured", "suspended", "unavailable"]
        availability = c2[3].selectbox("Availability", availability_options,
                                       index=availability_options.index(member.availability) if member.availability in availability_options else 0,
                                       key=f"po_avail_{member.id}")
        c3 = st.columns(4)
        height = c3[0].number_input("Height (cm)", 0, 250, int(member.height_cm or 0), key=f"po_height_{member.id}")
        weight = c3[1].number_input("Weight (kg)", 0, 200, int(member.weight_kg or 0), key=f"po_weight_{member.id}")
        joined = c3[2].text_input("Joined date", value=member.joined_date, placeholder="YYYY-MM-DD", key=f"po_joined_{member.id}")
        contract = c3[3].text_input("Contract end", value=member.contract_end, placeholder="YYYY-MM-DD", key=f"po_contract_{member.id}")
        c4 = st.columns(3)
        phone = c4[0].text_input("Phone", value=member.phone, key=f"po_phone_{member.id}")
        email = c4[1].text_input("Email", value=member.email, key=f"po_email_{member.id}")
        agent = c4[2].text_input("Agent / representative", value=member.agent, key=f"po_agent_{member.id}")
        emergency = st.text_input("Emergency contact", value=member.emergency_contact, key=f"po_emergency_{member.id}")
        notes = st.text_area("Player notes", value=member.notes, key=f"po_notes_{member.id}", height=100)
        if st.button("Save player profile", type="primary", key=f"po_save_{member.id}"):
            svc.update_member(shell.user, member.id, player_name=name, shirt_number=number, role=role,
                              secondary_role=secondary, date_of_birth=dob, nationality=nationality,
                              preferred_foot=foot, availability=availability, height_cm=(height or None),
                              weight_kg=(weight or None), joined_date=joined, contract_end=contract,
                              phone=phone, email=email, emergency_contact=emergency, agent=agent, notes=notes)
            st.toast("Player profile saved")
            st.rerun()

    def _info(self, shell, svc, t) -> None:
        if not self._can_edit:
            st.write(t.info or "_No info yet._")
            return
        c = st.columns([2, 2, 2])
        comp = c[0].text_input("Competition", value=t.competition, key=f"tm_comp_{t.id}")
        season = c[1].text_input("Season", value=t.season, key=f"tm_season_{t.id}")
        age = c[2].selectbox("Age group", [""] + list(_ident.AGE_GROUPS),
                             index=([""] + list(_ident.AGE_GROUPS)).index(t.age_group)
                             if t.age_group in _ident.AGE_GROUPS else 0,
                             format_func=lambda a: a or "—", key=f"tm_age_{t.id}",
                             disabled=(t.kind != "academy"))
        info = st.text_area("Team info / notes", value=t.info, key=f"tm_info_{t.id}", height=120)
        b = st.columns([1, 1, 3])
        if b[0].button("Save", type="primary", key=f"tm_save_{t.id}"):
            svc.update_team(shell.user, t.id, competition=comp, season=season,
                            age_group=(age if t.kind == "academy" else ""), info=info)
            st.rerun()
        if b[1].button("Delete team", key=f"tm_del_{t.id}"):
            svc.delete_team(shell.user, t.id)
            st.session_state.pop(_SEL, None); st.rerun()
        crest = st.file_uploader("Team / club crest", type=["png", "jpg", "jpeg", "webp"],
                                 key=f"tm_crest_{t.id}")
        if crest is not None and st.button("Upload crest", key=f"tm_crestbtn_{t.id}"):
            svc.set_crest(shell.user, t.id, crest.getvalue(), crest.type or "image/png")
            st.rerun()
