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
from fap.ui.page import Page, page_registry

_KINDS = {"club": "Club / First Team", "academy": "Academy"}
_SEL = "_teams_selected"


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
            C.render_empty_state("No teams yet", "Create your first club or academy squad above.",
                                 icon_name="teams")
            return
        st.caption(f"{len(summaries)} team(s)")
        for s in summaries:
            cols = st.columns([5, 1], vertical_alignment="center")
            tag = _KINDS.get(s["kind"], s["kind"]) + (f" · {s['age_group']}" if s["age_group"] else "")
            meta = " · ".join(x for x in (tag, s["competition"], s["season"],
                                          f"{s['members']} player(s)") if x)
            cols[0].markdown(f"**{_html.escape(s['name'])}**<br>"
                             f"<span style='color:var(--fap-text-muted)'>{_html.escape(meta)}</span>",
                             unsafe_allow_html=True)
            if cols[1].button("Open", key=f"tm_open_{s['id']}", use_container_width=True):
                st.session_state[_SEL] = s["id"]
                st.rerun()

    # ---------------------------------------------------------------- detail
    def _team_detail(self, shell, svc, team_id) -> None:
        t = svc.get_team(team_id)
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

        tabs = st.tabs(["Roster", "Info & crest"])
        with tabs[0]:
            self._roster(shell, svc, t)
        with tabs[1]:
            self._info(shell, svc, t)

    def _roster(self, shell, svc, t) -> None:
        members = svc.list_members(t.id)
        if self._can_edit:
            with st.expander("Add player to roster", expanded=not members):
                c = st.columns([3, 2, 1, 2])
                nm = c[0].text_input("Player name", key=f"tm_mn_{t.id}")
                oid = c[1].text_input("Operational id", key=f"tm_moid_{t.id}",
                                      placeholder="ACD-… / CLB-… / SCT-…")
                sh = c[2].text_input("No.", key=f"tm_msh_{t.id}")
                role = c[3].text_input("Role/position", key=f"tm_mrole_{t.id}")
                if st.button("Add to roster", key=f"tm_madd_{t.id}"):
                    try:
                        svc.add_member(shell.user, t.id, player_name=nm, operational_id=oid,
                                       shirt_number=sh, role=role)
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
                st.caption("Later phases add a picker over existing scouting / first-team players; "
                           "for now enter the player and their unique operational id.")
        if not members:
            C.render_empty_state("Empty roster", "Add players above.", icon_name="players")
            return
        st.caption(f"{len(members)} player(s)")
        for m in members:
            cols = st.columns([5, 1], vertical_alignment="center")
            bits = " · ".join(x for x in (m.operational_id, m.role,
                                          (f"#{m.shirt_number}" if m.shirt_number else "")) if x)
            cols[0].markdown(f"**{_html.escape(m.player_name or m.operational_id)}**"
                             + (f" &nbsp; <span style='color:var(--fap-text-muted)'>{_html.escape(bits)}"
                                f"</span>" if bits else ""), unsafe_allow_html=True)
            if self._can_edit and cols[1].button("Remove", key=f"tm_mrm_{m.id}",
                                                  use_container_width=True):
                svc.remove_member(shell.user, m.id); st.rerun()

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
