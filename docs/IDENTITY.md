# Identity & Access (Phase 3A)

Authentication is the platform entry point. **Microsoft owns identity; the
platform owns authorization.** Sign-in runs through OpenID Connect (Microsoft
Entra ID by default); the platform only decides who is admitted and as what
role.

There are no local passwords, no local usernames, and no password database in
this layer. (The legacy `fap.auth` local provider still exists for the
unrelated `fap.ui` shell and is untouched.)

## What pages import

Pages never see Microsoft, a provider, or a claim. They import one facade:

```python
from fap.identity import current_user, require_login, logout, Role

user = require_login()          # renders sign-in / access-denied and stops if needed
if user.has_role(Role.HEAD_COACH):
    ...
```

- `current_user() -> User | None` — the authorized user, or None (never raises).
- `require_login() -> User` — gate a page; stops the script with a sign-in or
  access-denied screen otherwise.
- `logout()` — sign out of the platform and the provider.
- `Role` — the 12 club roles, rank-ordered (`user.role >= Role.HEAD_COACH`).

## Architecture

```
   app.py / pages          import fap.identity  (facade only)
        │
   fap.identity.session     Streamlit glue: st.login / st.user / st.logout
        │                    (the ONLY module that imports Streamlit)
   fap.identity.service      IdentityService: normalize claims -> authorize
        ├── provider.py       IdentityProvider registry (a plugin family)
        │     builtin/: microsoft, google, okta, auth0, keycloak, dev
        ├── policy.py         AccessPolicy: domains / whitelist / roles, fail closed
        └── roles.py          Role (12, ranked)
```

Everything below `session.py` is pure and unit-tested without a browser.

### Adding a provider

One file in `fap/identity/builtin/` subclassing `IdentityProvider`, declaring
its claim names, registered with `@identity_registry.register`. No application
code changes. Supported today: **Microsoft Entra, Google Workspace, Okta,
Auth0, Keycloak, Dev**.

## Roles

Super Admin · Club Admin · Head Coach · Assistant Coach · Goalkeeper Coach ·
Performance Analyst · First Team Analyst · Academy Analyst · Recruitment Analyst
· Scout · Medical Staff · Read Only. Ranked by authority; compare with
`>=`.

## Configuration

All configuration is in `.streamlit/secrets.toml` (gitignored). Copy
`.streamlit/secrets.toml.example` and fill in your values. `[auth.*]` is
Streamlit-native OIDC; `[identity]` is the platform access policy. Tenant ids
and domains live only in secrets — never in code.

**Role resolution order:** per-email `role_assignments` → highest matching
`group_roles` → `default_role`.

**Fail closed:** with neither `allowed_domains` nor `email_whitelist`, no one is
admitted. Access is granted only by an explicit rule.

**Session:** `session_timeout_minutes` sets an idle timeout (0 disables);
`remember_session = true` keeps a session alive across the idle window.

## Local development

Set `FAP_ENVIRONMENT=development` (the existing convention) to bypass sign-in
and run as a synthetic **Super Admin** — no identity provider or Authlib needed.
Production never falls back to the dev provider; that is what keeps the platform
fail-closed.

## Deploying with authentication on

1. `pip install -r requirements.txt` (adds Authlib; Streamlit ≥ 1.42).
2. Register an app in Microsoft Entra; set redirect URI to
   `<your-url>/oauth2callback`.
3. Fill `.streamlit/secrets.toml` from the example (client id/secret, tenant
   metadata URL, allowed domains, role assignments).
4. Deploy. Every visit now requires a Microsoft sign-in from an allowed domain.
