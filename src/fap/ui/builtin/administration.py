"""Administration - the enterprise admin portal (Phase 7.1).

Every section is capability-protected through the platform PermissionService and
backed by the AdministrationService (users, roles, invitations, sessions, scoped
grants, storage) plus the existing WorkspaceManager (org hierarchy) and
AuditService. No new manager, no new hierarchy, no second design language - it
renders inside the existing shell and theme.
"""
from __future__ import annotations

import streamlit as st

from fap.core.exceptions import AuthError
from fap.core.plugin import PluginInfo
from fap.identity import ALL_CAPABILITIES, Capability, POSITIONS
from fap.identity.roles import Role
from fap.ui.page import Page, page_registry


@page_registry.register
class AdministrationPage(Page):
    info = PluginInfo(id="administration", name="Administration", category="page")
    section = "Admin"
    icon = "admin"
    order = 90
    min_role = Role.CLUB_ADMIN          # hidden from analysts / read-only

    # ------------------------------------------------------------ entry
    def render(self, shell) -> None:
        st.title("Administration")
        admin = getattr(shell.platform, "administration", None) if shell.platform else None
        perms = getattr(shell.platform, "permissions", None) if shell.platform else None
        if admin is None or perms is None:
            st.info("Administration services unavailable.")
            return
        if not perms.can(shell.user, str(Capability.VIEW_ADMIN)):
            st.warning("You do not have permission to view administration.")
            return

        # only show sections the user is allowed to see (capability-gated tabs)
        sections = [
            ("Users", Capability.VIEW_ADMIN, self._users),
            ("Roles", Capability.VIEW_ADMIN, self._roles),
            ("Organizations", Capability.MANAGE_ORG, self._orgs),
            ("Invitations", Capability.VIEW_ADMIN, self._invitations),
            ("Sessions", Capability.VIEW_SESSIONS, self._sessions),
            ("Audit", Capability.VIEW_AUDIT, self._audit),
            ("Storage", Capability.VIEW_STORAGE, self._storage),
            ("Security", Capability.MANAGE_SECURITY, self._security),
            ("Providers", Capability.MANAGE_PROVIDER, self._providers),
            ("Settings", Capability.MANAGE_SETTINGS, self._settings),
        ]
        allowed = [(name, fn) for name, cap, fn in sections
                   if perms.can(shell.user, str(cap))]
        tabs = st.tabs([n for n, _ in allowed])
        for tab, (_name, fn) in zip(tabs, allowed):
            with tab:
                try:
                    fn(shell, admin, perms)
                except AuthError as exc:
                    st.warning(str(exc))
                except Exception as exc:                     # never crash the portal
                    st.error(f"Section error: {exc}")

    # ------------------------------------------------------------ Users
    def _users(self, shell, admin, perms) -> None:
        st.caption("Identity is owned by your provider (e.g. Microsoft Entra ID). This directory "
                   "holds each user's platform role, position, scope and status.")
        can_edit = perms.can(shell.user, str(Capability.EDIT_USERS))
        role_slugs = [r.slug for r in admin.list_roles()]
        for u in admin.list_users(shell.user):
            with st.container(border=True):
                st.markdown(f"**{u.name or u.email}** · `{u.email}`  \n"
                            f"Role **{u.role_slug}** · Position _{u.position or '—'}_ · "
                            f"Status **{u.status}** · Last login {u.last_login_at or '—'}")
                if not can_edit:
                    continue
                c1, c2, c3 = st.columns(3)
                new_role = c1.selectbox("Role", role_slugs,
                                        index=role_slugs.index(u.role_slug) if u.role_slug in role_slugs else 0,
                                        key=f"role_{u.email}")
                new_pos = c2.selectbox("Position", list(POSITIONS),
                                       index=(list(POSITIONS).index(u.position) if u.position in POSITIONS else 0),
                                       key=f"pos_{u.email}")
                new_status = c3.selectbox("Status", ["active", "suspended", "disabled"],
                                          index=["active", "suspended", "disabled"].index(u.status),
                                          key=f"st_{u.email}")
                b1, b2, b3 = st.columns(3)
                if b1.button("Apply", key=f"apply_{u.email}"):
                    admin.set_role(shell.user, u.email, new_role)
                    admin.set_position(shell.user, u.email, new_pos)
                    admin.set_status(shell.user, u.email, new_status)
                    st.rerun()
                if b2.button("Force logout", key=f"fl_{u.email}"):
                    admin.force_logout_user(shell.user, u.email); st.toast("Signed out")
                if b3.button("Delete", key=f"del_{u.email}"):
                    admin.delete_user(shell.user, u.email); st.rerun()

    # ------------------------------------------------------------ Roles
    def _roles(self, shell, admin, perms) -> None:
        st.caption("Roles are collections of capabilities. Built-ins are fixed; create custom "
                   "roles for your club.")
        for rd in admin.list_roles():
            tag = "Super Admin (all)" if rd.superuser else f"{len(rd.capabilities)} capabilities"
            with st.expander(f"{rd.name}  ·  {tag}" + ("  · built-in" if rd.builtin else "  · custom")):
                if rd.superuser:
                    st.write("Grants every capability.")
                else:
                    st.write(", ".join(sorted(rd.capabilities)) or "_no capabilities_")
                if not rd.builtin and perms.can(shell.user, str(Capability.MANAGE_ROLES)):
                    if st.button("Delete role", key=f"delrole_{rd.slug}"):
                        admin.delete_role(shell.user, rd.slug); st.rerun()
        if perms.can(shell.user, str(Capability.MANAGE_ROLES)):
            st.divider()
            st.markdown("**Create custom role**")
            name = st.text_input("Role name", key="new_role_name")
            caps = st.multiselect("Capabilities", sorted(ALL_CAPABILITIES), key="new_role_caps")
            if st.button("Create role", type="primary", key="create_role") and name.strip():
                admin.create_role(shell.user, name.strip(), caps); st.rerun()

    # ------------------------------------------------------------ Organizations
    def _orgs(self, shell, admin, perms) -> None:
        st.caption("Organization → Club → Team → Season → Competition → Workspace. "
                   "The existing workspace hierarchy; scopes attach here.")
        try:
            clubs = shell.wm.nodes_of_kind("club")
        except Exception:
            clubs = []
        for club in clubs:
            st.markdown(f"• **{club.name}** `{club.id[:8]}`")
            for child in shell.wm.children(club.id):
                st.markdown(f"&nbsp;&nbsp;&nbsp;↳ {child.kind}: {child.name} `{child.id[:8]}`",
                            unsafe_allow_html=True)
        name = st.text_input("New club name", key="admin_new_club")
        if st.button("Create club", key="admin_create_club") and name.strip():
            shell.wm.create_club(shell.user, name.strip()); st.rerun()

    # ------------------------------------------------------------ Invitations
    def _invitations(self, shell, admin, perms) -> None:
        can_invite = perms.can(shell.user, str(Capability.INVITE_USER))
        if can_invite:
            st.markdown("**Invite user**")
            role_slugs = [r.slug for r in admin.list_roles()]
            c1, c2, c3 = st.columns(3)
            email = c1.text_input("Email", key="inv_email")
            role = c2.selectbox("Role", role_slugs, key="inv_role")
            pos = c3.selectbox("Position", list(POSITIONS), key="inv_pos")
            if st.button("Send invitation", type="primary", key="inv_send") and email.strip():
                inv = admin.invite(shell.user, email.strip(), role_slug=role, position=pos)
                st.success(f"Invitation created for {inv.email}. They are provisioned on first "
                           f"Microsoft sign-in.")
                st.rerun()
            st.divider()
        st.markdown("**Pending & recent invitations**")
        for inv in admin.list_invitations(shell.user):
            cols = st.columns([3, 1])
            cols[0].write(f"`{inv.email}` · {inv.role_slug} · **{inv.status}** · by {inv.invited_by or '—'}")
            if inv.status == "pending" and can_invite and cols[1].button("Revoke", key=f"revinv_{inv.id}"):
                admin.revoke_invitation(shell.user, inv.id); st.rerun()

    # ------------------------------------------------------------ Sessions
    def _sessions(self, shell, admin, perms) -> None:
        can_manage = perms.can(shell.user, str(Capability.MANAGE_SESSIONS))
        active = admin.list_sessions(shell.user, active_only=False)
        if not active:
            st.caption("No sessions recorded.")
        for s in active:
            cols = st.columns([3, 1])
            cols[0].write(f"`{s.email}` · {s.provider_id or '—'} · **{s.status}** · "
                          f"last seen {s.last_seen_at}")
            if s.status == "active" and can_manage and cols[1].button("Force logout", key=f"fls_{s.id}"):
                admin.force_logout(shell.user, s.id); st.rerun()

    # ------------------------------------------------------------ Audit
    def _audit(self, shell, admin, perms) -> None:
        query = st.text_input("Search action / actor", key="audit_q").strip().lower()
        try:
            entries = shell.wm.audit_trail(limit=300)
        except Exception:
            entries = []
        shown = 0
        for e in entries:
            hay = f"{e.action} {e.actor} {e.actor_role} {e.target_type} {e.target_id}".lower()
            if query and query not in hay:
                continue
            st.write(f"`{e.ts}` · **{e.action}** · {e.actor or 'system'} "
                     f"({e.actor_role or '—'}) · {e.target_type} {e.target_id}")
            shown += 1
        if shown == 0:
            st.caption("No matching audit entries.")

    # ------------------------------------------------------------ Storage
    def _storage(self, shell, admin, perms) -> None:
        rep = admin.storage_report(shell.user)
        c1, c2 = st.columns(2)
        c1.metric("Dataset storage", f"{rep['datasets_bytes'] / 1e6:.1f} MB")
        c2.metric("Image storage", f"{rep['images_bytes'] / 1e6:.1f} MB")
        st.markdown("**Row counts**")
        for t, n in rep["tables"].items():
            st.write(f"• {t}: **{n if n is not None else '—'}**")
        if perms.can(shell.user, str(Capability.MANAGE_STORAGE)):
            st.divider()
            st.caption("Cache is only an accelerator; datasets are never deleted here.")
            if st.button("Clear cache", key="clear_cache"):
                admin.cleanup_cache(shell.user); st.toast("Cache cleared")

    # ------------------------------------------------------------ Security
    def _security(self, shell, admin, perms) -> None:
        st.caption("Sign-in security is enforced by the identity access policy (allowed domains, "
                   "email whitelist, Microsoft tenant) configured in secrets/config.")
        try:
            from fap.identity.config import development_mode, load_identity_config
            import streamlit as _st
            cfg = load_identity_config({k: _st.secrets[k] for k in _st.secrets} if hasattr(_st, "secrets") else {},
                                       development=development_mode())
            pol = cfg.policy
            st.write(f"• Development mode: **{cfg.development}**")
            st.write(f"• Providers: **{', '.join(cfg.providers) or 'none configured'}**")
            st.write(f"• Allowed domains: **{', '.join(sorted(pol.allowed_domains)) or '—'}**")
            st.write(f"• Email whitelist: **{len(pol.email_whitelist)} entries**")
            st.write(f"• Session timeout: **{cfg.session_timeout_minutes} min** "
                     f"(remember: {cfg.remember_session})")
            st.write(f"• Fail-closed: **{pol.fail_closed}**")
        except Exception as exc:
            st.info(f"Security configuration unavailable: {exc}")

    # ------------------------------------------------------------ Providers
    def _providers(self, shell, admin, perms) -> None:
        st.caption("Identity providers (provider-agnostic). Microsoft Entra ID is the production "
                   "default; development mode bypasses sign-in.")
        try:
            from fap.identity.provider import identity_registry, load_builtin_identity_providers
            load_builtin_identity_providers()
            for cls in identity_registry:
                info = cls().info
                st.write(f"• **{info.name}** (`{info.id}`) — {info.description or ''}")
        except Exception as exc:
            st.info(f"Providers unavailable: {exc}")

    # ------------------------------------------------------------ Settings
    def _settings(self, shell, admin, perms) -> None:
        try:
            from fap.core.version import platform_version
            st.write(f"• Platform version: **{platform_version()}**")
        except Exception:
            pass
        st.write(f"• Signed-in administrator: **{shell.user.name}** ({shell.user.email})")
        st.write(f"• Effective role: **{perms.role_slug_for(shell.user)}** "
                 f"· superuser: **{perms.is_superuser(shell.user)}**")
        st.caption("Super Admin is seeded from FAP_SUPER_ADMIN (or [identity].super_admin). "
                   "Only a Super Admin can create another Super Admin.")
