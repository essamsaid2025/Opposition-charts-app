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
from fap.theme import components as C
from fap.theme import icon
from fap.ui.page import Page, page_registry

SEL = "_scout_player_id"
OPEN_REPORT = "_open_report_id"        # the Report Studio's navigation key (reused)
# Uploaded videos are streamed to the click-to-seek component as an inline base64
# data URL. Above this size we skip the interactive player and fall back to plain
# st.video (no seek) so a huge file never bloats the component payload.
_MAX_INLINE_VIDEO_BYTES = 25 * 1024 * 1024


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
        self._can_export = perms.can(shell.user, str(Capability.EXPORT_REPORT))

        C.render_section_title(
            "Scouting", eyebrow="Recruitment",
            subtitle="Track targets, watchlists and reports across your recruitment network.",
            icon_name="scouting")
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
        C.render_metric_row([
            C.metric_card_html("Players", str(d["counts"]["active"]), icon_name="scouting",
                               accent="primary", hint="active targets"),
            C.metric_card_html("Archived", str(d["counts"]["archived"]), icon_name="folder",
                               accent="info", hint="soft-deleted"),
            C.metric_card_html("Watchlists", str(len(d["watchlists"])), icon_name="star",
                               accent="warning", hint="shortlists"),
            C.metric_card_html("Reports", str(len(d["latest_reports"])), icon_name="reports",
                               accent="success", hint="latest output"),
        ])
        cols = st.columns(2)
        with cols[0]:
            self._player_strip(svc, "Recently updated", d["recent"])
            self._player_strip(svc, "Top rated", d["top_rated"])
            self._player_strip(svc, "Favorites", d["favorites"])
        with cols[1]:
            self._player_strip(svc, "Recently viewed", d["recently_viewed"])
            self._player_strip(svc, "Contracts expiring", d["contracts_expiring"])
            st.markdown("**Latest reports**")
            if not d["latest_reports"]:
                st.caption("No reports yet.")
            for link in d["latest_reports"]:
                st.markdown(f"{icon('reports', 13)} {link.title}", unsafe_allow_html=True)

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
        if not players:
            C.render_empty_state("No players found", "Adjust your search or filters, or add a "
                                 "new target below.", icon_name="scouting")
        for p in players:
            cols = st.columns([4, 1], vertical_alignment="center")
            rating = (f" &nbsp; {icon('star', 13)} <b>{p.internal_rating}</b>"
                      if p.internal_rating else "")
            fav_mark = (icon('star', 13) + " ") if getattr(p, "favorite", False) else ""
            cols[0].markdown(
                f"{fav_mark}<b>{p.name}</b> &middot; {p.position or '—'} &middot; "
                f"{p.club or '—'}{rating}", unsafe_allow_html=True)
            if cols[1].button("Open", key=f"open_{p.id}", use_container_width=True):
                st.session_state[SEL] = p.id
                st.rerun()

        if self._can_edit:
            st.divider()
            with st.expander("Add player"):
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
        top = st.columns([1, 5, 1], vertical_alignment="center")
        if top[0].button("Back", key="scout_back", use_container_width=True):
            st.session_state.pop(SEL, None)
            st.rerun()
        top[1].subheader(f"{p.name}  ·  {p.position or '—'}  ·  {p.club or '—'}")
        if self._can_edit and top[2].button("Favorite" if not p.favorite else "Unfavorite",
                                            key="scout_fav_btn", use_container_width=True,
                                            type="primary" if not p.favorite else "secondary"):
            svc.set_favorite(shell.user, p.id, not p.favorite)
            st.rerun()

        if p.profile_image_id:
            data = svc.image_bytes(p.profile_image_id)
            if data:
                st.image(data, width=140)

        tabs = st.tabs(["Profile", "Visualization", "Notes", "Images", "Videos",
                        "Attachments", "Reports"])
        with tabs[0]:
            self._profile(shell, svc, p)
        with tabs[1]:
            self._tab_visualization(shell, svc, p)
        with tabs[2]:
            self._notes(shell, svc, p)
        with tabs[3]:
            self._images(shell, svc, p)
        with tabs[4]:
            self._videos(shell, svc, p)
        with tabs[5]:
            self._attachments(shell, svc, p)
        with tabs[6]:
            self._reports(shell, svc, p)

    def _tab_visualization(self, shell, svc, p) -> None:
        """Visualization workspace, routed by dataset CAPABILITY:
        - a player-scouting dataset -> the Player Scouting Visualization workspace
          (metric charts + pizza, no event data required);
        - an event dataset -> the existing event visualization engine.
        When the scout can edit, each rendered chart can be assigned (frozen) to
        the player's report."""
        def _assign(png, title, viz_id):
            svc.assign_chart(shell.user, p.id, png, title=title, viz_id=viz_id)

        on_assign = _assign if self._can_edit else None
        if svc.active_dataset_kind(shell.user) == "player_scouting":
            from fap.ui.components.scouting_viz_workspace import render_scouting_viz_workspace
            render_scouting_viz_workspace(shell, svc, p, key=f"sc_pviz_{p.id}",
                                          on_assign=on_assign)
            return
        from fap.ui.components.viz_workspace import render_visualization_workspace
        frame = svc.player_event_frame(shell.user, p.id)
        render_visualization_workspace(shell, frame=frame, player_name=p.name,
                                       key=f"sc_viz_{p.id}", on_assign=on_assign)
        if self._can_edit:
            self._assigned_charts_panel(shell, svc, p)

    def _active_analysis(self, shell, svc, p) -> None:
        """Player analysis from the ACTIVE dataset, routed by dataset CAPABILITY:
        a player-scouting dataset shows the player's metric profile; an event
        dataset shows event/match analysis. The two are never mixed, and a
        player-scouting dataset never reports 'No events found'."""
        kind = svc.active_dataset_kind(shell.user)
        if kind == "":
            with st.expander("Player analysis (active dataset)", expanded=False):
                go = C.render_empty_state(
                    "No active dataset", "Scouting analysis reads from the active dataset. Import "
                    "and choose one in the Data Hub - notes, ratings and tags stay in the scouting "
                    "database.", icon_name="datasets",
                    action_label="Open Data Hub", key=f"sc_dh_{p.id}")
                if go:
                    shell.goto("data_hub")
            return
        if kind == "player_scouting":
            self._scouting_metric_profile(shell, svc, p)
            return
        self._event_analysis(shell, svc, p)

    def _scouting_metric_profile(self, shell, svc, p) -> None:
        """Player-scouting capability: the player's metrics from the active
        player-scouting dataset (resolved by name against the Player column). No
        event lookup, and missing event data is NOT an error."""
        with st.expander("Scouting profile (active dataset)", expanded=True):
            profile = svc.active_scouting_profile(shell.user, p.id)
            if profile is None:
                C.render_alert(
                    f"{p.name} is not in the active player-scouting dataset "
                    f"(the player's name may differ in the data). Notes, ratings and tags are "
                    f"still available.", "info")
                return
            dims = profile.get("dimensions", {})
            meta = " · ".join(f"**{k.title()}** {v}" for k, v in dims.items() if v not in (None, ""))
            if meta:
                st.markdown(meta)
            scale = profile.get("value_scale")
            if scale == "normalized":
                st.caption("Metric values are percentile/rank-normalized (0-1), preserved as-is.")
            rows = [{"metric": m["name"], "unit": m["unit"],
                     "value": ("—" if m["value"] is None else m["value"])}
                    for m in profile.get("metrics", [])]
            if rows:
                st.dataframe(rows, use_container_width=True, hide_index=True)
            C.render_alert(
                "Event-level evidence (pass/shot/touch maps) is unavailable for this dataset - "
                "player-scouting data has no match events. Activate an event dataset in the Data "
                "Hub to add event analysis.", "info")

    def _event_analysis(self, shell, svc, p) -> None:
        """Event capability: match/event analysis from the active event dataset."""
        with st.expander("Match analysis (active dataset)", expanded=False):
            stats = svc.active_player_stats(shell.user, p.id)
            if not stats["events"]:
                C.render_alert(f"No events found for {p.name} in the active dataset "
                               f"(the player's name may differ in the data).", "info")
                return
            m = st.columns(2)
            m[0].metric("Events", stats["events"])
            m[1].metric("Matches", stats["matches"])
            try:
                catalog = svc.available_visualizations(shell.user)
            except Exception:
                return
            cats = sorted({v["category"] for v in catalog})
            a, b, c = st.columns([2, 2, 1])
            cat = a.selectbox("Category", cats, key=f"sc_cat_{p.id}")
            in_cat = [v for v in catalog if v["category"] == cat]
            viz = b.selectbox("Visualization", in_cat, format_func=lambda v: v["name"],
                              key=f"sc_viz_{p.id}")
            theme = c.selectbox("Theme", ["opta_light", "opta_dark"], key=f"sc_theme_{p.id}")
            if st.button("Render chart", key=f"sc_render_{p.id}"):
                png = svc.render_player_chart(shell.user, p.id, viz["id"], theme_id=theme)
                if png:
                    st.image(png, use_container_width=True)
                else:
                    st.info("This visualization could not be rendered from the current events.")

    def _profile(self, shell, svc, p) -> None:
        from fap.scouting import identity
        dn = identity.display_name_of(p)
        aliases = identity.aliases_of(p)
        st.write(f"**Recruitment** {C.badge_html(identity.status_label(p.status) or '—', 'info')} "
                 f"&nbsp; **Priority** {identity.priority_label(p.priority) or '—'}"
                 + (f" &nbsp; **Also known as** {', '.join(aliases)}" if aliases else "")
                 + (f" &nbsp; **Source** {identity.source_of(p)}" if identity.source_of(p) else ""),
                 unsafe_allow_html=True)
        st.write(f"**Country** {p.country or '—'} · **Age** {p.age or '—'} · **Foot** {p.foot or '—'} "
                 f"· **Height** {p.height or '—'} · **Contract** {p.contract_until or '—'}")
        st.write(f"**Rating** {p.internal_rating or '—'} · **Value** {p.market_value or '—'} "
                 f"· **Agent** {p.agent or '—'} · **Tags** {', '.join(p.tags) or '—'}")
        self._active_analysis(shell, svc, p)
        if not self._can_edit:
            return
        statuses = list(identity.RECRUITMENT_STATUSES)
        priorities = [""] + list(identity.RECRUITMENT_PRIORITIES)
        cur_status = identity.normalize_status(p.status)
        cur_priority = identity.normalize_priority(p.priority)
        with st.expander("Edit profile"):
            cc = st.columns(3)
            club = cc[0].text_input("Club", value=p.club, key="ep_club")
            league = cc[1].text_input("League", value=p.league, key="ep_league")
            country = cc[2].text_input("Country", value=p.country, key="ep_country")
            age = cc[0].number_input("Age", 0, 60, p.age or 0, key="ep_age")
            rating = cc[1].number_input("Rating", 0.0, 10.0, float(p.internal_rating or 0), 0.1, key="ep_rating")
            status = cc[2].selectbox("Recruitment status", statuses,
                                     index=statuses.index(cur_status) if cur_status in statuses else 0,
                                     format_func=identity.status_label, key="ep_status")
            priority = cc[0].selectbox("Priority", priorities,
                                       index=priorities.index(cur_priority) if cur_priority in priorities else 0,
                                       format_func=lambda x: identity.priority_label(x) or "—", key="ep_priority")
            contract = cc[1].text_input("Contract until", value=p.contract_until, key="ep_contract")
            display_name = cc[2].text_input("Display name", value=dn, key="ep_dn")
            alias_str = cc[0].text_input("Aliases (comma separated)", value=", ".join(aliases),
                                         key="ep_aliases")
            source = cc[1].text_input("Source", value=identity.source_of(p), key="ep_source",
                                      placeholder="e.g. Malta league export, scout obs")
            if st.button("Save", type="primary", key="ep_save"):
                svc.update_player(shell.user, p.id, club=club, league=league, country=country,
                                  age=int(age) or None, internal_rating=rating or None,
                                  contract_until=contract)
                svc.set_recruitment_status(shell.user, p.id, status)
                svc.set_priority(shell.user, p.id, priority)
                svc.set_display_name(shell.user, p.id, display_name)
                svc.set_source(shell.user, p.id, source)
                svc.set_aliases(shell.user, p.id,
                                [a.strip() for a in alias_str.split(",") if a.strip()])
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
                st.markdown((icon("pin", 13) + " " if n.pinned else "") + (n.body or "_empty_"),
                            unsafe_allow_html=True)
                st.caption(f"{n.author} · {n.updated_at}")
                if self._can_edit and st.button("Delete", key=f"dn_{n.id}"):
                    svc.delete_note(shell.user, n.id); st.rerun()
        if self._can_edit:
            body = st.text_area("New note (markdown)", key="new_note")
            pinned = st.checkbox("Pin", key="new_note_pin")
            if st.button("Add note", type="primary", key="add_note") and body.strip():
                svc.add_note(shell.user, p.id, body, pinned=pinned); st.rerun()

    def _assigned_charts_panel(self, shell, svc, p) -> None:
        """The charts pinned to this player for their report (frozen PNGs)."""
        charts = svc.list_assigned_charts(p.id)
        st.divider()
        st.markdown(f"**Assigned to report** · {len(charts)} chart(s)")
        if not charts:
            st.caption("Render a chart above and click **Assign to player report** to pin it here. "
                       "Assigned charts are embedded when you generate or download the report.")
            return
        cols = st.columns(4)
        for i, m in enumerate(charts):
            data = svc.image_bytes(m.image_id)
            with cols[i % 4]:
                if data:
                    st.image(data, caption=m.caption or "Chart", use_container_width=True)
                if st.button("Remove", key=f"unassign_{m.id}", use_container_width=True):
                    svc.unassign_chart(shell.user, m.id)
                    st.rerun()

    def _images(self, shell, svc, p) -> None:
        media = [m for m in svc.list_media(p.id) if m.kind != "report_chart"]
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
        from fap.ui.builtin import video_sync as VS
        for v in svc.list_videos(p.id):
            with st.container(border=True):
                self._video_card(shell, svc, p, v, VS)
        if self._can_edit:
            st.markdown("**Add external video** (YouTube / Vimeo / Hudl / Wyscout / SkillCorner)")
            url = st.text_input("Video URL", key="vid_url")
            if st.button("Add link", key="vid_link") and url.strip():
                svc.add_external_video(shell.user, p.id, url.strip()); st.rerun()
            up = st.file_uploader("Or upload video", type=["mp4", "mov", "mkv", "webm", "avi"], key="vid_up")
            if up is not None and st.button("Upload video", key="vid_btn"):
                svc.add_uploaded_video(shell.user, p.id, up.getvalue(), up.name, up.type or "video/mp4")
                st.rerun()

    # ---- video click-to-seek (Tier 1). Un-synced videos render EXACTLY as before ----
    def _video_card(self, shell, svc, p, v, VS) -> None:
        mode = VS.component_mode(v)                    # upload|youtube|vimeo, or None
        has_match = bool(v.match_id)
        has_offset = v.sync_offset_seconds is not None
        if mode is None:                               # source can't be seeked -> today's render
            self._video_static_today(svc, v)
            st.caption("Click-to-seek isn't available for this source — standard playback/link shown.")
        elif not has_match:                            # seekable but not linked -> IDENTICAL to today
            self._video_static_today(svc, v)
            if self._can_edit:
                self._match_linker(shell, svc, p, v)
        elif not has_offset:                           # linked, not calibrated -> mark kickoff
            self._video_calibrate(shell, svc, v, VS)
        else:                                          # fully synced -> player + event list
            self._video_seek(shell, svc, p, v, VS)
        if self._can_edit and st.button("Delete", key=f"dv_{v.id}"):
            svc.delete_video(shell.user, v.id); st.rerun()

    @staticmethod
    def _video_static_today(svc, v) -> None:
        """Byte-for-byte the pre-existing rendering (the safe fallback everywhere)."""
        if v.kind == "external":
            st.markdown(f"{icon('video', 14)} **{v.title}** · {v.provider}  \n{v.url}",
                        unsafe_allow_html=True)
        else:
            st.markdown(f"{icon('video', 14)} **{v.title}** · uploaded ({v.size_bytes // 1024} KB)",
                        unsafe_allow_html=True)
            data = svc.video_bytes(v.id)
            if data and v.mime.startswith("video/"):
                st.video(data)

    @staticmethod
    def _video_header(v) -> None:
        label = v.provider or ("uploaded" if v.kind == "upload" else "video")
        st.markdown(f"{icon('video', 14)} **{v.title}** · {label}", unsafe_allow_html=True)

    @staticmethod
    def _vs_colors() -> dict:
        return {"accent": "#E07B2B", "muted": "#8A93A2"}

    def _component_src(self, svc, v, VS):
        """(src, mime) for the component, or (None, '') when it can't be used."""
        mode = VS.component_mode(v)
        if mode == "upload":
            data = svc.video_bytes(v.id)
            if not data or len(data) > _MAX_INLINE_VIDEO_BYTES:
                return None, ""
            import base64
            mime = v.mime or "video/mp4"
            return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}", mime
        if mode == "youtube":
            return VS.youtube_id(v.url), ""
        if mode == "vimeo":
            return VS.vimeo_id(v.url), ""
        return None, ""

    def _match_linker(self, shell, svc, p, v) -> None:
        with st.expander("Link this footage to a match (enables click-to-seek)"):
            frame = svc.player_event_frame(shell.user, p.id)
            ids = []
            if frame is not None and "match_id" in frame.columns:
                ids = sorted({str(m).strip() for m in frame["match_id"] if str(m).strip()})
            options = ["(choose)"] + ids
            chosen = st.selectbox("Match from active dataset", options, key=f"vm_sel_{v.id}")
            manual = st.text_input("…or type a match id", key=f"vm_txt_{v.id}")
            target = manual.strip() or ("" if chosen == "(choose)" else chosen)
            if st.button("Link match", key=f"vm_btn_{v.id}") and target:
                svc.set_video_sync(shell.user, v.id, target, None)   # calibrate next
                st.rerun()

    def _video_calibrate(self, shell, svc, v, VS) -> None:
        self._video_header(v)
        src, mime = self._component_src(svc, v, VS)
        if not src:
            self._video_static_today(svc, v)
            st.caption("This file is too large for the interactive player — calibration unavailable.")
            self._unlink_button(shell, svc, v)
            return
        rendered, intent = VS.video_sync(mode=VS.component_mode(v), src=src, mime=mime,
                                         calibrate=True, key=f"vs_{v.id}", colors=self._vs_colors())
        if not rendered:
            self._video_static_today(svc, v)
            st.caption("Interactive player unavailable — standard playback shown.")
            return
        st.caption(f"Linked to match **{v.match_id}**. Scrub to kickoff, then click "
                   f"**Mark kickoff** in the player.")
        self._unlink_button(shell, svc, v)
        if intent and self._can_edit and intent.get("nonce"):
            if st.session_state.get(f"vs_mark_{v.id}") != intent["nonce"]:
                st.session_state[f"vs_mark_{v.id}"] = intent["nonce"]
                svc.set_video_sync(shell.user, v.id, v.match_id, float(intent["time"]))
                st.toast(f"Kickoff marked at {intent['time']:.1f}s")
                st.rerun()

    def _video_seek(self, shell, svc, p, v, VS) -> None:
        self._video_header(v)
        src, mime = self._component_src(svc, v, VS)
        if not src:
            self._video_static_today(svc, v)
            st.caption("This file is too large for the interactive player — standard playback shown.")
            return
        seek_key = f"vs_seek_{v.id}"
        seek = st.session_state.get(seek_key) or {}
        rendered, _ = VS.video_sync(mode=VS.component_mode(v), src=src, mime=mime,
                                    seek_to=seek.get("time"), seek_nonce=seek.get("nonce", ""),
                                    key=f"vs_{v.id}", colors=self._vs_colors())
        if not rendered:
            self._video_static_today(svc, v)
            st.caption("Interactive player unavailable — standard playback shown.")
            return
        st.caption(f"Synced to match **{v.match_id}** (kickoff at "
                   f"{float(v.sync_offset_seconds):.1f}s). Click an event to jump the video there.")
        if self._can_edit:
            c1, c2 = st.columns(2)
            if c1.button("Recalibrate kickoff", key=f"vs_recal_{v.id}", use_container_width=True):
                svc.set_video_sync(shell.user, v.id, v.match_id, None); st.rerun()
            if c2.button("Unlink match", key=f"vs_unlink_{v.id}", use_container_width=True):
                svc.set_video_sync(shell.user, v.id, "", None)
                st.session_state.pop(seek_key, None); st.rerun()
        self._event_seek_list(shell, svc, p, v, seek_key, VS)

    def _unlink_button(self, shell, svc, v) -> None:
        if self._can_edit and st.button("Unlink match", key=f"vs_ul_{v.id}"):
            svc.set_video_sync(shell.user, v.id, "", None); st.rerun()

    def _event_seek_list(self, shell, svc, p, v, seek_key, VS) -> None:
        import uuid as _uuid
        import pandas as pd
        frame = svc.player_event_frame(shell.user, p.id)
        if frame is None or "match_id" not in frame.columns:
            C.render_alert("No active dataset events to sync to — activate this player's match "
                           "dataset in the Data Hub.", "info")
            return
        ev = frame[frame["match_id"].astype(str).str.strip() == str(v.match_id)].copy()
        if ev.empty:
            C.render_alert(f"No events for match {v.match_id} for this player in the active "
                           "dataset.", "info")
            return
        ev["_m"] = pd.to_numeric(ev.get("minute", 0), errors="coerce").fillna(0).astype(int)
        ev["_s"] = pd.to_numeric(ev.get("second", 0), errors="coerce").fillna(0).astype(int)
        ev = ev.sort_values(["_m", "_s"])
        types = sorted({str(t) for t in ev.get("event_type", pd.Series(dtype=str)) if str(t).strip()})
        pick = st.multiselect("Event types", types, default=types, key=f"vs_evt_{v.id}")
        if pick:
            ev = ev[ev["event_type"].astype(str).isin(pick)]
        st.caption(f"{len(ev)} event(s) — click to seek:")
        shown, ncol = ev.head(60), 3
        cols = st.columns(ncol)
        for i, (_, row) in enumerate(shown.iterrows()):
            m, s = int(row["_m"]), int(row["_s"])
            label = f"{m:02d}:{s:02d} · {str(row.get('event_type', 'event'))}"
            if cols[i % ncol].button(label, key=f"vs_ev_{v.id}_{i}", use_container_width=True):
                t = VS.event_video_time(v.sync_offset_seconds, m, s)
                st.session_state[seek_key] = {"time": t, "nonce": _uuid.uuid4().hex}
                st.rerun()
        if len(ev) > 60:
            st.caption(f"Showing the first 60 of {len(ev)} — narrow by event type above.")

    def _attachments(self, shell, svc, p) -> None:
        for a in svc.list_attachments(p.id):
            cols = st.columns([4, 1, 1])
            cols[0].markdown(f"{icon('folder', 14)} {a.filename} · {a.size_bytes // 1024} KB",
                             unsafe_allow_html=True)
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
        n_charts = len(svc.list_assigned_charts(p.id))
        st.caption(f"{icon('grid', 13)} {n_charts} chart(s) assigned to this player — new "
                   f"reports embed them automatically; use **Add charts** to add them to an "
                   f"existing report.")
        links = svc.list_reports(p.id)
        if not links:
            C.render_empty_state("No reports yet", "Generate a scouting report — assigned charts "
                                 "are included and it opens in Report Studio.", icon_name="reports")
        for link in links:
            cols = st.columns([3, 1, 1, 1], vertical_alignment="center")
            cols[0].markdown(f"{icon('reports', 14)} {link.title} · {link.created_at}",
                             unsafe_allow_html=True)
            if cols[1].button("Open", key=f"open_rep_{link.id}", use_container_width=True):
                st.session_state[OPEN_REPORT] = link.report_id
                shell.goto("report_editor")           # reuse the existing Report Studio
            if self._can_report and cols[2].button("Add charts", key=f"addc_{link.id}",
                                                    use_container_width=True):
                added = svc.add_charts_to_report(shell.user, link.report_id, p.id)
                st.toast(f"Added {added} chart(s) to the report" if added
                         else "No assigned charts to add")
                st.rerun()
            if self._can_export:
                self._download_report(shell, svc, link)
        if self._can_report:
            st.divider()
            if st.button("Generate scouting report", type="primary", key="gen_rep",
                         use_container_width=True):
                link = svc.create_report(shell.user, p.id)
                st.session_state[OPEN_REPORT] = link.report_id
                shell.goto("report_editor")           # open the auto-generated report in Studio

    def _download_report(self, shell, svc, link) -> None:
        """Render a linked report to a file and offer it for download (charts
        embedded by the reports engine). Uses the existing export pipeline."""
        formats = svc.report_formats() or ["html"]
        pick_key = f"fmt_{link.id}"
        fmt = st.session_state.get(pick_key, "pdf" if "pdf" in formats else formats[0])
        cols = st.columns([2, 2], vertical_alignment="center")
        fmt = cols[0].selectbox("Format", formats, index=formats.index(fmt) if fmt in formats else 0,
                                key=pick_key, label_visibility="collapsed")
        try:
            rendered = svc.render_report(shell.user, link.report_id, fmt)
            cols[1].download_button(
                "Download report", data=rendered.content, file_name=rendered.filename,
                mime=rendered.mime, key=f"dl_{link.id}_{fmt}", use_container_width=True)
        except Exception as exc:
            cols[1].caption(f"{fmt.upper()} unavailable: {exc}")

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
