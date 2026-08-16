"""Scouting - the professional recruitment workspace (Phase 8.0).

A thin view over ``ScoutingService``: no business logic here. Capability-gated
through the platform PermissionService; reports open in the EXISTING Report
Studio (the page just navigates to it by report id). Only navigation/selection
lives in session_state - every object is persisted by the service.
"""
from __future__ import annotations

import html as _html

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

# analyst A-F rating -> badge kind (A/B strong, C positive, D watch, E/F negative)
_RATING_KIND = {"A": "success", "B": "success", "C": "info", "D": "warning",
                "E": "danger", "F": "danger"}


def _initials(name: str) -> str:
    parts = [p for p in str(name or "").replace(".", " ").split() if p]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def _img_data_uri(data) -> str:
    """A data: URI for stored image bytes (mime sniffed from the magic number), or
    "" when the bytes are missing/undecodable — so the hero silently falls back to
    an initials avatar and never renders a broken image or raises."""
    if not data:
        return ""
    try:
        b = bytes(data)
        if b[:8].startswith(b"\x89PNG"):
            mime = "image/png"
        elif b[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif b[:6] in (b"GIF87a", b"GIF89a"):
            mime = "image/gif"
        elif b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            mime = "image/webp"
        elif b.lstrip()[:4] == b"<svg" or b.lstrip()[:5] == b"<?xml":
            mime = "image/svg+xml"
        else:
            mime = "image/png"
        import base64
        return f"data:{mime};base64,{base64.b64encode(b).decode('ascii')}"
    except Exception:
        return ""


def _safe_image(container, data, *, width) -> bool:
    """Render an image, tolerating broken/undecodable bytes (spec: media fallbacks
    must never error). Returns True if it displayed."""
    if not data:
        return False
    try:
        container.image(data, width=width)
        return True
    except Exception:
        return False


# a neutral, professional avatar fallback (light app theme, no player photo)
_AVATAR = ("<div style='width:56px;height:56px;border-radius:8px;"
           "background:var(--fap-surface-2,#eef1f5);color:var(--fap-text-muted,#5b6472);"
           "display:flex;align-items:center;justify-content:center;font-weight:700;"
           "font-size:18px;border:1px solid var(--fap-border,#dfe3e8)'>{}</div>")
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
        """The Recruitment Registry: identity-anchored player search with pathway/
        status/priority/recruitment-profile filters and optional live profile-fit
        (when a compatible scouting dataset is active). Not a CRUD table."""
        from fap.scouting import identity
        C.render_section_title("Recruitment Registry", eyebrow="Player Search",
                               subtitle="Search the canonical player registry - by identity, "
                               "pathway, status, priority and recruitment profile.",
                               icon_name="scouting")
        c = st.columns([3, 1, 1, 1])
        query = c[0].text_input("Search (name / alias / club)", key="scout_q")
        ptype = c[1].selectbox("Pathway", ["all", "first_team", "academy", "trialist"],
                               format_func=lambda x: "All" if x == "all" else identity.type_label(x),
                               key="scout_ptype")
        pos = c[2].text_input("Position", key="scout_pos")
        rating = c[3].selectbox("Rating", ["any"] + list(identity.ANALYST_RATINGS),
                                format_func=lambda x: "Any" if x == "any" else x, key="scout_rating")
        c2 = st.columns([1, 1, 2, 1])
        status = c2[0].selectbox("Status", ["any"] + list(identity.RECRUITMENT_STATUSES),
                                 format_func=lambda x: "Any" if x == "any" else identity.status_label(x),
                                 key="scout_status")
        priority = c2[1].selectbox("Priority", ["any"] + list(identity.RECRUITMENT_PRIORITIES),
                                   format_func=lambda x: "Any" if x == "any" else x.title(),
                                   key="scout_prio")
        profiles = [("", "Any profile")] + [(p["id"], p["name"]) for p in svc.available_profiles()]
        prof_id = c2[2].selectbox("Recruitment profile fit", [p[0] for p in profiles],
                                  format_func=lambda i: dict(profiles).get(i, i), key="scout_prof")
        min_fit = c2[3].number_input("Min fit %", 0, 100, 0, 5, key="scout_minfit") if prof_id else None

        filters: dict = {"query": query, "player_type": ptype}
        if pos.strip():
            filters["position"] = pos.strip()
        if status != "any":
            filters["status"] = status
        if priority != "any":
            filters["priority"] = priority
        if rating != "any":
            filters["rating"] = rating
        rows = svc.player_registry(
            shell.user, filters=filters, workspace_id=shell.workspace_id,
            profile_id=prof_id or None, min_fit=(min_fit if (prof_id and min_fit) else None))
        st.caption(f"{len(rows)} player(s)" + (" · fit vs active dataset" if prof_id else ""))
        if not rows:
            C.render_empty_state("No players found", "Adjust the search or filters, or add a "
                                 "new target below.", icon_name="scouting")
        for r in rows:
            self._registry_card(shell, svc, r)

        if self._can_edit:
            st.divider()
            self._add_player_form(shell, svc)

    def _add_player_form(self, shell, svc) -> None:
        """Professional, pathway-aware registration. Only fields relevant to the
        chosen pathway are shown. Creation never depends on any dataset."""
        from fap.scouting import identity, player_profile
        with st.expander("+ Add Player", expanded=False):
            st.markdown("**Identity**")
            a, b = st.columns(2)
            name = a.text_input("Full name", key="np_name")
            display = b.text_input("Preferred / display name", key="np_display")
            c, d, e = st.columns(3)
            dob = c.text_input("Date of birth", key="np_dob", placeholder="YYYY-MM-DD")
            nationality = d.text_input("Nationality", key="np_nat")
            secondary_nat = e.text_input("Secondary nationality", key="np_secnat")

            st.markdown("**Physical**")
            ph = st.columns(3)
            height = ph[0].number_input("Height (cm)", 0, 260, 0, key="np_h")
            weight = ph[1].number_input("Weight (kg)", 0, 200, 0, key="np_w")
            foot = ph[2].selectbox("Preferred foot", list(player_profile.FOOT_VALUES),
                                   index=3, format_func=str.title, key="np_foot")

            st.markdown("**Football**")
            f, g, h = st.columns(3)
            position = f.text_input("Primary position", key="np_pos", placeholder="CF")
            secondary = g.text_input("Secondary positions", key="np_sec", placeholder="RAMF, AMF")
            club = h.text_input("Current club", key="np_club")
            f2, g2, h2 = st.columns(3)
            league = f2.text_input("Competition / league", key="np_league")
            shirt = g2.number_input("Shirt number", 0, 99, 0, key="np_shirt")
            contract = h2.text_input("Contract expiry", key="np_contract", placeholder="YYYY-MM-DD")
            source = st.text_input("Source", key="np_source", placeholder="e.g. Malta league export")

            for w in player_profile.validate_profile({"dob": dob, "height_cm": height,
                                                      "weight_kg": weight, "contract_expires": contract}):
                C.render_alert(w, "warning")

            st.markdown("**Pathway**")
            np_type = st.radio("Player pathway", list(identity.PLAYER_TYPES),
                               format_func=identity.type_label, horizontal=True, key="np_type")
            extra: dict = {}
            academy_fields: dict = {}
            age_group = ""
            if np_type == "academy":
                ac = st.columns(3)
                age_group = ac[0].selectbox("Age group", [""] + list(identity.AGE_GROUPS), key="np_ag")
                academy_fields["stage"] = ac[1].text_input("Development stage", key="np_stage")
                academy_fields["projection"] = ac[2].text_input("First-team projection", key="np_proj")
                pc = st.columns(3)
                academy_fields["technical_potential"] = pc[0].number_input("Technical potential", 0, 100, 0, 5, key="np_tp") or None
                academy_fields["tactical_potential"] = pc[1].number_input("Tactical potential", 0, 100, 0, 5, key="np_tacp") or None
                academy_fields["physical_potential"] = pc[2].number_input("Physical potential", 0, 100, 0, 5, key="np_pp") or None
            elif np_type == "trialist":
                tc = st.columns(3)
                extra["trial_period"] = tc[0].text_input("Trial period", key="np_trialp")
                extra["trial_source"] = tc[1].text_input("Trial source", key="np_trials")
                extra["evaluation_status"] = tc[2].text_input("Evaluation status", key="np_evals")
            else:
                sc_ = st.columns(3)
                status = sc_[0].selectbox("Recruitment status", list(identity.RECRUITMENT_STATUSES),
                                          format_func=identity.status_label, key="np_status")
                priority = sc_[1].selectbox("Priority", [""] + list(identity.RECRUITMENT_PRIORITIES),
                                            format_func=lambda x: x.title() if x else "—", key="np_prio")
                profs = [("", "None")] + [(pr["id"], pr["name"])
                                          for pr in svc.available_profiles(position)]
                pids = [x[0] for x in profs]
                prof = sc_[2].selectbox("Recruitment profile", pids,
                                        format_func=lambda i: dict(profs).get(i, i), key="np_prof")
                extra.update(status=status, priority=priority, recruitment_profile=prof)

            st.markdown("**Media** (optional)")
            mcol = st.columns(2)
            photo = mcol[0].file_uploader("Player photo", type=["png", "jpg", "jpeg", "webp"], key="np_photo")
            logo = mcol[1].file_uploader("Club logo", type=["png", "jpg", "jpeg", "webp"], key="np_logo")
            note0 = st.text_area("Scouting note (optional)", key="np_note", height=68)

            if st.button("Create player", type="primary", key="np_create") and name.strip():
                secondary_positions = [s.strip() for s in secondary.split(",") if s.strip()]
                p = svc.create_player(
                    shell.user, name.strip(), club=club, league=league, position=position,
                    secondary_positions=secondary_positions, dob=dob, nationality=nationality,
                    secondary_nationalities=[s.strip() for s in secondary_nat.split(",") if s.strip()],
                    height=int(height) or None, weight=int(weight) or None, foot=foot,
                    shirt_number=int(shirt) or None, contract_until=contract, source=source,
                    display_name=display.strip(), player_type=np_type, age_group=age_group,
                    status=extra.get("status", ""), priority=extra.get("priority", ""),
                    recruitment_profile=extra.get("recruitment_profile", ""),
                    workspace_id=shell.workspace_id)
                if photo is not None:
                    svc.add_image(shell.user, p.id, photo.getvalue(), photo.type or "image/png", kind="profile")
                if logo is not None:
                    svc.set_club_logo(shell.user, p.id, logo.getvalue(), logo.type or "image/png")
                if note0.strip():
                    svc.add_note(shell.user, p.id, note0.strip())
                if academy_fields:
                    svc.set_academy_profile(shell.user, p.id, **academy_fields)
                if np_type == "trialist":
                    svc.set_trial_profile(
                        shell.user, p.id, trial_period=extra.get("trial_period"),
                        trial_source=extra.get("trial_source"),
                        evaluation_status=extra.get("evaluation_status"))
                st.session_state[SEL] = p.id
                st.toast(f"Created {p.name} — {identity.operational_id_of(p)}")
                st.rerun()

    def _registry_card(self, shell, svc, r: dict) -> None:
        from fap.theme import components as C
        from fap.scouting import identity
        with st.container(border=True):
            cols = st.columns([1, 5, 2, 1], vertical_alignment="center")
            img = svc.image_bytes(r["profile_image_id"]) if r.get("profile_image_id") else None
            if not _safe_image(cols[0], img, width=56):
                cols[0].markdown(_AVATAR.format(_initials(r["name"])), unsafe_allow_html=True)
            type_kind = "info" if r["player_type"] == "first_team" else "neutral"
            fit = r.get("profile_fit")
            fit_html = (f" &nbsp; {C.badge_html(f'Fit {fit:.0f}%', 'success')}"
                        if isinstance(fit, (int, float)) else "")
            cols[1].markdown(
                f"<b>{_html.escape(r['name'])}</b> &nbsp;"
                f"<span style='color:var(--fap-text-muted)'>{_html.escape(r.get('operational_id') or '—')}</span><br>"
                f"<span style='color:var(--fap-text-muted)'>{_html.escape(r.get('position') or '—')} · "
                f"{_html.escape(r.get('club') or '—')}"
                f"{' · ' + str(r['age']) if r.get('age') else ''}"
                f"{' · ' + r['age_group'] if r.get('age_group') else ''}</span>",
                unsafe_allow_html=True)
            rating = r.get("analyst_rating") or ""
            rating_html = (" " + C.badge_html(f"Rating {rating}", _RATING_KIND.get(rating, "neutral"))
                           if rating else "")
            cols[2].markdown(
                f"{C.badge_html(identity.type_label(r['player_type']), type_kind)} "
                f"{C.badge_html(identity.status_label(r['status']) or '—', 'warning')}"
                f"{rating_html}{fit_html}",
                unsafe_allow_html=True)
            if cols[3].button("Open", key=f"open_{r['id']}", use_container_width=True):
                st.session_state[SEL] = r["id"]
                st.rerun()

    # ------------------------------------------------------------ player detail
    def _player_detail(self, shell, svc, player_id) -> None:
        """The premium recruitment dossier: a persistent hero + snapshot + intelligence
        strip (always visible, above the fold) over five sections — Overview, Analysis,
        Evidence, Media, Reports. Every section reuses the existing services; nothing
        here depends on the active dataset."""
        p = svc.view_player(shell.user, player_id)
        if p is None:
            st.session_state.pop(SEL, None)
            st.rerun()
            return
        dash = svc.player_dashboard(shell.user, p.id)

        # ---- top bar: Back | Favorite ----
        top = st.columns([1, 6, 1], vertical_alignment="center")
        if top[0].button("Back", key="scout_back", use_container_width=True):
            st.session_state.pop(SEL, None)
            st.rerun()
        if self._can_edit and top[2].button("Favorite" if not p.favorite else "Unfavorite",
                                            key="scout_fav_btn", use_container_width=True,
                                            type="primary" if not p.favorite else "secondary"):
            svc.set_favorite(shell.user, p.id, not p.favorite)
            st.rerun()

        # ---- hero + snapshot + recruitment intelligence (always visible) ----
        self._hero(shell, svc, p, dash)
        self._snapshot_strip(svc, p, dash)
        self._intel_strip(shell, svc, p, dash)

        # ---- five professional sections ----
        tabs = st.tabs(["Overview", "Analysis", "Evidence", "Media", "Reports"])
        with tabs[0]:
            self._tab_overview(shell, svc, p, dash)
        with tabs[1]:
            self._tab_analysis(shell, svc, p)
        with tabs[2]:
            self._tab_evidence(shell, svc, p, dash)
        with tabs[3]:
            self._tab_media(shell, svc, p)
        with tabs[4]:
            self._tab_reports(shell, svc, p)

    # ---- hero ---------------------------------------------------------------
    def _hero(self, shell, svc, p, dash) -> None:
        from fap.scouting import identity
        from fap.scouting import profiles as _profiles
        snap = dash["snapshot"]
        op = identity.operational_id_of(p)
        prof = identity.recruitment_profile_of(p)
        prof_obj = _profiles.get_profile(prof)
        prof_name = prof_obj.name if prof_obj else ""
        ptype = identity.player_type_of(p)
        type_kind = "info" if ptype == "first_team" else "neutral"
        prio = snap.get("priority") or ""
        prio_kind = {"critical": "danger", "high": "warning"}.get(prio, "neutral")

        badges = C.badge_html(identity.type_label(ptype), type_kind)
        status_lbl = identity.status_label(snap.get("status")) if ptype == "first_team" else ""
        if status_lbl:
            badges += " " + C.badge_html(status_lbl, "warning")
        prio_lbl = identity.priority_label(prio)
        if prio_lbl:
            badges += " " + C.badge_html(prio_lbl, prio_kind)
        rating = snap.get("analyst_rating") or ""
        if rating:
            badges += " " + C.badge_html(f"Rating {rating}", _RATING_KIND.get(rating, "neutral"))
        if ptype == "academy" and snap.get("age_group"):
            badges += " " + C.badge_html(snap["age_group"], "info")

        photo = _img_data_uri(svc.image_bytes(p.profile_image_id)) if p.profile_image_id else ""
        logo = _img_data_uri(svc.image_bytes(p.club_logo_id)) if p.club_logo_id else ""
        pos_line = "  ·  ".join(x for x in (p.position, p.club) if x) or "—"
        ctx = [("Club", _html.escape(str(snap.get("club") or "—"))),
               ("Position", _html.escape(", ".join(snap.get("positions") or []) or (p.position or "—"))),
               ("Age", str(snap.get("age")) if snap.get("age") else "—"),
               ("Nationality", _html.escape(str(snap.get("nationality") or "—")))]
        C.render_player_hero(
            _html.escape(snap.get("display_name") or p.name), position_line=_html.escape(pos_line),
            photo_uri=photo, initials=_initials(p.name), logo_uri=logo, badges_html=badges,
            operational_id=_html.escape(op or ""), profile_name=_html.escape(prof_name),
            context=ctx)

    # ---- compact snapshot ---------------------------------------------------
    def _snapshot_strip(self, svc, p, dash) -> None:
        snap = dash["snapshot"]

        def _v(x):
            return "—" if x in (None, "", []) else str(x)
        age_sub = "" if snap["age_derived"] else "stored" if snap["age"] else ""
        tiles = [
            C.dossier_stat_html("Age", _v(snap["age"]), sub=age_sub, icon=icon("calendar", 15)),
            C.dossier_stat_html("Height", f"{snap['height_cm']}" if snap["height_cm"] else "—",
                                sub="cm" if snap["height_cm"] else "", icon=icon("line-straight", 15)),
            C.dossier_stat_html("Weight", f"{snap['weight_kg']}" if snap["weight_kg"] else "—",
                                sub="kg" if snap["weight_kg"] else "", icon=icon("layers", 15)),
            C.dossier_stat_html("Foot", snap["preferred_foot"].title(), icon=icon("ball", 15)),
            C.dossier_stat_html("Positions", _html.escape(", ".join(snap["positions"]) or "—"),
                                icon=icon("map-pin", 15)),
            C.dossier_stat_html("Nationality", _html.escape(_v(snap["nationality"])), icon=icon("flag", 15)),
            C.dossier_stat_html("Contract", _html.escape(_v(snap["contract_expires"])), icon=icon("book", 15)),
            C.dossier_stat_html("Shirt", f"#{snap['shirt_number']}" if snap["shirt_number"] else "—",
                                icon=icon("jersey", 15)),
        ]
        C.render_dossier_grid(tiles)

    # ---- recruitment intelligence ------------------------------------------
    def _intel_strip(self, shell, svc, p, dash) -> None:
        from fap.scouting import identity
        from fap.scouting import profiles as _profiles
        snap = dash["snapshot"]
        ptype = identity.player_type_of(p)
        # data coverage from the dashboard's data sources (metrics when available)
        cov = "—"
        for d in dash.get("data_sources", []):
            if d["kind"] == "player_scouting" and d.get("status") == "metrics_available":
                cov = f"{d.get('metric_count', 0)} metrics"
                break

        if ptype == "academy":
            ac = dash.get("academy", {}) or {}
            def _pot(v):
                return (f"{int(v)}", "good") if v else ("—", "muted")
            tech_v, tech_k = _pot(ac.get("technical_potential"))
            tact_v, tact_k = _pot(ac.get("tactical_potential"))
            phys_v, phys_k = _pot(ac.get("physical_potential"))
            items = [
                ("Pathway", identity.type_label(ptype), "", icon("players", 14)),
                ("Age group", snap.get("age_group") or "—", "" if snap.get("age_group") else "muted",
                 icon("flag", 14)),
                ("Stage", _html.escape(ac.get("stage") or "—"), "" if ac.get("stage") else "muted",
                 icon("layers", 14)),
                ("Technical", tech_v, tech_k, icon("sliders", 14)),
                ("Tactical", tact_v, tact_k, icon("target", 14)),
                ("Physical", phys_v, phys_k, icon("pulse", 14)),
                ("Data coverage", cov, "" if cov != "—" else "muted", icon("datasets", 14)),
            ]
            C.render_dossier_label("Development intelligence", icon=icon("scouting", 13))
            C.render_intel_strip(items)
            return

        prof = identity.recruitment_profile_of(p)
        prof_obj = _profiles.get_profile(prof)
        prof_name = prof_obj.name if prof_obj else "—"
        fit = dash.get("fit")
        fit_bar = None
        if fit and fit.get("available"):
            fit_v, fit_k = f"{fit['score']:.0f}%", "fit"
            fit_bar = float(fit["score"])
        elif fit is not None:
            fit_v, fit_k = "Unavailable", "muted"
        else:
            fit_v, fit_k = "No profile", "muted"
        rating = snap.get("analyst_rating") or ""
        rating_kind = {"A": "good", "B": "good", "D": "warn", "E": "warn", "F": "warn"}.get(rating, "")
        items = [
            ("Recruitment profile", _html.escape(prof_name), "" if prof_name != "—" else "muted",
             icon("target", 14)),
            ("Profile fit", fit_v, fit_k, icon("goal", 14), fit_bar),
            ("Analyst rating", rating or "—", rating_kind if rating else "muted", icon("star", 14)),
            ("Status", identity.status_label(snap.get("status")) or "—", "", icon("flag", 14)),
            ("Priority", identity.priority_label(snap.get("priority")) or "—",
             "warn" if snap.get("priority") in ("high", "critical") else "muted"
             if not snap.get("priority") else "", icon("flame", 14)),
            ("Pathway", identity.type_label(ptype), "", icon("players", 14)),
            ("Data coverage", cov, "" if cov != "—" else "muted", icon("datasets", 14)),
        ]
        C.render_dossier_label("Recruitment intelligence", icon=icon("scouting", 13))
        C.render_intel_strip(items)

    def _tab_visualization(self, shell, svc, p) -> None:
        """Player-scoped Visual Analysis. The scouting chart workspace runs over the
        player's LINKED player-scouting dataset (resolved by dataset_id, NEVER the
        active dataset), so Pizza/mplsoccer-Pizza/Radar/Bar/Scatter etc. stay
        available for this player even when a different dataset is active. An event
        dataset (if the player has one) still gets the event visualization engine."""
        # keep report-embed on save (persistent asset is saved inside the workspace)
        def _embed(png, title, viz_id):
            svc.assign_chart(shell.user, p.id, png, title=title, viz_id=viz_id)
        on_assign = _embed if self._can_edit else None

        linked = svc.linked_scouting_datasets(shell.user, p.id)
        if linked:
            ids = [d["dataset_id"] for d in linked]
            names = {d["dataset_id"]: d for d in linked}
            if len(ids) > 1:
                chosen = st.selectbox(
                    "Dataset", ids, key=f"scviz_ds_{p.id}",
                    format_func=lambda i: f"{names[i]['name']} · {names[i]['metric_count']} metrics"
                    + ("" if names[i]["linked"] else " · (active, not linked)"))
            else:
                chosen = ids[0]
                d0 = names[chosen]
                st.caption(f"Dataset: **{d0['name']}** · {d0['metric_count']} metrics"
                           + ("" if d0["linked"] else " · active (not linked yet)"))
            if not names[chosen]["linked"] and self._can_edit:
                if st.button("Link this dataset to the player", key=f"scviz_link_{p.id}"):
                    ctx0 = svc.scouting_viz_context(shell.user, p.id, chosen)
                    if ctx0:
                        svc.link_dataset_identity(shell.user, p.id, ctx0["primary"], method="manual")
                        st.rerun()
            ctx = svc.scouting_viz_context(shell.user, p.id, chosen)
            if ctx is None:
                C.render_alert("The linked dataset is unavailable or the player row could not be "
                               "resolved. Saved visual evidence remains available below.", "warning")
                return
            from fap.ui.components.scouting_viz_workspace import render_scouting_viz_workspace
            render_scouting_viz_workspace(shell, svc, p, ctx, key=f"sc_pviz_{p.id}",
                                          on_assign=on_assign)
            return

        # no player-scouting dataset linked/active: event path if the player has events
        if svc.active_dataset_kind(shell.user) == "event":
            from fap.ui.components.viz_workspace import render_visualization_workspace
            frame = svc.player_event_frame(shell.user, p.id)
            render_visualization_workspace(shell, frame=frame, player_name=p.name,
                                           key=f"sc_viz_{p.id}", on_assign=on_assign)
            if self._can_edit:
                self._assigned_charts_panel(shell, svc, p)
            return
        C.render_alert("No player-scouting or event dataset is linked to this player yet. Activate a "
                       "dataset in the Data Hub and link it here — the visualizations then stay "
                       "available regardless of the active dataset.", "info")

    def _data_sources_section(self, shell, svc, p, dash) -> None:
        """Every dataset PERSISTENTLY linked to this player, read by dataset_id and
        independent of the active dataset. Honest per-dataset status; a deleted
        dataset shows 'unavailable' (the link is kept, nothing fabricated)."""
        sources = dash.get("data_sources", [])
        active = ""
        try:
            ad = shell.wm.active_dataset(shell.user)
            active = ad.id if ad else ""
        except Exception:
            active = ""
        with st.expander(f"Data sources ({len(sources)})", expanded=bool(sources)):
            if not sources:
                C.render_alert("No datasets linked yet. Activate a dataset in the Data Hub and link "
                               "it to this player — the link then persists regardless of the active "
                               "dataset.", "info")
            _kind = {"metrics_available": "success", "linked": "success",
                     "linked_no_row": "warning", "ambiguous": "warning",
                     "not_scouting": "info", "unavailable": "danger"}
            for d in sources:
                with st.container(border=True):
                    cc = st.columns([5, 1], vertical_alignment="center")
                    stt = d["status"]
                    label = {"metrics_available": f"{d.get('metric_count', 0)} metrics",
                             "linked": f"{d.get('matches', 0)} match(es)",
                             "linked_no_row": "player record unavailable",
                             "ambiguous": "identity ambiguous",
                             "not_scouting": "event data", "unavailable": "dataset unavailable"}.get(stt, stt)
                    typ = "Player Scouting" if d["kind"] == "player_scouting" else "Event Data"
                    is_active = d["dataset_id"] == active and active
                    cc[0].markdown(
                        f"**{_html.escape(d['name'])}** "
                        + (C.badge_html('Active', 'info') + " " if is_active else "")
                        + C.badge_html(label, _kind.get(stt, "neutral"))
                        + f"<br><span style='color:var(--fap-text-muted)'>{typ}"
                        + (f" · {_html.escape(str(d['entity_key']))}" if d.get('entity_key') else "")
                        + "</span>", unsafe_allow_html=True)
                    if d["exists"] and cc[1].button("Open", key=f"ds_open_{p.id}_{d['dataset_id']}"):
                        shell.wm.set_active_dataset(shell.user, d["dataset_id"])   # working context only
                        st.rerun()

    def _visual_evidence_section(self, shell, svc, p, dash) -> None:
        """Saved player visualizations — persistent, immutable PNG assets that carry
        their source dataset + player-only scope, available regardless of the active
        dataset or a later dataset change."""
        assets = dash.get("visualizations", [])
        with st.expander(f"Visual evidence ({len(assets)})", expanded=bool(assets)):
            if not assets:
                st.caption("No saved visualizations yet. In the Visualization tab, render a chart and "
                           "click 'Save to player' — it is stored permanently against this player.")
                return
            cols = st.columns(3)
            for i, a in enumerate(reversed(assets)):
                with cols[i % 3]:
                    png = svc.player_visualization_bytes(p.id, a["id"])
                    if png:
                        st.image(png, use_container_width=True)
                    scope = a.get("scope", {}).get("player") or []
                    st.caption(f"**{_html.escape(a.get('title', 'Visualization'))}**")
                    st.caption(f"{_html.escape(a.get('source_dataset_name') or 'dataset')}"
                               + (f" · {_html.escape(', '.join(map(str, scope)))}" if scope else ""))
                    if self._can_edit and st.button("Remove", key=f"vz_del_{p.id}_{a['id']}"):
                        svc.delete_player_visualization(shell.user, p.id, a["id"]); st.rerun()

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
        player-scouting dataset, resolved through the deterministic dataset-identity
        matcher. Three independent states (player exists / dataset linked / metrics)
        are shown honestly - a missing link is informational, never an error."""
        self._dataset_identity_panel(shell, svc, p)
        with st.expander("Scouting profile (active dataset)", expanded=True):
            profile = svc.active_scouting_profile(shell.user, p.id)
            if profile is None:
                C.render_alert(
                    "Metrics unavailable — no dataset record is linked to this player yet. "
                    "Link the player to a dataset row above; the player profile, notes, "
                    "ratings, tags, videos and links remain fully available.", "info")
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

    def _dataset_identity_panel(self, shell, svc, p) -> None:
        """DATASET IDENTITY: the confirmed/auto/proposed/ambiguous mapping between
        the canonical player and a row in the active scouting dataset. The dataset's
        spelling never becomes the player's identity."""
        status = svc.dataset_link_status(shell.user, p.id)
        if not status["dataset_active"]:
            return
        can_edit = getattr(self, "_can_edit", False)
        with st.container(border=True):
            st.markdown(f"**Dataset identity** &nbsp; "
                        f"<span style='color:var(--fap-text-muted)'>{_html.escape(status['dataset_name'])}</span>",
                        unsafe_allow_html=True)
            if status["linked"]:
                st.markdown(
                    f"{C.badge_html('Linked', 'success')} &nbsp; **{_html.escape(str(status['entity_key']))}** "
                    f"&nbsp; <span style='color:var(--fap-text-muted)'>{_html.escape(status['method'])}"
                    f"{' · auto' if status['auto'] else ''}</span>", unsafe_allow_html=True)
                if can_edit and st.button("Change dataset match", key=f"dl_change_{p.id}"):
                    st.session_state[f"dl_manual_{p.id}"] = True
            elif status["proposed"]:
                cand = status["proposed"]
                st.markdown(f"{icon('search', 13)} **Possible dataset match found**", unsafe_allow_html=True)
                st.markdown(f"{_html.escape(p.name)} → **{_html.escape(cand['key'])}** "
                            f"<span style='color:var(--fap-text-muted)'>{_html.escape(cand['method'])} · "
                            f"{cand['confidence']} confidence</span>", unsafe_allow_html=True)
                if can_edit and st.button("Confirm match", type="primary", key=f"dl_confirm_{p.id}"):
                    svc.link_dataset_identity(shell.user, p.id, cand["key"], method=cand["method"])
                    st.rerun()
            elif status["candidates"]:
                st.markdown(f"{icon('alert-triangle', 13)} **Multiple possible matches** — choose one:",
                            unsafe_allow_html=True)
                for cand in status["candidates"]:
                    dims = cand.get("dims", {})
                    ctx = " · ".join(str(dims[k]) for k in ("team", "position") if dims.get(k))
                    cc = st.columns([4, 1], vertical_alignment="center")
                    cc[0].markdown(f"**{_html.escape(cand['key'])}** "
                                   f"<span style='color:var(--fap-text-muted)'>{_html.escape(ctx)}</span>",
                                   unsafe_allow_html=True)
                    if can_edit and cc[1].button("Select", key=f"dl_sel_{p.id}_{cand['key']}"):
                        svc.link_dataset_identity(shell.user, p.id, cand["key"], method="manual (ambiguous)")
                        st.rerun()
            else:
                st.markdown(f"{C.badge_html('Not linked', 'neutral')} &nbsp; "
                            "no matching record in this dataset.")
                if can_edit and st.button("Find player in dataset", key=f"dl_find_{p.id}"):
                    st.session_state[f"dl_manual_{p.id}"] = True
            # manual search/selection dialog
            if can_edit and st.session_state.get(f"dl_manual_{p.id}"):
                ctx = svc.active_scouting_dataset(shell.user)
                q = st.text_input("Search the dataset", key=f"dl_q_{p.id}").strip().lower()
                names = ctx["players"] if ctx else []
                hits = [n for n in names if q in n.lower()][:15] if q else names[:15]
                pick = st.selectbox("Dataset player", hits, key=f"dl_pick_{p.id}") if hits else None
                mcols = st.columns(2)
                if pick and mcols[0].button("Link selected", type="primary", key=f"dl_link_{p.id}"):
                    svc.link_dataset_identity(shell.user, p.id, pick, method="manual")
                    st.session_state.pop(f"dl_manual_{p.id}", None); st.rerun()
                if mcols[1].button("Cancel", key=f"dl_cancel_{p.id}"):
                    st.session_state.pop(f"dl_manual_{p.id}", None); st.rerun()
            if status["linked"] and can_edit:
                if st.button("Unlink", key=f"dl_unlink_{p.id}"):
                    svc.unlink_dataset_identity(shell.user, p.id); st.rerun()

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

    # ============================================================ OVERVIEW tab
    def _tab_overview(self, shell, svc, p, dash) -> None:
        """The dossier landing — a true intelligence dashboard, not a form: an
        at-a-glance counts row, the recruitment assessment (transparent fit), observed
        strengths / areas to monitor, saved visual evidence, read-only video + match
        previews, scouting notes, then the data sources. Editing lives behind an
        expander below. Everything is active-dataset-independent."""
        from fap.scouting import identity
        snap = dash["snapshot"]
        ptype = identity.player_type_of(p)
        matches = svc.player_matches(shell.user, p.id)
        videos = svc.list_videos(p.id)

        # 1) intelligence snapshot (real persisted totals) ----
        self._intel_counts(dash, matches, videos)

        # 2) recruitment assessment (transparent, never fabricated) ----
        C.render_dossier_label("Recruitment assessment", icon=icon("target", 13))
        if ptype == "academy":
            self._academy_assessment(p, dash)
        if dash["fit"] is not None:
            fit = dash["fit"]
            with st.container(border=True):
                if fit.get("available"):
                    badge = C.badge_html(f"Fit {fit['score']:.0f}", "success")
                    st.markdown(
                        f"**{_html.escape(fit['profile'])}** &nbsp; {badge} &nbsp; "
                        f"<span style='color:var(--fap-text-muted)'>{fit['mode']} · "
                        f"{len(fit['matched'])} matched metrics</span>", unsafe_allow_html=True)
                    st.caption("Matched: " + ", ".join(fit["matched"][:10]))
                else:
                    st.caption(f"{fit['profile']} fit unavailable — {fit.get('reason', '')}")
        elif ptype != "academy":
            st.caption("No recruitment profile set yet — assign one in Edit profile to compute a "
                       "transparent, data-driven fit.")

        # 3) strengths / areas to monitor (observation only) ----
        if dash["strengths"]:
            C.render_dossier_label("Strengths & areas to monitor", icon=icon("pulse", 13))
            sc_cols = st.columns(2)
            with sc_cols[0]:
                st.markdown(f"{icon('arrow-up', 13)} **Strengths** (top percentiles)",
                            unsafe_allow_html=True)
                for s in dash["strengths"]:
                    st.markdown(f"{C.badge_html(str(s['percentile']), 'success')} {_html.escape(s['name'])}",
                                unsafe_allow_html=True)
            with sc_cols[1]:
                if dash["dev_areas"]:
                    st.markdown(f"{icon('warning', 13)} **Areas to monitor** (low percentiles)",
                                unsafe_allow_html=True)
                    for s in dash["dev_areas"]:
                        st.markdown(f"{C.badge_html(str(s['percentile']), 'warning')} {_html.escape(s['name'])}",
                                    unsafe_allow_html=True)
            st.caption("Data-driven observations from the linked scouting dataset — analyst "
                       "interpretation is kept separate (Scouting notes below).")

        # 4) saved visual evidence (persistent immutable assets) ----
        self._visual_evidence_section(shell, svc, p, dash)

        # 5) video evidence preview (read-only; full player in the Evidence tab) ----
        self._video_evidence_preview(shell, svc, p, videos)

        # 6) match evidence preview (read-only; full tools in the Evidence tab) ----
        self._match_evidence_preview(matches)

        # 7) scouting notes (analyst interpretation) ----
        C.render_dossier_label(f"Scouting notes ({dash['counts']['notes']})", icon=icon("text", 13))
        self._notes(shell, svc, p)

        # data sources (persistent, active-independent) ----
        self._data_sources_section(shell, svc, p, dash)

        if not self._can_edit:
            return
        # ---- editing behind an expander so the Overview stays a dossier ----
        with st.expander("Edit profile & recruitment", expanded=False):
            self._edit_profile_form(shell, svc, p, snap)
            self._recruitment_block(shell, svc, p)
            if ptype == "academy":
                self._academy_block(shell, svc, p)
            self._history_block(svc, p)
            col = st.columns(3)
            if col[0].button("Archive" if not p.archived else "Restore", key="p_archive"):
                svc.archive_player(shell.user, p.id, not p.archived); st.rerun()
            if col[1].button("Duplicate", key="p_dup"):
                dup = svc.duplicate_player(shell.user, p.id); st.session_state[SEL] = dup.id; st.rerun()
            if col[2].button("Delete", key="p_del"):
                svc.delete_player(shell.user, p.id); st.session_state.pop(SEL, None); st.rerun()

    def _intel_counts(self, dash, matches, videos) -> None:
        counts = dash.get("counts", {})
        items = [
            (icon("datasets", 16), str(counts.get("data_sources", 0)), "Data sources"),
            (icon("match", 16), str(len(matches)), "Matches"),
            (icon("video", 16), str(len(videos)), "Videos"),
            (icon("grid", 16), str(counts.get("visualizations", 0)), "Visualizations"),
            (icon("reports", 16), str(counts.get("reports", 0)), "Reports"),
        ]
        C.render_snapshot_counts(items)

    def _academy_assessment(self, p, dash) -> None:
        """Development-focused summary for academy players (real data only)."""
        from fap.scouting import identity
        ac = dash.get("academy", {}) or {}
        snap = dash["snapshot"]
        bits = []
        if snap.get("age_group"):
            bits.append(f"**Age group** {snap['age_group']}")
        if ac.get("stage"):
            bits.append(f"**Stage** {_html.escape(ac['stage'])}")
        if ac.get("projection"):
            bits.append(f"**Projection** {_html.escape(ac['projection'])}")
        if bits:
            st.markdown(" &nbsp;·&nbsp; ".join(bits), unsafe_allow_html=True)
        pots = [("Technical", ac.get("technical_potential")), ("Tactical", ac.get("tactical_potential")),
                ("Physical", ac.get("physical_potential"))]
        if any(v for _, v in pots):
            st.caption("Development potential (analyst-entered): "
                       + " · ".join(f"{lbl} {int(v)}" for lbl, v in pots if v))

    def _video_evidence_preview(self, shell, svc, p, videos) -> None:
        C.render_dossier_label(f"Video evidence ({len(videos)})", icon=icon("video", 13))
        if not videos:
            st.caption("No videos linked yet. Add match footage in the Evidence tab.")
            return
        for v in videos[:3]:
            synced = ("Synced" if (v.match_id and v.sync_offset_seconds is not None)
                      else "Linked" if v.match_id else "Not linked")
            ds_name = ""
            if getattr(v, "dataset_id", ""):
                try:
                    ds = shell.wm.get_dataset(v.dataset_id)
                    ds_name = ds.name if ds else ""
                except Exception:
                    ds_name = ""
            meta = " · ".join(x for x in (
                v.provider or ("uploaded" if v.kind == "upload" else ""),
                (f"match {v.match_id}" if v.match_id else ""), ds_name, synced) if x)
            st.markdown(C.evidence_card_html(_html.escape(v.title or "Video"), _html.escape(meta),
                                             icon=icon("video", 16)), unsafe_allow_html=True)
        tail = f"+{len(videos) - 3} more · " if len(videos) > 3 else ""
        st.caption(tail + "Open the Evidence tab to watch, seek and manage.")

    def _match_evidence_preview(self, matches) -> None:
        C.render_dossier_label(f"Match evidence ({len(matches)})", icon=icon("match", 13))
        if not matches:
            st.caption("No match-level evidence yet. Link an event dataset in the Evidence tab.")
            return
        for m in matches[:3]:
            title = m.get("opponent") or m.get("match_id")
            meta = " · ".join(x for x in (m.get("competition"), m.get("match_date"),
                                          f"{m.get('event_count', 0)} tagged actions") if x)
            st.markdown(C.evidence_card_html(_html.escape(str(title)), _html.escape(meta),
                                             icon=icon("match", 16)), unsafe_allow_html=True)
        tail = f"+{len(matches) - 3} more · " if len(matches) > 3 else ""
        st.caption(tail + "Open the Evidence tab for full match evidence and linking.")

    # ============================================================ ANALYSIS tab
    def _tab_analysis(self, shell, svc, p) -> None:
        """Visual analysis: the player-scoped scouting visualization workspace (Metric
        Explorer / Visualizations / Pizza Builder / Population Context) plus the active
        dataset's metric or event analysis. The chart engine/themes are untouched."""
        C.render_dossier_label("Visual analysis", icon=icon("analysis", 13))
        self._tab_visualization(shell, svc, p)
        st.divider()
        self._active_analysis(shell, svc, p)

    # ============================================================ EVIDENCE tab
    def _tab_evidence(self, shell, svc, p, dash) -> None:
        """The evidence centre: match-level evidence across linked datasets and the
        synced match videos with their click-to-seek action lists — all read by their
        persisted dataset_id (active-independent). Saved visual evidence lives on the
        Overview; it is not repeated here (one interactive owner per component)."""
        C.render_dossier_label("Match evidence", icon=icon("target", 13))
        self._evidence_section(shell, svc, p)
        C.render_dossier_label(f"Match videos ({dash['counts']['videos']})", icon=icon("video", 13))
        self._videos(shell, svc, p)

    # ============================================================ MEDIA tab
    def _tab_media(self, shell, svc, p) -> None:
        """The media centre: player photo + club crest, the image gallery, external
        scouting links and attachments. Match videos live under Evidence (next to
        their action lists)."""
        pcols = st.columns([1, 1, 4], vertical_alignment="center")
        photo = svc.image_bytes(p.profile_image_id) if p.profile_image_id else None
        if not _safe_image(pcols[0], photo, width=96):
            pcols[0].markdown(_AVATAR.format(_initials(p.name)).replace("56px", "96px")
                              .replace("18px", "32px"), unsafe_allow_html=True)
        pcols[0].caption("Player photo")
        logo = svc.image_bytes(p.club_logo_id) if p.club_logo_id else None
        if _safe_image(pcols[1], logo, width=64):
            pcols[1].caption("Club logo")
        else:
            pcols[1].caption("No club logo")
        pcols[2].caption("Set the player photo and club logo from the Overview → Edit profile "
                         "panel. Additional imagery can be uploaded below.")
        C.render_dossier_label("Player imagery")
        self._images(shell, svc, p)
        self._links_panel(shell, svc, p)
        self._attachments(shell, svc, p)

    # ============================================================ REPORTS tab
    def _tab_reports(self, shell, svc, p) -> None:
        self._reports(shell, svc, p)

    def _evidence_section(self, shell, svc, p) -> None:
        """Match-level evidence: which matches this player has evidence for, across
        ALL linked datasets (persistent, independent of the active dataset). Clicking
        a match opens it in the existing event pathway with player scope preserved."""
        matches = svc.player_matches(shell.user, p.id)
        with st.expander(f"Evidence — matches ({len(matches)})", expanded=bool(matches)):
            if not matches:
                st.caption("No match-level evidence available. Link an event dataset to this "
                           "player below to build a permanent, per-match evidence trail.")
            for m in matches:
                cols = st.columns([5, 1], vertical_alignment="center")
                title = m["opponent"] or m["match_id"]
                meta = " · ".join(x for x in (m.get("match_date"), m.get("competition"),
                                              f"{len(m['datasets'])} dataset(s)") if x)
                badge = C.badge_html(f"{m['event_count']} tagged actions", "info")
                cols[0].markdown(
                    f"**{_html.escape(str(m['match_id']))}**  {_html.escape(str(title))} "
                    f"&nbsp; {badge}<br>"
                    f"<span style='color:var(--fap-text-muted)'>{_html.escape(meta)}</span>",
                    unsafe_allow_html=True)
                if cols[1].button("Open", key=f"ev_open_{p.id}_{m['match_id']}"):
                    ds0 = m["datasets"][0]["dataset_id"] if m["datasets"] else None
                    if ds0:
                        shell.wm.set_active_dataset(shell.user, ds0)   # query context only
                        st.session_state["_scout_evidence_scope"] = {
                            "player_id": p.id, "match_id": m["match_id"], "dataset_id": ds0}
                        st.rerun()

            # link the currently active event dataset to a match (no fabrication)
            if self._can_edit:
                try:
                    active = shell.wm.active_dataset(shell.user)
                except Exception:
                    active = None
                kind = svc.active_dataset_kind(shell.user)
                if active is None:
                    st.caption("No active dataset. Activate an event dataset in the Data Hub to link it.")
                elif kind == "player_scouting":
                    st.caption(f"Active dataset '{active.name}' is player-scouting data "
                               "(metrics, no match events) — not linkable as match evidence.")
                else:
                    st.divider()
                    lc = st.columns([3, 1])
                    mid = lc[0].text_input("Link active dataset to match id (optional)",
                                           key=f"ev_mid_{p.id}",
                                           placeholder="leave blank to use the dataset's own match_id column")
                    if lc[1].button("Link dataset", key=f"ev_link_{p.id}"):
                        svc.link_match_evidence(shell.user, p.id, active.id, match_id=mid.strip())
                        st.rerun()

    def _links_panel(self, shell, svc, p) -> None:
        links = svc.list_links(p.id)
        with st.expander(f"External links ({len(links)})"):
            for l in links:
                cc = st.columns([5, 1], vertical_alignment="center")
                cc[0].markdown(f"{icon('link', 13)} [{_html.escape(l.get('title') or l['url'])}]({l['url']})"
                               f" &nbsp; <span style='color:var(--fap-text-muted)'>{_html.escape(l.get('category',''))}</span>",
                               unsafe_allow_html=True)
                if self._can_edit and cc[1].button("Remove", key=f"lk_{l['id']}"):
                    svc.delete_link(shell.user, p.id, l["id"]); st.rerun()
            if self._can_edit:
                a, b, c = st.columns([3, 2, 1])
                url = a.text_input("URL", key=f"lk_url_{p.id}", placeholder="https://…")
                title = b.text_input("Title", key=f"lk_title_{p.id}")
                cat = c.selectbox("Type", ["reference", "video", "profile", "article", "club", "other"],
                                  key=f"lk_cat_{p.id}")
                if st.button("Add link", key=f"lk_add_{p.id}") and url.strip():
                    svc.add_link(shell.user, p.id, url.strip(), title=title.strip(), category=cat)
                    st.rerun()

    def _edit_profile_form(self, shell, svc, p, snap) -> None:
        """Full sectioned Edit form - preserves player_id/operational_id/links/etc.,
        with honest validation warnings (never silently corrects)."""
        from fap.scouting import identity, player_profile
        with st.expander("Edit profile"):
            st.markdown("**Identity**")
            i = st.columns(3)
            display_name = i[0].text_input("Display name", value=snap["display_name"], key="ep_dn")
            dob = i[1].text_input("Date of birth", value=snap["dob"] or "", key="ep_dob", placeholder="YYYY-MM-DD")
            nationality = i[2].text_input("Nationality", value=snap["nationality"] or "", key="ep_nat")
            j = st.columns(2)
            secondary_nat = j[0].text_input("Secondary nationalities", key="ep_secnat",
                                            value=", ".join(snap["secondary_nationalities"]))
            alias_str = j[1].text_input("Aliases", value=", ".join(snap["aliases"]), key="ep_aliases")

            st.markdown("**Physical**")
            ph = st.columns(3)
            height = ph[0].number_input("Height (cm)", 0, 260, int(snap["height_cm"] or 0), key="ep_h")
            weight = ph[1].number_input("Weight (kg)", 0, 200, int(snap["weight_kg"] or 0), key="ep_w")
            foot = ph[2].selectbox("Preferred foot", list(player_profile.FOOT_VALUES),
                                   index=list(player_profile.FOOT_VALUES).index(snap["preferred_foot"]),
                                   format_func=str.title, key="ep_foot")

            st.markdown("**Football**")
            fb = st.columns(3)
            position = fb[0].text_input("Primary position", value=p.position, key="ep_pos")
            secondary_pos = fb[1].text_input("Secondary positions",
                                             value=", ".join(p.secondary_positions or []), key="ep_secpos")
            shirt = fb[2].number_input("Shirt number", 0, 99, int(snap["shirt_number"] or 0), key="ep_shirt")
            fb2 = st.columns(3)
            club = fb2[0].text_input("Club", value=p.club, key="ep_club")
            league = fb2[1].text_input("League", value=p.league, key="ep_league")
            contract = fb2[2].text_input("Contract expiry", value=snap["contract_expires"] or "", key="ep_contract")
            agent = st.text_input("Agent", value=snap["agent"] or "", key="ep_agent")

            st.markdown("**Recruitment**")
            statuses = list(identity.RECRUITMENT_STATUSES)
            priorities = [""] + list(identity.RECRUITMENT_PRIORITIES)
            rc = st.columns(3)
            status = rc[0].selectbox("Status", statuses,
                                     index=statuses.index(snap["status"]) if snap["status"] in statuses else 0,
                                     format_func=identity.status_label, key="ep_status")
            priority = rc[1].selectbox("Priority", priorities,
                                       index=priorities.index(snap["priority"]) if snap["priority"] in priorities else 0,
                                       format_func=lambda x: identity.priority_label(x) or "—", key="ep_priority")
            ratings = [""] + list(identity.ANALYST_RATINGS)
            cur_rating = snap.get("analyst_rating") or ""
            rating = rc[2].selectbox(
                "Analyst rating (A–F)", ratings,
                index=ratings.index(cur_rating) if cur_rating in ratings else 0,
                format_func=lambda x: identity.rating_label(x) or "— not rated", key="ep_rating",
                help="The analyst's manual recruitment verdict — distinct from the data-driven profile fit.")
            source = st.text_input("Source", value=snap["source"], key="ep_source")

            edited = {"dob": dob, "height_cm": height, "weight_kg": weight,
                      "preferred_foot": foot, "contract_expires": contract}
            for w in player_profile.validate_profile(edited):
                C.render_alert(w, "warning")

            if st.button("Save profile", type="primary", key="ep_save"):
                svc.update_profile(
                    shell.user, p.id, dob=dob, nationality=nationality, height=int(height) or None,
                    weight=int(weight) or None, foot=foot, position=position,
                    secondary_positions=[s.strip() for s in secondary_pos.split(",") if s.strip()],
                    shirt_number=int(shirt) or None, club=club, league=league,
                    contract_until=contract, agent=agent,
                    secondary_nationalities=[s.strip() for s in secondary_nat.split(",") if s.strip()])
                svc.set_recruitment_status(shell.user, p.id, status)
                svc.set_priority(shell.user, p.id, priority)
                svc.set_analyst_rating(shell.user, p.id, rating)
                svc.set_display_name(shell.user, p.id, display_name)
                svc.set_source(shell.user, p.id, source)
                svc.set_aliases(shell.user, p.id, [a.strip() for a in alias_str.split(",") if a.strip()])
                st.rerun()

            st.markdown("**Media**")
            mc = st.columns(2)
            photo = mc[0].file_uploader("Player photo", type=["png", "jpg", "jpeg", "webp"], key="ep_photo")
            if photo is not None and mc[0].button("Set photo", key="ep_setphoto"):
                svc.add_image(shell.user, p.id, photo.getvalue(), photo.type or "image/png", kind="profile")
                st.rerun()
            logo = mc[1].file_uploader("Club logo", type=["png", "jpg", "jpeg", "webp", "svg"], key="ep_logo")
            if logo is not None and mc[1].button("Set logo", key="ep_setlogo"):
                svc.set_club_logo(shell.user, p.id, logo.getvalue(), logo.type or "image/png")
                st.rerun()

    def _recruitment_block(self, shell, svc, p) -> None:
        from fap.scouting import identity
        with st.expander("Recruitment profile & pathway"):
            cur_prof = identity.recruitment_profile_of(p)
            opts = [("", "None")] + [(pr["id"], pr["name"])
                                     for pr in svc.available_profiles(p.position)]
            ids = [o[0] for o in opts]
            prof = st.selectbox("Recruitment profile", ids,
                                index=ids.index(cur_prof) if cur_prof in ids else 0,
                                format_func=lambda i: dict(opts).get(i, i), key="ep_prof")
            if st.button("Set profile", key="ep_setprof"):
                svc.set_recruitment_profile(shell.user, p.id, prof); st.rerun()
            st.divider()
            cur_type = identity.player_type_of(p)
            st.caption(f"Pathway: **{identity.type_label(cur_type)}** · "
                       f"internal id `{p.id}` (immutable)")
            if cur_type == "academy":
                if st.button("Promote to First Team", type="primary", key="ep_promote"):
                    svc.promote_to_first_team(shell.user, p.id,
                                              note="promoted from Academy"); st.rerun()
            else:
                new_type = st.selectbox("Change pathway", list(identity.PLAYER_TYPES),
                                        index=list(identity.PLAYER_TYPES).index(cur_type),
                                        format_func=identity.type_label, key="ep_ptype")
                if new_type != cur_type and st.button("Apply pathway change", key="ep_setptype"):
                    svc.set_player_type(shell.user, p.id, new_type,
                                        reassign_operational_id=True); st.rerun()

    def _academy_block(self, shell, svc, p) -> None:
        from fap.scouting import identity
        with st.expander("Academy development", expanded=True):
            ac = identity.academy_profile_of(p)
            cc = st.columns(3)
            age_group = cc[0].selectbox("Age group", [""] + list(identity.AGE_GROUPS),
                                        index=([""] + list(identity.AGE_GROUPS)).index(identity.age_group_of(p))
                                        if identity.age_group_of(p) in identity.AGE_GROUPS else 0,
                                        key="ac_ag")
            stage = cc[1].text_input("Development stage", value=ac.get("stage", ""), key="ac_stage")
            projection = cc[2].text_input("First-Team projection", value=ac.get("projection", ""),
                                          key="ac_proj")
            pc = st.columns(3)
            tech = pc[0].number_input("Technical potential", 0, 100, int(ac.get("technical_potential", 0)),
                                      5, key="ac_tech")
            tact = pc[1].number_input("Tactical potential", 0, 100, int(ac.get("tactical_potential", 0)),
                                      5, key="ac_tact")
            phys = pc[2].number_input("Physical potential", 0, 100, int(ac.get("physical_potential", 0)),
                                      5, key="ac_phys")
            if st.button("Save academy profile", key="ac_save"):
                svc.set_age_group(shell.user, p.id, age_group)
                svc.set_academy_profile(
                    shell.user, p.id, stage=stage, projection=projection,
                    technical_potential=tech or None, tactical_potential=tact or None,
                    physical_potential=phys or None)
                st.rerun()

    def _history_block(self, svc, p) -> None:
        from fap.scouting import identity
        sh = identity.status_history_of(p)
        ph = identity.pathway_history_of(p)
        if not sh and not ph:
            return
        with st.expander("Recruitment & development history"):
            for ev in reversed(ph):
                st.markdown(f"{icon('shuffle', 13)} **Pathway** {identity.type_label(ev.get('from'))} "
                            f"→ {identity.type_label(ev.get('to'))} "
                            f"({ev.get('operational_id_before','')} → {ev.get('operational_id_after','')})  "
                            f"<span style='color:var(--fap-text-muted)'>{ev.get('at','')} · {ev.get('by','')}</span>",
                            unsafe_allow_html=True)
            for ev in reversed(sh):
                st.markdown(f"{icon('flag', 13)} **Status** {identity.status_label(ev.get('from'))} "
                            f"→ {identity.status_label(ev.get('to'))}  "
                            f"<span style='color:var(--fap-text-muted)'>{ev.get('at','')} · {ev.get('by','')}"
                            f"{' · ' + ev['note'] if ev.get('note') else ''}</span>",
                            unsafe_allow_html=True)

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
        with st.expander("Link this footage to a match dataset (enables click-to-seek)",
                         expanded=not bool(v.dataset_id)):
            try:
                active = shell.wm.active_dataset(shell.user)
            except Exception:
                active = None
            # Linking captures the active EVENT dataset PERMANENTLY on the video, so the
            # active dataset never influences the action list afterwards.
            if active is None or svc.active_dataset_kind(shell.user) != "event":
                st.caption("Activate this player's event match dataset in the Data Hub, then link it "
                           "here. The link is saved permanently — changing the active dataset later "
                           "won't affect this video's actions.")
                return
            frame = svc.player_event_frame(shell.user, p.id)
            ids = []
            if frame is not None and "match_id" in frame.columns:
                ids = sorted({str(m).strip() for m in frame["match_id"] if str(m).strip()})
            options = ["(choose)"] + ids
            chosen = st.selectbox("Match", options, key=f"vm_sel_{v.id}")
            manual = st.text_input("…or type a match id", key=f"vm_txt_{v.id}")
            target = manual.strip() or ("" if chosen == "(choose)" else chosen)
            st.caption(f"Evidence source: **{_html.escape(active.name)}**")
            if st.button("Link match", key=f"vm_btn_{v.id}") and target:
                svc.link_video_to_match(shell.user, v.id, active.id, target)   # persists dataset_id
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
        ds_name = ""
        if getattr(v, "dataset_id", ""):
            try:
                ds = shell.wm.get_dataset(v.dataset_id)
                ds_name = ds.name if ds else ""
            except Exception:
                ds_name = ""
        st.caption(f"Synced to match **{v.match_id}**"
                   + (f" · dataset **{_html.escape(ds_name)}**" if ds_name else "")
                   + f" (kickoff at {float(v.sync_offset_seconds):.1f}s). "
                   "Click an event to jump the video there — actions stay from this dataset "
                   "regardless of the active dataset.")
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
        # Actions come from the video's PERSISTED dataset_id (P4.4/P4.5), NEVER the
        # active dataset. A legacy video (no dataset_id) is explicitly re-linked.
        ev = svc.video_events(shell.user, p.id, v)
        if ev is None:
            if not getattr(v, "dataset_id", ""):
                C.render_alert("Dataset not linked. Link this video to its match dataset to load "
                               "the player's actions — it will then stay linked regardless of the "
                               "active dataset.", "info")
                self._match_linker(shell, svc, p, v)
            else:
                C.render_alert("The linked dataset is unavailable or holds no events for this "
                               "match.", "info")
            return
        ev = ev.copy()
        if ev.empty:
            C.render_alert(f"No events for match {v.match_id} for this player in the linked "
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
        # ---- two clearly-separated generation options ----
        if self._can_report:
            self._generate_report_panel(shell, svc, p)
            st.divider()

        # ---- existing reports (premium + standard) ----
        links = svc.list_reports(p.id)
        if not links:
            C.render_empty_state("No reports yet", "Generate a Premium Player Report or a Standard "
                                 "report above.", icon_name="reports")
        for link in links:
            info = svc.premium_report_info(link.report_id)
            with st.container(border=True):
                cols = st.columns([3, 1, 1], vertical_alignment="center")
                badge = (C.badge_html("Premium", "warning") if info.get("is_premium")
                         else C.badge_html("Standard", "neutral"))
                extra = ""
                if info.get("is_premium"):
                    bits = [x for x in (f"Source: {info['source']}" if info.get("source") else "",
                                        f"Rating: {info['rating']}" if info.get("rating") else "") if x]
                    extra = ("<br><span style='color:var(--fap-text-muted)'>"
                             + " · ".join(bits) + "</span>") if bits else ""
                cols[0].markdown(f"{icon('reports', 14)} **{_html.escape(link.title)}** {badge}"
                                 f"<br><span style='color:var(--fap-text-muted)'>{link.created_at}</span>"
                                 f"{extra}", unsafe_allow_html=True)
                if cols[1].button("Open", key=f"open_rep_{link.id}", use_container_width=True):
                    st.session_state[OPEN_REPORT] = link.report_id
                    shell.goto("report_editor")       # reuse the existing Report Studio
                if self._can_report and not info.get("is_premium") and cols[2].button(
                        "Add charts", key=f"addc_{link.id}", use_container_width=True):
                    added = svc.add_charts_to_report(shell.user, link.report_id, p.id)
                    st.toast(f"Added {added} chart(s) to the report" if added
                             else "No assigned charts to add")
                    st.rerun()
                if self._can_export:
                    self._download_report(shell, svc, link, premium=info.get("is_premium", False))

    def _generate_report_panel(self, shell, svc, p) -> None:
        """Two clearly-separated options: the new recruitment-focused Premium Player
        Report, and the EXISTING Standard report (unchanged)."""
        st.markdown("#### Generate player report")
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                st.markdown(f"**{icon('star', 15)} Premium Player Report**", unsafe_allow_html=True)
                st.caption("Professional recruitment dossier: branded cover, A–F rating, "
                           "recruitment fit, automatic player-scoped charts, strengths / areas "
                           "to monitor, all notes, video QR codes and evidence.")
                linked = svc.linked_scouting_datasets(shell.user, p.id)
                ds_id = ""
                if linked:
                    ids = [d["dataset_id"] for d in linked]
                    names = {d["dataset_id"]: d for d in linked}
                    ds_id = st.selectbox(
                        "Data source", ids, key=f"prem_ds_{p.id}",
                        format_func=lambda i: f"{names[i]['name']} · {names[i]['metric_count']} metrics")
                else:
                    st.caption("No linked scouting dataset — the report generates without charts.")
                inc = st.checkbox("Include automatic charts", value=True, key=f"prem_charts_{p.id}")
                brand = None
                with st.expander("Report brand colours (optional)"):
                    st.caption("Applies only to this report's cover — never the app or chart themes.")
                    use_brand = st.checkbox("Apply custom brand colours", key=f"prem_brand_{p.id}")
                    bc = st.columns(3)
                    primary = bc[0].color_picker("Primary", "#E07B2B", key=f"prem_pc_{p.id}")
                    secondary = bc[1].color_picker("Secondary", "#0B1F3A", key=f"prem_sc_{p.id}")
                    accent = bc[2].color_picker("Accent", "#E07B2B", key=f"prem_ac_{p.id}")
                    if use_brand:
                        brand = {"primary": primary, "secondary": secondary, "accent": accent}
                if st.button("Generate Premium Report", type="primary",
                             key=f"gen_premium_{p.id}", use_container_width=True):
                    try:
                        link = svc.create_premium_report(
                            shell.user, p.id, dataset_id=ds_id, include_charts=inc, brand=brand)
                        st.toast(f"Premium report generated for {p.name}")
                        st.rerun()
                    except Exception as exc:
                        C.render_alert(f"Could not generate the premium report: {exc}", "warning")
        with right:
            with st.container(border=True):
                st.markdown(f"**{icon('reports', 15)} Standard Report**", unsafe_allow_html=True)
                n_charts = len(svc.list_assigned_charts(p.id))
                st.caption(f"The existing report generator and Studio layout. "
                           f"{n_charts} assigned chart(s) are embedded automatically.")
                if st.button("Generate Standard Report", key=f"gen_standard_{p.id}",
                             use_container_width=True):
                    link = svc.create_report(shell.user, p.id)
                    st.session_state[OPEN_REPORT] = link.report_id
                    shell.goto("report_editor")       # open the auto-generated report in Studio

    def _download_report(self, shell, svc, link, *, premium: bool = False) -> None:
        """Render a linked report to a file and offer it for download. Premium reports
        render through the premium pipeline (cover photo/logo resolver + embedded
        charts/QR); Standard reports use the existing export pipeline."""
        formats = svc.report_formats() or ["html"]
        pick_key = f"fmt_{link.id}"
        fmt = st.session_state.get(pick_key, "pdf" if "pdf" in formats else formats[0])
        cols = st.columns([2, 2], vertical_alignment="center")
        fmt = cols[0].selectbox("Format", formats, index=formats.index(fmt) if fmt in formats else 0,
                                key=pick_key, label_visibility="collapsed")
        try:
            rendered = (svc.render_premium_report(shell.user, link.report_id, fmt) if premium
                        else svc.render_report(shell.user, link.report_id, fmt))
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
