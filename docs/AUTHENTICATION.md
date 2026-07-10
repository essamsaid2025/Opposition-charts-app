# Authentication Guide

Authentication is a plugin family (`fap.auth`). The built-in provider is
`local` (username/password, PBKDF2-SHA256 hashed in SQLite). The workflow
policy below lives in `fap/auth/workflow.py` and is fully unit-tested.

## Development Mode (no login screen)

Set the environment to `development` in either of two ways:

**Option A - local config file.** Create `config/settings.local.yaml`
(gitignored) containing:

    environment: "development"

**Option B - environment variable** (containers, CI, Streamlit Cloud secrets):

    FAP_ENVIRONMENT=development

In development mode the login screen never appears; the session runs as a
temporary **Developer** user (role `admin`, never written to the database).
A banner in the sidebar reminds you that auth is bypassed.

## Production Mode

Production is the default. Remove the override (delete the line from
`settings.local.yaml`, or unset `FAP_ENVIRONMENT`), or set explicitly:

    environment: "production"

With `auth.enabled: true` (the default), every visit requires sign-in.

## First-Run Administrator

On startup with an **empty user database**, the app creates exactly one
administrator account:

    username: admin
    password: admin123

This account is flagged `must_change_password`; the very first login is
forced through a password-change screen before the app is usable. The
account is **never recreated** once any user exists, and the default
password is the only hardcoded credential in the codebase (first-run only).

## Changing the Administrator Password

1. In the app: sign in as `admin` / `admin123`; the forced password-change
   form appears - set a new password (minimum 8 characters).
2. Any time later, from a terminal:

       python scripts/manage_users.py set-password admin

   The password is prompted interactively and stored hashed.

## Creating Additional Users

    python scripts/manage_users.py create maria --role analyst
    python scripts/manage_users.py create coach_pep --role admin

The script uses the same database and the same hashing as the app. Roles are
free-form strings today (`analyst`, `admin`); role-based page access is a
future extension point.

## Security Notes

- Passwords are hashed with PBKDF2-HMAC-SHA256, 200,000 iterations, 16-byte
  random salt per user. Plaintext is never stored or logged.
- `must_change_password` guarantees the bootstrap credential cannot survive
  past the first login.
- Adding SSO/OAuth later = one new module registering in `auth_registry`,
  plus `auth.provider: "<id>"` in configuration. No call sites change.
