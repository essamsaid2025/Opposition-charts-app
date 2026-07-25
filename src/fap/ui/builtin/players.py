"""First Team Players - our squad workspace (Phase 10 · P-Foundation).

A thin view over ``PlayersService``: no business logic here. Capability-gated
through the platform PermissionService. Only navigation/selection lives in
session_state - every player and asset is persisted by the service. A modern
club dashboard: searchable, filterable squad grid of player cards, a
professional Add-Player wizard, and a player profile (full tabs land in the
P-Profile milestone). Completely separate from the Scouting page.
"""
from __future__ import annotations

import datetime as _dt

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.capabilities import Capability
from fap.identity.roles import Role
from fap.players.analysis import age_from_dob
from fap.players.models import AVAILABILITY, FEET, POSITIONS, STATUSES
from fap.ui.page import Page, page_registry

SEL = "_ftp_id"            # selected first-team player
ADD = "_ftp_add"           # add-player wizard open flag

_AVAIL_BADGE = {"available": "🟢 Available", "doubtful": "🟡 Doubtful",
                "injured": "🔴 Injured", "suspended": "🟠 Suspended",
                "unavailable": "⚪ Unavailable"}


@page_registry.register
class FirstTeamPlayersPage(Page):
    info = PluginInfo(id="players", name="Players", category="page")
    section = "Squad"
    icon = "players"
    order = 5                      # first in the Squad section (before Scouting)
    min_role = Role.READ_ONLY      # view gated by capability below

    def render(self, shell) -> None:
        svc = getattr(shell.platform, "players", None) if shell.platform else None
        perms = getattr(shell.platform, "permissions", None) if shell.platform else None
        if svc is None or perms is None:
            st.info("First Team Players platform unavailable.")
            return
        if not perms.can(shell.user, str(Capability.VIEW_PLAYERS)):
            st.warning("You do not have permission to view players.")
            return
        self._can_edit = perms.can(shell.user, str(Capability.EDIT_PLAYERS))
        self._can_delete = perms.can(shell.user, str(Capability.DELETE_PLAYERS))
        self._can_medical = perms.can(shell.user, str(Capability.VIEW_MEDICAL))

        st.title("First Team")

        selected = st.session_state.get(SEL)
        if selected and svc.get_player(selected):
            self._profile(shell, svc, selected)
            return
        if st.session_state.get(ADD) and self._can_edit:
            self._wizard(shell, svc)
            return
        self._squad(shell, svc)

    # ---------------------------------------------------------------- squad
    def _squad(self, shell, svc) -> None:
        summary = svc.squad_summary(shell.user)
        top = st.columns([3, 1])
        with top[0]:
            m = st.columns(3)
            m[0].metric("Squad", summary["total"])
            m[1].metric("Injured", summary["injured"])
            m[2].metric("Archived", summary["archived"])
        with top[1]:
            if self._can_edit and st.button("➕ Add player", type="primary", key="ftp_addbtn"):
                st.session_state[ADD] = True
                st.rerun()

        side, grid = st.columns([1, 3])
        with side:
            st.caption("SEARCH & FILTER")
            query = st.text_input("Search (name / number / position)", key="ftp_q")
            opts = svc.filter_options(shell.user)

            def pick(label, col):
                choice = st.selectbox(label, ["All", *opts.get(col, [])], key=f"ftp_f_{col}")
                return "" if choice == "All" else choice

            position = pick("Position", "primary_position")
            nationality = pick("Nationality", "nationality")
            availability = pick("Availability", "availability")
            foot = pick("Preferred foot", "foot")
            status = pick("Status", "status")
            aa, ab = st.columns(2)
            min_age = aa.number_input("Min age", 14, 45, 14, key="ftp_minage")
            max_age = ab.number_input("Max age", 14, 45, 45, key="ftp_maxage")
            expiring = st.checkbox("Contract expiring (≤6 months)", key="ftp_exp")
            sort = st.selectbox("Sort by", ["Shirt number", "Name", "Position", "Age"], key="ftp_sort")

        filters = {k: v for k, v in (("primary_position", position), ("nationality", nationality),
                                     ("availability", availability), ("foot", foot),
                                     ("status", status)) if v}
        if min_age > 14:
            filters["min_age"] = min_age
        if max_age < 45:
            filters["max_age"] = max_age
        if expiring:
            soon = (_dt.date.today() + _dt.timedelta(days=180)).isoformat()
            filters["contract_expiring_before"] = soon
        players = svc.search(shell.user, query=query, filters=filters or None,
                             workspace_id=shell.workspace_id)
        players = self._sort(players, sort)

        with grid:
            if not players:
                st.info("No players match. Add players or adjust filters.")
                return
            index = svc.card_index(shell.user, players)
            cols = st.columns(3)
            for i, p in enumerate(players):
                with cols[i % 3]:
                    self._card(shell, svc, p, index.get(p.id, {}))

    @staticmethod
    def _sort(players, sort):
        key = {"Shirt number": lambda p: (p.shirt_number is None, p.shirt_number or 0),
               "Name": lambda p: p.name.lower(),
               "Position": lambda p: p.primary_position,
               "Age": lambda p: age_from_dob(p.dob) or 999}.get(sort)
        return sorted(players, key=key) if key else players

    def _card(self, shell, svc, p, agg) -> None:
        with st.container(border=True):
            photo = svc.image_bytes(p.profile_image_id) if p.profile_image_id else None
            c = st.columns([1, 2])
            with c[0]:
                if photo:
                    st.image(photo, use_container_width=True)
                else:
                    st.markdown(f"<div style='background:#e8edf2;border-radius:8px;height:64px;"
                                f"display:flex;align-items:center;justify-content:center;"
                                f"font-weight:700;color:#7a8aa0'>{self._initials(p)}</div>",
                                unsafe_allow_html=True)
            with c[1]:
                num = f"#{p.shirt_number}  " if p.shirt_number is not None else ""
                st.markdown(f"**{num}{p.name}**")
                age = age_from_dob(p.dob)
                st.caption(f"{p.primary_position or '—'} · {age if age is not None else '—'} · "
                           f"{p.nationality or '—'}")
            avail = "injured" if agg.get("injured") else p.availability
            badge = _AVAIL_BADGE.get(avail, avail.title() or "—")
            end = agg.get("contract_end") or "—"
            st.caption(f"{badge}  ·  ⏱ {agg.get('minutes', 0)} min  ·  📄 exp {end}")
            if st.button("Open profile", key=f"ftp_open_{p.id}"):
                st.session_state[SEL] = p.id
                st.rerun()

    @staticmethod
    def _initials(p) -> str:
        parts = (p.display_name or f"{p.first_name} {p.last_name}").split()
        return "".join(w[0] for w in parts[:2]).upper() or "?"

    # ---------------------------------------------------------------- wizard
    def _wizard(self, shell, svc) -> None:
        if st.button("← Back to squad", key="ftp_wiz_back"):
            st.session_state[ADD] = False
            st.rerun()
        st.subheader("Add player")
        st.caption("A professional 5-step intake. Fields you skip can be added later on the profile.")
        with st.form("ftp_wizard", clear_on_submit=False):
            st.markdown("**Step 1 — Basic information**")
            a, b, c = st.columns(3)
            first = a.text_input("First name")
            last = b.text_input("Last name")
            display = c.text_input("Display name")
            d, e, f = st.columns(3)
            number = d.number_input("Shirt number", 0, 99, 0)
            dob = e.text_input("Date of birth (YYYY-MM-DD)")
            nationality = f.text_input("Nationality")
            g, h, i = st.columns(3)
            foot = g.selectbox("Preferred foot", FEET, format_func=lambda x: x.title() or "—")
            primary = h.selectbox("Primary position", ["", *POSITIONS])
            secondary = i.multiselect("Secondary positions", POSITIONS)
            j, k = st.columns(2)
            height = j.number_input("Height (cm)", 0, 220, 0)
            weight = k.number_input("Weight (kg)", 0, 130, 0)

            st.markdown("**Step 2 — Club information**")
            l, m, n = st.columns(3)
            join_date = l.text_input("Join date (YYYY-MM-DD)")
            c_start = m.text_input("Contract start (YYYY-MM-DD)")
            c_end = n.text_input("Contract end (YYYY-MM-DD)")
            o, q, r = st.columns(3)
            salary = o.number_input("Salary (optional)", 0.0, step=1000.0)
            market = q.number_input("Market value (optional)", 0.0, step=100000.0)
            loan = r.checkbox("On loan")
            s, t = st.columns(2)
            captain = s.checkbox("Captain")
            vice = t.checkbox("Vice-captain")

            st.markdown("**Step 3 — Medical**")
            u, v = st.columns(2)
            injury = u.text_input("Current injury (optional)")
            availability = v.selectbox("Availability", AVAILABILITY)
            med_notes = st.text_area("Medical notes (optional)", height=68)

            st.markdown("**Step 4 — Media**")
            photo = st.file_uploader("Player image", type=["png", "jpg", "jpeg", "webp"])
            video_url = st.text_input("Video link (optional)")

            st.markdown("**Step 5 — Performance (optional)**")
            aa, ab, ac = st.columns(3)
            season = aa.text_input("Season")
            competition = ab.text_input("Competition")
            apps = ac.number_input("Appearances", 0, 100, 0)

            if st.form_submit_button("Create player", type="primary"):
                self._create(shell, svc, dict(
                    first_name=first, last_name=last, display_name=display,
                    shirt_number=(int(number) or None), dob=dob, nationality=nationality,
                    foot=foot, primary_position=primary, secondary_positions=list(secondary),
                    height=(int(height) or None), weight=(int(weight) or None),
                    join_date=join_date, captain=captain, vice_captain=vice,
                    availability=availability,
                ), c_start, c_end, salary, market, loan, injury, med_notes, availability,
                    photo, video_url, season, competition, int(apps))

    def _create(self, shell, svc, base, c_start, c_end, salary, market, loan, injury, med_notes,
                availability, photo, video_url, season, competition, apps) -> None:
        try:
            p = svc.create_player(shell.user, workspace_id=shell.workspace_id, **base)
            if c_start or c_end or salary or market:
                svc.add_contract(shell.user, p.id, contract_start=c_start, contract_end=c_end,
                                 salary=(salary or None), market_value=(market or None), loan=loan)
            if injury and self._can_medical:
                svc.add_medical(shell.user, p.id, injury=injury, status="open",
                                availability="injured", medical_notes=med_notes)
            if photo is not None:
                svc.add_image(shell.user, p.id, photo.getvalue(), photo.type or "image/png",
                              kind="profile")
            if video_url:
                svc.add_video(shell.user, p.id, url=video_url, kind="external")
            if season or apps:
                svc.add_career(shell.user, p.id, season=season, competition=competition,
                               appearances=apps)
            st.success(f"Created {p.name}.")
            st.session_state[ADD] = False
            st.session_state[SEL] = p.id
            st.rerun()
        except Exception as exc:
            st.error(f"Could not create player: {exc}")

    # ---------------------------------------------------------------- profile (foundation)
    def _profile(self, shell, svc, player_id) -> None:
        if st.button("← Back to squad", key="ftp_prof_back"):
            st.session_state.pop(SEL, None)
            st.rerun()
        ov = svc.overview(shell.user, player_id)
        p = ov["player"]
        head = st.columns([1, 3])
        with head[0]:
            photo = svc.image_bytes(p.profile_image_id) if p.profile_image_id else None
            if photo:
                st.image(photo, use_container_width=True)
            else:
                st.markdown(f"<div style='background:#e8edf2;border-radius:10px;height:120px;"
                            f"display:flex;align-items:center;justify-content:center;font-size:2rem;"
                            f"font-weight:700;color:#7a8aa0'>{self._initials(p)}</div>",
                            unsafe_allow_html=True)
        with head[1]:
            num = f"#{p.shirt_number} · " if p.shirt_number is not None else ""
            cap = " (C)" if p.captain else (" (VC)" if p.vice_captain else "")
            st.subheader(f"{num}{p.name}{cap}")
            st.caption(f"{p.primary_position or '—'} · {ov['age'] if ov['age'] is not None else '—'} yrs "
                       f"· {p.nationality or '—'} · {p.foot.title() or '—'} foot")
            st.markdown(f"**{ov['availability']}**")

        k = st.columns(4)
        c = ov["contract"]
        k[0].metric("Contract ends", (c.contract_end if c and c.contract_end else "—"))
        k[1].metric("Career minutes", ov["career_totals"]["minutes"])
        k[2].metric("Goals", ov["career_totals"]["goals"])
        k[3].metric("Assists", ov["career_totals"]["assists"])
        if ov.get("injury"):
            st.warning(f"Injury: {ov['injury'].injury} — expected return "
                       f"{ov['injury'].expected_return or 'TBD'}")
        st.caption("Full profile tabs (Overview / Stats / Analysis / Charts / Reports / Medical / "
                   "Training / Videos / Career / Matches / Settings) arrive in the P-Profile milestone.")

        if self._can_edit or self._can_delete:
            with st.expander("Settings"):
                if self._can_edit and st.button("Archive player", key="ftp_arch"):
                    svc.archive_player(shell.user, player_id)
                    st.session_state.pop(SEL, None)
                    st.rerun()
                if self._can_delete and st.button("Delete player", key="ftp_del"):
                    svc.delete_player(shell.user, player_id)
                    st.session_state.pop(SEL, None)
                    st.rerun()
