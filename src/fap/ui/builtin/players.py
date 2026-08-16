"""First Team Players - our squad workspace (Phase 10 · P-Foundation).

A thin view over ``PlayersService``: no business logic here. Capability-gated
through the platform PermissionService. Only navigation/selection lives in
session_state - every player and asset is persisted by the service. A modern
club dashboard: searchable, filterable squad grid of player cards, a
professional Add-Player wizard, and a player profile (full tabs land in the
P-Profile milestone). Completely separate from the Scouting page.
"""
from __future__ import annotations

import base64
import datetime as _dt
import html as _html

import streamlit as st

from fap.core.plugin import PluginInfo
from fap.identity.capabilities import Capability
from fap.identity.roles import Role
from fap.players.analysis import age_from_dob
from fap.players.models import AVAILABILITY, FEET, POSITIONS, STATUSES
from fap.theme import components as C
from fap.theme import icon
from fap.ui.page import Page, page_registry

SEL = "_ftp_id"            # selected first-team player
ADD = "_ftp_add"           # add-player wizard open flag
OPEN_REPORT = "_open_report_id"   # Report Studio navigation key (reused)


def _avail_badge(avail: str) -> str:
    """Availability -> unified status-badge HTML (one squad-status vocabulary)."""
    return C.status_badge_html(avail or "unavailable")


def _photo_uri(svc, image_id) -> str:
    """A data: URI for a stored player image, or '' when there is none, so the
    pure card builders can embed a photo without touching storage themselves."""
    if not image_id:
        return ""
    raw = svc.image_bytes(image_id)
    if not raw:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


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
        self._can_report = perms.can(shell.user, str(Capability.CREATE_REPORT))

        C.render_section_title(
            "First Team", eyebrow="Squad",
            subtitle="Your first-team squad — search, filter and open any player.",
            icon_name="players")

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
        available = max(0, summary["total"] - summary["injured"] - summary["archived"])
        top = st.columns([3, 1], vertical_alignment="center")
        with top[0]:
            C.render_metric_row([
                C.metric_card_html("Squad", str(summary["total"]), icon_name="players",
                                   accent="primary", hint="registered players"),
                C.metric_card_html("Available", str(available), icon_name="heart",
                                   accent="success", hint="fit to play"),
                C.metric_card_html("Injured", str(summary["injured"]), icon_name="cross-medical",
                                   accent="danger", hint="in treatment"),
                C.metric_card_html("Archived", str(summary["archived"]), icon_name="folder",
                                   accent="info", hint="not in squad"),
            ])
        with top[1]:
            if self._can_edit and st.button("Add player", type="primary", key="ftp_addbtn",
                                            use_container_width=True):
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
            foot = pick("Preferred foot", "foot")
            aa, ab = st.columns(2)
            min_age = aa.number_input("Min age", 14, 45, 14, key="ftp_minage")
            max_age = ab.number_input("Max age", 14, 45, 45, key="ftp_maxage")
            st.caption("STATUS")
            f1, f2 = st.columns(2)
            injured = f1.checkbox("Injured", key="ftp_inj")
            suspended = f2.checkbox("Suspended", key="ftp_susp")
            loan = f1.checkbox("On loan", key="ftp_loan")
            expiring = f2.checkbox("Expiring", key="ftp_exp")
            captain = f1.checkbox("Captain", key="ftp_cap")
            vice = f2.checkbox("Vice-captain", key="ftp_vice")
            st.caption("SQUAD TYPE")
            g1, g2 = st.columns(2)
            academy = g1.checkbox("Academy graduate", key="ftp_acad")
            homegrown = g2.checkbox("Homegrown", key="ftp_hg")
            foreign = g1.checkbox("Foreign", key="ftp_for")
            sort = st.selectbox("Sort by", ["Shirt number", "Name", "Position", "Age"], key="ftp_sort")

        status = ("injured" if injured else "suspended" if suspended else "loan" if loan else "")
        filters = {k: v for k, v in (("primary_position", position), ("nationality", nationality),
                                     ("foot", foot), ("status", status)) if v}
        if min_age > 14:
            filters["min_age"] = min_age
        if max_age < 45:
            filters["max_age"] = max_age
        if expiring:
            filters["contract_expiring_before"] = (_dt.date.today() + _dt.timedelta(days=180)).isoformat()
        if captain:
            filters["captain"] = True
        if vice:
            filters["vice_captain"] = True
        players = svc.search(shell.user, query=query, filters=filters or None,
                             workspace_id=shell.workspace_id)
        # document-flag filters (Academy/U21/Women-ready) applied in Python
        if academy:
            players = [p for p in players if p.document.get("academy_graduate")]
        if homegrown:
            players = [p for p in players if p.document.get("homegrown")]
        if foreign:
            players = [p for p in players if p.document.get("foreign") or
                       (p.nationality and not p.document.get("homegrown"))]
        players = self._sort(players, sort)

        with grid:
            view = st.radio("View", ["Grid", "List", "Table"], horizontal=True, key="ftp_view",
                            label_visibility="collapsed")
            if not players:
                add = C.render_empty_state(
                    "No players match", "Adjust the filters on the left, or add your first "
                    "player to start building the squad.", icon_name="players",
                    action_label=("Add player" if self._can_edit else ""), key="ftp_empty_add")
                if add:
                    st.session_state[ADD] = True
                    st.rerun()
                return
            index = svc.card_index(shell.user, players)
            if view == "Table":
                self._table(players, index)
            elif view == "List":
                for p in players:
                    self._list_row(shell, svc, p, index.get(p.id, {}))
            else:
                cols = st.columns(3)
                for i, p in enumerate(players):
                    with cols[i % 3]:
                        self._card(shell, svc, p, index.get(p.id, {}))

    def _list_row(self, shell, svc, p, agg) -> None:
        with st.container(border=True):
            c = st.columns([1, 3, 2, 1], vertical_alignment="center")
            photo = svc.image_bytes(p.profile_image_id) if p.profile_image_id else None
            if photo:
                c[0].image(photo, use_container_width=True)
            else:
                c[0].markdown(C.avatar_html(initials=self._initials(p), size=46),
                              unsafe_allow_html=True)
            num = f"#{p.shirt_number} " if p.shirt_number is not None else ""
            c[1].markdown(f"**{num}{p.name}**  \n{p.primary_position or '—'} · "
                          f"{age_from_dob(p.dob) or '—'} · {p.nationality or '—'}")
            avail = "injured" if agg.get("injured") else p.availability
            c[2].markdown(
                f"{_avail_badge(avail)}<br><span style='color:var(--fap-text-muted);font-size:.8rem'>"
                f"{icon('clock', 13)} {agg.get('minutes', 0)} min &nbsp; "
                f"{icon('calendar', 13)} {agg.get('contract_end') or '—'}</span>",
                unsafe_allow_html=True)
            if c[3].button("Open", key=f"ftp_lopen_{p.id}", use_container_width=True):
                st.session_state[SEL] = p.id
                st.rerun()

    @staticmethod
    def _table(players, index) -> None:
        rows = []
        for p in players:
            agg = index.get(p.id, {})
            rows.append({"#": p.shirt_number, "Name": p.name, "Pos": p.primary_position,
                         "Age": age_from_dob(p.dob), "Nat": p.nationality, "Foot": p.foot,
                         "Availability": ("Injured" if agg.get("injured") else p.availability),
                         "Minutes": agg.get("minutes", 0), "Contract": agg.get("contract_end") or "—"})
        st.dataframe(rows, use_container_width=True, hide_index=True)

    @staticmethod
    def _sort(players, sort):
        key = {"Shirt number": lambda p: (p.shirt_number is None, p.shirt_number or 0),
               "Name": lambda p: p.name.lower(),
               "Position": lambda p: p.primary_position,
               "Age": lambda p: age_from_dob(p.dob) or 999}.get(sort)
        return sorted(players, key=key) if key else players

    def _card(self, shell, svc, p, agg) -> None:
        avail = "injured" if agg.get("injured") else p.availability
        age = age_from_dob(p.dob)
        st.markdown(C.player_card_html(
            p.name, number=(p.shirt_number if p.shirt_number is not None else None),
            position=p.primary_position or "", nationality=p.nationality or "",
            age=(f"{age} yrs" if age is not None else ""),
            contract=(f"exp {agg.get('contract_end')}" if agg.get("contract_end") else ""),
            minutes=(f"{agg.get('minutes', 0)} min"),
            photo_uri=_photo_uri(svc, p.profile_image_id),
            status=avail, captain=bool(p.captain)), unsafe_allow_html=True)
        if st.button("Open profile", key=f"ftp_open_{p.id}", use_container_width=True):
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

    # ---------------------------------------------------------------- profile hub
    def _profile(self, shell, svc, player_id) -> None:
        if st.button("← Back to squad", key="ftp_prof_back"):
            st.session_state.pop(SEL, None)
            st.rerun()
        ov = svc.overview(shell.user, player_id)
        p = ov["player"]
        self._header(svc, p, ov)

        tabs = st.tabs(["Overview", "Analysis", "Statistics", "Visualization", "Career", "Matches",
                        "Training", "Medical", "Videos", "Reports", "Settings"])
        with tabs[0]:
            self._tab_overview(shell, svc, player_id, ov)
        with tabs[1]:
            self._tab_analysis(shell, svc, player_id, ov)
        with tabs[2]:
            self._tab_statistics(shell, svc, player_id)
        with tabs[3]:
            self._tab_visualization(shell, svc, player_id, p)
        with tabs[4]:
            self._tab_career(shell, svc, player_id)
        with tabs[5]:
            self._tab_matches(shell, svc, player_id)
        with tabs[6]:
            self._tab_training(shell, svc, player_id)
        with tabs[7]:
            self._tab_medical(shell, svc, player_id)
        with tabs[8]:
            self._tab_videos(shell, svc, player_id)
        with tabs[9]:
            self._tab_reports(shell, svc, player_id)
        with tabs[10]:
            self._tab_settings(shell, svc, player_id, p)

    # ---- Visualization workspace (reuses the shared player-scoped viz engine) ----
    def _tab_visualization(self, shell, svc, player_id, p) -> None:
        """First-team player performance analysis. When a player-scouting metric
        dataset is LINKED (resolved by dataset_id, never the active dataset), the
        shared player-scoped workspace (Metric Explorer / Pizza / Radar / Bar /
        Scatter / Squad context) renders it with Save-to-Player; otherwise the event
        visualization engine is used. Saved charts appear in Visual Evidence below."""
        C.render_section_title("Performance Analysis", eyebrow="Player Data",
                               subtitle="Metric analysis from the player's linked dataset — "
                               "independent of whatever dataset is globally active.",
                               icon_name="analysis")
        linked = svc.linked_player_scouting_datasets(shell.user, player_id)
        if linked:
            ids = [d["dataset_id"] for d in linked]
            names = {d["dataset_id"]: d for d in linked}
            if len(ids) > 1:
                chosen = st.selectbox(
                    "Analysis source", ids, key=f"ftviz_ds_{player_id}",
                    format_func=lambda i: f"{names[i]['name']} · {names[i]['metric_count']} metrics"
                    + ("" if names[i]["linked"] else " · (active, not linked)"))
            else:
                chosen = ids[0]
                d0 = names[chosen]
                st.caption(f"{icon('datasets', 13)} Analysis source: **{d0['name']}** · "
                           f"{d0['metric_count']} metrics"
                           + ("" if d0["linked"] else " · active (not linked yet)"),
                           unsafe_allow_html=True)
            if not names[chosen]["linked"] and self._can_edit:
                if st.button("Link this dataset to the player", key=f"ftviz_link_{player_id}"):
                    ctx0 = svc.player_viz_context(shell.user, player_id, chosen)
                    if ctx0:
                        svc.link_dataset_identity(shell.user, player_id, ctx0["primary"],
                                                  dataset_id=chosen, method="manual")
                        st.rerun()
            ctx = svc.player_viz_context(shell.user, player_id, chosen)
            if ctx is None:
                C.render_alert("The linked dataset is unavailable or the player row could not be "
                               "resolved. Saved visual evidence remains available below.", "warning")
            else:
                from fap.ui.components.scouting_viz_workspace import render_scouting_viz_workspace
                render_scouting_viz_workspace(shell, svc, p, ctx, key=f"ftp_pviz_{player_id}",
                                              allow_save=self._can_edit)
        else:
            # no linked metric dataset: the existing event visualization workspace
            from fap.ui.components.viz_workspace import render_visualization_workspace
            frame = svc.player_event_frame(shell.user, player_id)
            render_visualization_workspace(shell, frame=frame, player_name=p.name,
                                           key=f"ftp_viz_{player_id}")
            st.caption("Link a player-metric dataset (Data Hub → activate → link here) for "
                       "Pizza / Radar / Bar / Scatter and Save-to-Player.")
        st.divider()
        self._visual_evidence_section(shell, svc, player_id, p)

    def _visual_evidence_section(self, shell, svc, player_id, p) -> None:
        """Saved player visualizations — immutable PNG assets that carry their source
        dataset + single-player scope, available regardless of the active dataset, a
        later dataset switch, reload, or the source dataset disappearing."""
        assets = svc.list_player_visualizations(player_id)
        C.render_dossier_label(f"Visual evidence ({len(assets)})", icon=icon("grid", 13))
        if not assets:
            st.caption("No saved visualizations yet. Render a chart above and click "
                       "**Save to player** — it is stored permanently against this player.")
            return
        active = ""
        try:
            ad = shell.wm.active_dataset(shell.user)
            active = ad.id if ad else ""
        except Exception:
            active = ""
        cols = st.columns(3)
        for i, a in enumerate(reversed(assets)):
            with cols[i % 3]:
                png = svc.player_visualization_bytes(player_id, a["id"])
                if png:
                    st.image(png, use_container_width=True)
                scope = a.get("scope", {}).get("player") or []
                st.caption(f"**{_html.escape(a.get('title', 'Visualization'))}**")
                src = a.get("source_dataset_name") or "dataset"
                gone = False
                if a.get("dataset_id"):
                    try:
                        gone = shell.wm.get_dataset(a["dataset_id"]) is None
                    except Exception:
                        gone = False
                st.caption(f"{_html.escape(src)}"
                           + (" · source unavailable — saved chart remains" if gone else "")
                           + (f" · Scope: {_html.escape(', '.join(map(str, scope)))}" if scope else ""))
                if self._can_edit and st.button("Remove", key=f"ftvz_del_{player_id}_{a['id']}"):
                    svc.delete_player_visualization(shell.user, player_id, a["id"]); st.rerun()

    # ---- professional header -------------------------------------------
    def _header(self, svc, p, ov) -> None:
        with st.container(border=True):
            head = st.columns([1, 3, 2], vertical_alignment="center")
            with head[0]:
                photo = svc.image_bytes(p.profile_image_id) if p.profile_image_id else None
                if photo:
                    st.image(photo, use_container_width=True)
                else:
                    st.markdown(C.avatar_html(initials=self._initials(p), size=104),
                                unsafe_allow_html=True)
            with head[1]:
                num = (f'<span class="fap-badge neutral">#{p.shirt_number}</span>'
                       if p.shirt_number is not None else "")
                role = (C.status_badge_html("captain") if p.captain
                        else C.status_badge_html("vice") if p.vice_captain else "")
                avail = "injured" if ov.get("injury") else p.availability
                flag = (p.flag + " ") if p.flag else ""
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px">'
                    f'{num}{role}'
                    f'<span style="font-size:1.5rem;font-weight:800;letter-spacing:-.02em">{p.name}</span>'
                    f'</div>'
                    f'<div style="color:var(--fap-text-muted);font-size:.86rem;margin-bottom:6px">'
                    f'{icon("map-pin",13)} {p.primary_position or "—"} &nbsp; '
                    f'{icon("flag",13)} {flag}{p.nationality or "—"} &nbsp; '
                    f'{icon("user",13)} {ov["age"] if ov["age"] is not None else "—"} yrs &nbsp; '
                    f'{icon("target",13)} {p.foot.title() or "—"} foot</div>'
                    f'{_avail_badge(avail)}', unsafe_allow_html=True)
            with head[2]:
                c = ov["contract"]
                st.metric("Career minutes", ov["career_totals"]["minutes"])
                st.metric("Contract ends", (c.contract_end if c and c.contract_end else "—"))

    # ---- Overview (live dashboard) --------------------------------------
    def _tab_overview(self, shell, svc, player_id, ov) -> None:
        c = ov["contract"]
        wl = ov["workload"]
        r1 = st.columns(4)
        r1[0].metric("Availability", ov["availability"])
        r1[1].metric("Medical", ov["medical_status"])
        r1[2].metric("Training", ov["training_status"])
        r1[3].metric("Contract ends", (c.contract_end if c and c.contract_end else "—"))
        r2 = st.columns(4)
        r2[0].metric("Career minutes", ov["career_totals"]["minutes"])
        r2[1].metric("Goals", ov["career_totals"]["goals"])
        r2[2].metric("Assists", ov["career_totals"]["assists"])
        r2[3].metric("Matches linked", ov["matches"])
        st.subheader("Workload")
        w = st.columns(4)
        w[0].metric("Load 7d", wl["load_7d"]); w[1].metric("Load 28d", wl["load_28d"])
        w[2].metric("Sprint 7d", wl["sprint_7d"]); w[3].metric("Sessions 7d", wl["sessions_7d"])
        cc = st.columns(2)
        with cc[0]:
            st.subheader("Recent form")
            form = ov["recent_form"]
            if form:
                st.dataframe([{"Availability": f["availability"] or "—", "Role": f["role"] or "—",
                               "Minutes": f["minutes"]} for f in form],
                             use_container_width=True, hide_index=True)
            else:
                st.caption("No linked matches yet.")
        with cc[1]:
            st.subheader("Fixtures")
            lm = ov["last_match"]
            st.markdown(f"**Last match:** {('%d min · %s' % (lm.minutes or 0, lm.role or '—')) if lm else '—'}")
            st.markdown("**Next match:** — (fixtures feed not connected)")
        if ov.get("injury"):
            st.warning(f"Current injury: {ov['injury'].injury} — expected return "
                       f"{ov['injury'].expected_return or 'TBD'}")
        st.subheader("Timeline")
        self._timeline(svc, shell, player_id)

    _TL_STYLE = {"signing": ("edit", "info"), "contract": ("calendar", "neutral"),
                 "loan": ("link", "info"), "injury": ("cross-medical", "danger"),
                 "recovery": ("check", "success"), "match": ("match", "neutral"),
                 "video": ("video", "info"), "award": ("trophy", "warning"),
                 "report": ("reports", "success")}

    def _timeline(self, svc, shell, player_id) -> None:
        events = svc.timeline(shell.user, player_id)
        if not events:
            st.caption("No timeline events yet.")
            return
        rows = []
        for e in events[:40]:
            icon_name, kind = self._TL_STYLE.get(e["type"], ("info", "neutral"))
            badge = C.badge_html(e["type"].title(), kind, icon_name=icon_name)
            rows.append(
                f"<div class='fap-activity-row'>{badge}"
                f"<span class='who'>{e['label']}</span>"
                f"<span class='ts'>{e['date'] or '—'}</span></div>")
        st.markdown(f"<div class='fap-card fap-activity'>{''.join(rows)}</div>",
                    unsafe_allow_html=True)

    # ---- Analysis (central hub, reuses existing modules) ----------------
    def _tab_analysis(self, shell, svc, player_id, ov) -> None:
        st.caption("Central analysis hub — professional module cards. Every card opens an existing module; "
                   "nothing is recomputed here.")
        cards = svc.analysis_hub(shell.user, player_id)
        cols = st.columns(2)
        for i, card in enumerate(cards):
            with cols[i % 2]:
                with st.container(border=True):
                    st.markdown(f"### {card['name']}")
                    st.caption(card["desc"])
                    g = st.columns(2)
                    g[0].metric("Datasets", card["datasets"])
                    g[1].metric("Reports", card["reports"])
                    st.caption(f"Last analysis: **{card['last_analysis']}**  ·  "
                               f"Last update: **{card['last_update']}**")
                    if st.button(f"Open {card['name']}", key=f"an_{card['page_id']}_{i}"):
                        try:
                            shell.goto(card["page_id"])
                        except Exception:
                            st.info("Open this module from the navigation.")
        st.subheader("Physical & GPS")
        wl = ov["workload"]
        g = st.columns(4)
        g[0].metric("Load 7d", wl["load_7d"]); g[1].metric("Load 28d", wl["load_28d"])
        g[2].metric("Sprint 7d", wl["sprint_7d"]); g[3].metric("HSR 7d", wl["hsr_7d"])
        st.caption("GPS / physical figures are drawn from the Training tab data.")
        st.subheader("Medical & Training")
        st.markdown(f"Medical status: **{ov['medical_status']}** · Training status: **{ov['training_status']}**")

    # ---- Statistics (reuse analytics + dynamic charts) ------------------
    def _tab_statistics(self, shell, svc, player_id) -> None:
        st.caption("Career statistics are always shown from the stored figures; charts render linked match "
                   "data through the existing visualization engine (chart list pulled live from the registry).")
        totals = svc.career_totals(player_id)
        st.subheader("Career statistics")
        k = st.columns(7)
        k[0].metric("Apps", totals["appearances"]); k[1].metric("Starts", totals["starts"])
        k[2].metric("Minutes", totals["minutes"]); k[3].metric("Goals", totals["goals"])
        k[4].metric("Assists", totals["assists"]); k[5].metric("Yellow", totals["yellow"])
        k[6].metric("Red", totals["red"])
        career = svc.list_career(player_id)
        if career:
            st.dataframe([{"Season": c.season, "Competition": c.competition, "Apps": c.appearances,
                           "Goals": c.goals, "Assists": c.assists, "Minutes": c.minutes,
                           "Yellow": c.yellow, "Red": c.red} for c in career],
                         use_container_width=True, hide_index=True)
        else:
            st.info("No career statistics recorded yet.")
        st.subheader("Charts")
        src = svc.player_data_source(shell.user, player_id)
        if src["active"]:
            st.caption(f"{icon('datasets', 13)} Charts render from the active dataset "
                       f"**{src['active_name']}**" + (f" + {src['linked']} linked" if src['linked'] else "")
                       + " through the existing visualization engine.", unsafe_allow_html=True)
        elif src["linked"]:
            st.caption(f"Charts render from {src['linked']} linked dataset(s). "
                       "Choose an active dataset in the Data Hub to analyze more.")
        try:
            catalog = svc.available_visualizations(shell.user)
        except Exception as exc:
            st.caption(f"Visualization registry unavailable: {exc}")
            return
        cats = sorted({v["category"] for v in catalog})
        a, b, c = st.columns([2, 2, 1])
        cat = a.selectbox("Category", cats, key="ftp_chart_cat")
        in_cat = [v for v in catalog if v["category"] == cat]
        viz = b.selectbox("Visualization", in_cat, format_func=lambda v: v["name"], key="ftp_chart_viz")
        themes = ["opta_light", "opta_dark"]
        theme = c.selectbox("Theme", themes, key="ftp_chart_theme")
        if st.button("Render chart", key="ftp_chart_render"):
            png = svc.render_player_chart(shell.user, player_id, viz["id"], theme_id=theme)
            if png:
                st.image(png, use_container_width=True)
            elif svc.player_data_source(shell.user, player_id)["active"] or \
                    svc.player_data_source(shell.user, player_id)["linked"]:
                st.info(f"No events for this player in the current data. This chart may not apply, "
                        f"or the player's name may differ in the dataset.")
            else:
                st.info("No match data yet. Choose an active dataset in the **Data Hub**, or link a "
                        "dataset in the **Matches** tab, then render charts here.")

    # ---- Career --------------------------------------------------------
    def _tab_career(self, shell, svc, player_id) -> None:
        career = svc.list_career(player_id)
        if career:
            st.dataframe([{"Season": c.season, "Club": c.club, "Competition": c.competition,
                           "Apps": c.appearances, "Goals": c.goals, "Assists": c.assists,
                           "Minutes": c.minutes} for c in career],
                         use_container_width=True, hide_index=True)
        else:
            st.info("No career history yet.")
        if self._can_edit:
            with st.expander("Add career row"):
                with st.form("ftp_career", clear_on_submit=True):
                    a, b, c = st.columns(3)
                    season = a.text_input("Season"); club = b.text_input("Club")
                    comp = c.text_input("Competition")
                    d, e, f, g = st.columns(4)
                    apps = d.number_input("Apps", 0, 100, 0); goals = e.number_input("Goals", 0, 100, 0)
                    ass = f.number_input("Assists", 0, 100, 0); mins = g.number_input("Minutes", 0, 10000, 0)
                    if st.form_submit_button("Add"):
                        svc.add_career(shell.user, player_id, season=season, club=club, competition=comp,
                                       appearances=int(apps), goals=int(goals), assists=int(ass),
                                       minutes=int(mins))
                        st.rerun()

    # ---- Matches (link-only, rich presentation) ------------------------
    def _tab_matches(self, shell, svc, player_id) -> None:
        rows = svc.match_rows(shell.user, player_id)
        if rows:
            for i, r in enumerate(rows):
                with st.container(border=True):
                    c = st.columns([3, 2, 1, 1, 2])
                    c[0].markdown(f"**vs {r['opponent']}**  \n{r['competition']}")
                    c[1].markdown(f"{icon('calendar', 13)} {r['date']}  \n{r['season']}",
                                  unsafe_allow_html=True)
                    c[2].metric("Min", r["minutes"] if r["minutes"] is not None else "—")
                    c[3].markdown(f"**{r['result']}**  \n{r['role'] or '—'}")
                    with c[4]:
                        if r["dataset_id"] and st.button("Open Analysis", key=f"ftp_ma_{i}"):
                            try:
                                shell.goto("opponent_analysis")
                            except Exception:
                                st.info("Open Opponent Analysis from the navigation.")
            st.caption("Match statistics come from the linked datasets — never duplicated here.")
        else:
            st.info("No matches linked. Match data is never duplicated here — link an existing dataset below.")
        if self._can_edit:
            with st.expander("Link a match / dataset"):
                with st.form("ftp_link", clear_on_submit=True):
                    a, b = st.columns(2)
                    dataset_id = a.text_input("Dataset id")
                    minutes = b.number_input("Minutes", 0, 130, 90)
                    role = st.text_input("Role / position")
                    if st.form_submit_button("Link match"):
                        svc.link_match(shell.user, player_id, dataset_id=dataset_id,
                                       minutes=int(minutes), role=role)
                        st.rerun()

    # ---- Training ------------------------------------------------------
    def _tab_training(self, shell, svc, player_id) -> None:
        sessions = svc.list_training(player_id)
        if sessions:
            st.dataframe([{"Date": t.date, "Attendance": t.attendance, "Load": t.load, "RPE": t.rpe,
                           "Sprint": t.sprint_distance, "HSR": t.hsr, "Wellness": t.wellness}
                          for t in sessions], use_container_width=True, hide_index=True)
        else:
            st.info("No training sessions recorded (GPS/load can be imported in P-Import).")
        if self._can_edit:
            with st.expander("Add training session"):
                with st.form("ftp_train", clear_on_submit=True):
                    a, b, c = st.columns(3)
                    date = a.text_input("Date (YYYY-MM-DD)")
                    attendance = b.selectbox("Attendance", ["present", "partial", "absent", "rest"])
                    load = c.number_input("Load", 0.0, 2000.0, 0.0)
                    d, e, f = st.columns(3)
                    rpe = d.number_input("RPE", 0.0, 10.0, 0.0)
                    sprint = e.number_input("Sprint distance", 0.0, 2000.0, 0.0)
                    wellness = f.number_input("Wellness", 0.0, 10.0, 0.0)
                    if st.form_submit_button("Add"):
                        svc.add_training(shell.user, player_id, date=date, attendance=attendance,
                                         load=load, rpe=rpe, sprint_distance=sprint, wellness=wellness)
                        st.rerun()

    # ---- Medical (gated) -----------------------------------------------
    def _tab_medical(self, shell, svc, player_id) -> None:
        if not self._can_medical:
            st.warning("You do not have permission to view medical records (VIEW_MEDICAL).")
            return
        records = svc.list_medical(shell.user, player_id)
        if records:
            st.dataframe([{"Date": m.date, "Injury": m.injury, "Type": m.injury_type,
                           "Status": m.status, "Return": m.expected_return, "Severity": m.severity}
                          for m in records], use_container_width=True, hide_index=True)
        else:
            st.success("No medical records — player has no logged injuries.")
        if self._can_edit:
            with st.expander("Log injury / update"):
                with st.form("ftp_med", clear_on_submit=True):
                    a, b = st.columns(2)
                    injury = a.text_input("Injury"); itype = b.text_input("Type")
                    c, d, e = st.columns(3)
                    date = c.text_input("Date (YYYY-MM-DD)")
                    ret = d.text_input("Expected return")
                    status = e.selectbox("Status", ["open", "recovering", "returned"])
                    notes = st.text_area("Medical notes", height=68)
                    if st.form_submit_button("Save"):
                        svc.add_medical(shell.user, player_id, injury=injury, injury_type=itype,
                                        date=date, expected_return=ret, status=status,
                                        availability="injured", medical_notes=notes)
                        st.rerun()

    # ---- Videos (grouped timeline) -------------------------------------
    def _tab_videos(self, shell, svc, player_id) -> None:
        videos = svc.list_videos(player_id)
        groups = {"training": "Training", "match": "Matches", "tagged": "Tagged clips",
                  "coach": "Coach clips", "opponent": "Opponent clips", "external": "External"}
        by_kind = {k: [v for v in videos if v.kind == k] for k in groups}
        for k, label in groups.items():
            items = by_kind[k]
            if items:
                st.markdown(f"**{label}**")
                for v in items:
                    link = f"[{v.title or v.url}]({v.url})" if v.url else (v.title or v.filename)
                    st.markdown(f"{icon('video', 13)} {link}", unsafe_allow_html=True)
        if not videos:
            st.info("No videos yet.")
        if self._can_edit:
            with st.expander("Add video"):
                with st.form("ftp_vid", clear_on_submit=True):
                    a, b = st.columns(2)
                    kind = a.selectbox("Group", list(groups), format_func=lambda k: groups[k])
                    title = b.text_input("Title")
                    url = st.text_input("Link (YouTube / Hudl / Veo / …)")
                    if st.form_submit_button("Add"):
                        svc.add_video(shell.user, player_id, url=url, kind=kind, title=title)
                        st.rerun()

    # ---- Reports (ReportsManager) --------------------------------------
    def _tab_reports(self, shell, svc, player_id) -> None:
        data = svc.player_reports(shell.user, player_id)
        if data["pinned"]:
            C.render_section_title("Pinned", icon_name="pin")
            for r in data["pinned"]:
                self._report_row(shell, svc, player_id, r)
        C.render_section_title("Recent", icon_name="reports")
        recent = [r for r in data["reports"] if not r["pinned"]]
        if recent:
            for r in recent[:10]:
                self._report_row(shell, svc, player_id, r)
        elif not data["pinned"]:
            C.render_empty_state("No reports yet", "Create a report or generate a performance "
                                 "report to see it here.", icon_name="reports")
        if self._can_report:
            a, b = st.columns(2)
            if a.button("Create report", key="ftp_rep_create", use_container_width=True):
                self._make_report(shell, svc, player_id, generate=False)
            if b.button("Generate performance report", key="ftp_rep_gen", type="primary",
                        use_container_width=True):
                self._make_report(shell, svc, player_id, generate=True)

    def _make_report(self, shell, svc, player_id, generate) -> None:
        try:
            rec = svc.create_player_report(shell.user, player_id, generate=generate)
            st.session_state[OPEN_REPORT] = rec.id
            st.success(f"{'Generated' if generate else 'Created'} “{rec.title}”. Open in Report Studio.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not create report: {exc}")

    def _report_row(self, shell, svc, player_id, r) -> None:
        c = st.columns([4, 1, 1], vertical_alignment="center")
        c[0].markdown(f"{icon('reports', 14)} {r['title']}", unsafe_allow_html=True)
        if c[1].button("Open", key=f"ftp_ropen_{r['id']}", use_container_width=True):
            st.session_state[OPEN_REPORT] = r["id"]
            shell.goto("reports") if hasattr(shell, "goto") else None
        if self._can_edit and c[2].button("Pin" if not r["pinned"] else "Unpin",
                                          key=f"ftp_rpin_{r['id']}", use_container_width=True):
            svc.pin_report(shell.user, player_id, r["id"], on=not r["pinned"])
            st.rerun()

    # ---- Settings ------------------------------------------------------
    def _tab_settings(self, shell, svc, player_id, p) -> None:
        if not self._can_edit:
            st.caption("You need edit permission to change settings.")
            return
        st.markdown("**Squad flags**")
        with st.form("ftp_flags"):
            a, b, c = st.columns(3)
            captain = a.checkbox("Captain", value=p.captain)
            vice = b.checkbox("Vice-captain", value=p.vice_captain)
            academy = c.checkbox("Academy graduate", value=bool(p.document.get("academy_graduate")))
            d, e = st.columns(2)
            homegrown = d.checkbox("Homegrown", value=bool(p.document.get("homegrown")))
            foreign = e.checkbox("Foreign", value=bool(p.document.get("foreign")))
            if st.form_submit_button("Save flags"):
                svc.update_player(shell.user, player_id, captain=captain, vice_captain=vice)
                svc.set_flags(shell.user, player_id, academy_graduate=academy, homegrown=homegrown,
                              foreign=foreign)
                st.success("Saved.")
                st.rerun()

        st.markdown("**Player image**")
        up = st.file_uploader("Upload / replace image", type=["png", "jpg", "jpeg", "webp"],
                              key="ftp_img_up")
        if up is not None:
            square = st.checkbox("Crop to square (centered)", value=True, key="ftp_img_crop")
            zoom = st.slider("Zoom", 1.0, 2.5, 1.0, 0.1, key="ftp_img_zoom")
            if st.button("Save image", key="ftp_img_save"):
                data = self._process_image(up.getvalue(), square, zoom)
                svc.add_image(shell.user, player_id, data, "image/png", kind="profile")
                st.rerun()
        if p.profile_image_id and st.button("Remove image", key="ftp_img_del"):
            svc.update_player(shell.user, player_id, profile_image_id="")
            st.rerun()

        st.divider()
        st.markdown("**Danger zone**")
        a, b = st.columns(2)
        if a.button("Archive player", key="ftp_arch2"):
            svc.archive_player(shell.user, player_id)
            st.session_state.pop(SEL, None)
            st.rerun()
        if self._can_delete and b.button("Delete player", key="ftp_del2"):
            svc.delete_player(shell.user, player_id)
            st.session_state.pop(SEL, None)
            st.rerun()

    @staticmethod
    def _process_image(data: bytes, square: bool, zoom: float) -> bytes:
        """Crop/zoom the uploaded image with Pillow (already a platform dependency).
        Falls back to the original bytes if processing is unavailable."""
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(data)).convert("RGB")
            w, h = img.size
            if zoom > 1.0:
                cw, ch = int(w / zoom), int(h / zoom)
                left, top = (w - cw) // 2, (h - ch) // 2
                img = img.crop((left, top, left + cw, top + ch))
                w, h = img.size
            if square:
                s = min(w, h)
                img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
            out = io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
        except Exception:
            return data
