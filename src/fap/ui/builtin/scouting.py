"""Scouting - the professional recruitment workspace (Phase 8.0).

A thin view over ``ScoutingService``: no business logic here. Capability-gated
through the platform PermissionService; reports open in the EXISTING Report
Studio (the page just navigates to it by report id). Only navigation/selection
lives in session_state - every object is persisted by the service.
"""
from __future__ import annotations

import streamlit as st

from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.identity.capabilities import Capability
from fap.identity.roles import Role
from fap.scouting.models import PLAYER_STATUSES, PRIORITIES
from fap.ui.page import Page, page_registry

SEL = "_scout_player_id"
OPEN_REPORT = "_open_report_id"        # the Report Studio's navigation key (reused)


@page_registry.register
class ScoutingPage(Page):
    info = PluginInfo(id="scouting", name="Scouting", category="page")
    section = "Squad"
    icon = "scouting"
    order = 20
    min_role = Role.READ_ONLY          # view gated by capability below

    def render(self, shell) -> None:
        svc = getattr(shell.platform, "scouting", None) if shell.platform else None
        perms = getattr(shell.platform, "permissions", None) if shell.platform else None
        if svc is None or perms is None:
            st.info("Scouting platform unavailable.")
            return
        if not perms.can(shell.user, str(Capability.VIEW_SCOUTING)):
            st.warning("You do not have permission to view scouting.")
            return
        self._can_edit = perms.can(shell.user, str(Capability.EDIT_SCOUTING))
        self._can_report = perms.can(shell.user, str(Capability.CREATE_REPORT))

        st.title("Scouting")
        selected = st.session_state.get(SEL)
        if selected and svc.get_player(selected):
            self._player_detail(shell, svc, selected)
            return

        tabs = st.tabs(["Dashboard", "Players", "Watchlists", "Archive"])
        with tabs[0]:
            self._dashboard(shell, svc)
        with tabs[1]:
            self._players(shell, svc)
        with tabs[2]:
            self._watchlists(shell, svc)
        with tabs[3]:
            self._archive(shell, svc)

    # ------------------------------------------------------------ dashboard
    def _dashboard(self, shell, svc) -> None:
        d = svc.dashboard(shell.user)
        c = st.columns(4)
        c[0].metric("Players", d["counts"]["active"])
        c[1].metric("Archived", d["counts"]["archived"])
        c[2].metric("Watchlists", len(d["watchlists"]))
        c[3].metric("Reports", len(d["latest_reports"]))
        cols = st.columns(2)
        with cols[0]:
            self._player_strip(svc, "Recently updated", d["recent"])
            self._player_strip(svc, "Top rated", d["top_rated"])
            self._player_strip(svc, "Favorites", d["favorites"])
        with cols[1]:
            self._player_strip(svc, "Recently viewed", d["recently_viewed"])
            self._player_strip(svc, "Contracts expiring", d["contracts_expiring"])
            st.markdown("**Latest reports**")
            for link in d["latest_reports"]:
                st.caption(f"• {link.title}")

    def _player_strip(self, svc, title, players) -> None:
        st.markdown(f"**{title}**")
        if not players:
            st.caption("—")
        for p in players:
            if st.button(f"{p.name} · {p.position or '—'} · {p.club or '—'}",
                         key=f"strip_{title}_{p.id}", use_container_width=True):
                st.session_state[SEL] = p.id
                st.rerun()

    # ------------------------------------------------------------ players
    def _players(self, shell, svc) -> None:
        c = st.columns([3, 1, 1, 1])
        query = c[0].text_input("Search players", key="scout_q")
        pos = c[1].text_input("Position", key="scout_pos")
        min_rating = c[2].number_input("Min rating", 0.0, 10.0, 0.0, 0.5, key="scout_minr")
        fav = c[3].checkbox("Favorites", key="scout_fav")
        filters = {}
        if pos.strip():
            filters["position"] = pos.strip()
        if min_rating > 0:
            filters["min_rating"] = min_rating
        players = svc.search(shell.user, query=query, filters=filters, favorite=fav or None)
        st.caption(f"{len(players)} player(s)")
        for p in players:
            cols = st.columns([4, 1])
            label = f"**{p.name}** · {p.position or '—'} · {p.club or '—'}" + (
                f" · ★{p.internal_rating}" if p.internal_rating else "")
            cols[0].markdown(label)
            if cols[1].button("Open", key=f"open_{p.id}"):
                st.session_state[SEL] = p.id
                st.rerun()

        if self._can_edit:
            st.divider()
            with st.expander("➕ Add player"):
                name = st.text_input("Name", key="np_name")
                cc = st.columns(3)
                club = cc[0].text_input("Club", key="np_club")
                league = cc[1].text_input("League", key="np_league")
                position = cc[2].text_input("Position", key="np_pos")
                if st.button("Create player", type="primary", key="np_create") and name.strip():
                    p = svc.create_player(shell.user, name.strip(), club=club, league=league,
                                          position=position, workspace_id=shell.workspace_id)
                    st.session_state[SEL] = p.id
                    st.rerun()

    # ------------------------------------------------------------ player detail
    def _player_detail(self, shell, svc, player_id) -> None:
        p = svc.view_player(shell.user, player_id)
        if p is None:
            st.session_state.pop(SEL, None)
            st.rerun()
        top = st.columns([1, 5, 1])
        if top[0].button("← Back"):
            st.session_state.pop(SEL, None)
            st.rerun()
        top[1].subheader(f"{p.name}  ·  {p.position or '—'}  ·  {p.club or '—'}")
        if self._can_edit and top[2].button("★ Favorite" if not p.favorite else "★ Unfavorite"):
            svc.set_favorite(shell.user, p.id, not p.favorite)
            st.rerun()

        if p.profile_image_id:
            data = svc.image_bytes(p.profile_image_id)
            if data:
                st.image(data, width=140)

        tabs = st.tabs(["Profile", "Notes", "Images", "Videos", "Attachments", "Reports"])
        with tabs[0]:
            self._profile(shell, svc, p)
        with tabs[1]:
            self._notes(shell, svc, p)
        with tabs[2]:
            self._images(shell, svc, p)
        with tabs[3]:
            self._videos(shell, svc, p)
        with tabs[4]:
            self._attachments(shell, svc, p)
        with tabs[5]:
            self._reports(shell, svc, p)

    def _profile(self, shell, svc, p) -> None:
        st.write(f"**Country** {p.country or '—'} · **Age** {p.age or '—'} · **Foot** {p.foot or '—'} "
                 f"· **Height** {p.height or '—'} · **Contract** {p.contract_until or '—'}")
        st.write(f"**Rating** {p.internal_rating or '—'} · **Value** {p.market_value or '—'} "
                 f"· **Agent** {p.agent or '—'} · **Tags** {', '.join(p.tags) or '—'}")
        if not self._can_edit:
            return
        with st.expander("Edit profile"):
            cc = st.columns(3)
            club = cc[0].text_input("Club", value=p.club, key="ep_club")
            league = cc[1].text_input("League", value=p.league, key="ep_league")
            country = cc[2].text_input("Country", value=p.country, key="ep_country")
            age = cc[0].number_input("Age", 0, 60, p.age or 0, key="ep_age")
            rating = cc[1].number_input("Rating", 0.0, 10.0, float(p.internal_rating or 0), 0.1, key="ep_rating")
            status = cc[2].selectbox("Status", list(PLAYER_STATUSES),
                                     index=(list(PLAYER_STATUSES).index(p.status) if p.status in PLAYER_STATUSES else 0),
                                     key="ep_status")
            priority = cc[0].selectbox("Priority", list(PRIORITIES),
                                       index=list(PRIORITIES).index(p.priority) if p.priority in PRIORITIES else 0,
                                       key="ep_priority")
            contract = cc[1].text_input("Contract until", value=p.contract_until, key="ep_contract")
            if st.button("Save", type="primary", key="ep_save"):
                svc.update_player(shell.user, p.id, club=club, league=league, country=country,
                                  age=int(age) or None, internal_rating=rating or None, status=status,
                                  priority=priority, contract_until=contract)
                st.rerun()
        col = st.columns(3)
        if col[0].button("Archive" if not p.archived else "Restore", key="p_archive"):
            svc.archive_player(shell.user, p.id, not p.archived); st.rerun()
        if col[1].button("Duplicate", key="p_dup"):
            dup = svc.duplicate_player(shell.user, p.id); st.session_state[SEL] = dup.id; st.rerun()
        if col[2].button("Delete", key="p_del"):
            svc.delete_player(shell.user, p.id); st.session_state.pop(SEL, None); st.rerun()

    def _notes(self, shell, svc, p) -> None:
        for n in svc.list_notes(p.id):
            with st.container(border=True):
                st.markdown(("📌 " if n.pinned else "") + (n.body or "_empty_"))
                st.caption(f"{n.author} · {n.updated_at}")
                if self._can_edit and st.button("Delete", key=f"dn_{n.id}"):
                    svc.delete_note(shell.user, n.id); st.rerun()
        if self._can_edit:
            body = st.text_area("New note (markdown)", key="new_note")
            pinned = st.checkbox("Pin", key="new_note_pin")
            if st.button("Add note", type="primary", key="add_note") and body.strip():
                svc.add_note(shell.user, p.id, body, pinned=pinned); st.rerun()

    def _images(self, shell, svc, p) -> None:
        media = svc.list_media(p.id)
        cols = st.columns(4)
        for i, m in enumerate(media):
            data = svc.image_bytes(m.image_id)
            if data:
                cols[i % 4].image(data, caption=f"{m.kind} · {m.caption}", use_container_width=True)
        if self._can_edit:
            up = st.file_uploader("Add image", type=["png", "jpg", "jpeg", "webp", "svg"], key="img_up")
            kind = st.selectbox("Kind", ["scouting", "profile", "medical", "training", "match"], key="img_kind")
            if up is not None and st.button("Upload image", key="img_btn"):
                svc.add_image(shell.user, p.id, up.getvalue(), up.type or "image/png", kind=kind,
                              caption=up.name)
                st.rerun()

    def _videos(self, shell, svc, p) -> None:
        for v in svc.list_videos(p.id):
            with st.container(border=True):
                if v.kind == "external":
                    st.markdown(f"🎬 **{v.title}** · {v.provider}  \n{v.url}")
                else:
                    st.markdown(f"🎬 **{v.title}** · uploaded ({v.size_bytes // 1024} KB)")
                    data = svc.video_bytes(v.id)
                    if data and v.mime.startswith("video/"):
                        st.video(data)
                if self._can_edit and st.button("Delete", key=f"dv_{v.id}"):
                    svc.delete_video(shell.user, v.id); st.rerun()
        if self._can_edit:
            st.markdown("**Add external video** (YouTube / Vimeo / Hudl / Wyscout / SkillCorner)")
            url = st.text_input("Video URL", key="vid_url")
            if st.button("Add link", key="vid_link") and url.strip():
                svc.add_external_video(shell.user, p.id, url.strip()); st.rerun()
            up = st.file_uploader("Or upload video", type=["mp4", "mov", "mkv", "webm", "avi"], key="vid_up")
            if up is not None and st.button("Upload video", key="vid_btn"):
                svc.add_uploaded_video(shell.user, p.id, up.getvalue(), up.name, up.type or "video/mp4")
                st.rerun()

    def _attachments(self, shell, svc, p) -> None:
        for a in svc.list_attachments(p.id):
            cols = st.columns([4, 1, 1])
            cols[0].write(f"📎 {a.filename} · {a.size_bytes // 1024} KB")
            data = svc.attachment_bytes(a.id)
            if data:
                cols[1].download_button("Download", data, file_name=a.filename, key=f"da_{a.id}")
            if self._can_edit and cols[2].button("Delete", key=f"xa_{a.id}"):
                svc.delete_attachment(shell.user, a.id); st.rerun()
        if self._can_edit:
            up = st.file_uploader("Add attachment", key="att_up",
                                  type=["pdf", "docx", "pptx", "csv", "xlsx", "zip", "png", "jpg"])
            if up is not None and st.button("Upload attachment", key="att_btn"):
                svc.add_attachment(shell.user, p.id, up.getvalue(), up.name, up.type or "")
                st.rerun()

    def _reports(self, shell, svc, p) -> None:
        for link in svc.list_reports(p.id):
            cols = st.columns([4, 1])
            cols[0].write(f"📄 {link.title} · {link.created_at}")
            if cols[1].button("Open in Studio", key=f"open_rep_{link.id}"):
                st.session_state[OPEN_REPORT] = link.report_id
                shell.goto("report_editor")           # reuse the existing Report Studio
        if self._can_report:
            st.divider()
            if st.button("➕ Generate scouting report", type="primary", key="gen_rep"):
                link = svc.create_report(shell.user, p.id)
                st.session_state[OPEN_REPORT] = link.report_id
                shell.goto("report_editor")           # open the auto-generated report in Studio

    # ------------------------------------------------------------ watchlists
    def _watchlists(self, shell, svc) -> None:
        for w in svc.list_watchlists():
            with st.container(border=True):
                st.markdown(f"**{w.name}** · {w.member_count} players")
                for pl in svc.watchlist_players(w.id):
                    cols = st.columns([4, 1])
                    cols[0].write(f"• {pl.name} · {pl.position or '—'}")
                    if cols[1].button("Open", key=f"wlp_{w.id}_{pl.id}"):
                        st.session_state[SEL] = pl.id; st.rerun()
        if self._can_edit:
            name = st.text_input("New watchlist", key="wl_name")
            if st.button("Create watchlist", key="wl_create") and name.strip():
                svc.create_watchlist(shell.user, name.strip()); st.rerun()

    # ------------------------------------------------------------ archive
    def _archive(self, shell, svc) -> None:
        st.caption("Archived players (soft-deleted). Restore keeps every asset.")
        for p in svc.archived_players(shell.user):
            cols = st.columns([4, 1])
            cols[0].write(f"• {p.name} · {p.club or '—'}")
            if self._can_edit and cols[1].button("Restore", key=f"restore_{p.id}"):
                svc.restore_player(shell.user, p.id); st.rerun()
