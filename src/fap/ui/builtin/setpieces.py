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
    SET_PIECE_TYPE_LABELS, SET_PIECE_TYPES, SIDES,
)
from fap.ui.page import Page, page_registry

SEL = "_setpiece_id"                    # selected set piece (detail view)


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

        st.title("Set Piece Analysis")

        selected = st.session_state.get(SEL)
        if selected and svc.get_set_piece(selected):
            self._detail(shell, svc, selected)
            return

        tabs = st.tabs(["Dashboard", "Tag Set Piece", "Import", "Browse"])
        with tabs[0]:
            self._dashboard(shell, svc)
        with tabs[1]:
            self._tag(shell, svc)
        with tabs[2]:
            self._import(shell, svc)
        with tabs[3]:
            self._browse(shell, svc)

    # ---------------------------------------------------------------- dashboard
    def _dashboard(self, shell, svc) -> None:
        data = svc.dashboard(shell.user)
        if not data["total"]:
            st.info("No set pieces yet. Use **Tag Set Piece** to add one manually, "
                    "or **Import** a CSV/Excel/JSON file. Analytics dashboards arrive in Phase 9.1.")
            return
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Set Pieces", data["total"])
        c2.metric("Offensive", data["offensive"])
        c3.metric("Defensive", data["defensive"])
        c4.metric("Opposition", data["opposition"])
        st.subheader("By type")
        cols = st.columns(len(SET_PIECE_TYPES))
        for col, t in zip(cols, SET_PIECE_TYPES):
            col.metric(SET_PIECE_TYPE_LABELS[t], data["by_type"].get(t, 0))
        st.caption("KPIs, delivery maps, first-contact and second-ball analytics land in Phase 9.1.")

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
