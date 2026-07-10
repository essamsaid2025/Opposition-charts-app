"""User management CLI (runs against the same database as the app).

    python scripts/manage_users.py create <username> [--role analyst|admin]
    python scripts/manage_users.py set-password <username>

Passwords are prompted interactively (never passed on the command line) and
stored PBKDF2-SHA256 hashed, identical to in-app authentication.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fap.bootstrap import init_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="Create a new user")
    create.add_argument("username")
    create.add_argument("--role", default="analyst", choices=["analyst", "admin"])
    setpw = sub.add_parser("set-password", help="Set a user's password")
    setpw.add_argument("username")
    args = parser.parse_args()

    ctx = init_app(Path(__file__).resolve().parents[1])
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1

    if args.command == "create":
        ctx.authenticator.create_user(args.username, password, role=args.role)
        print(f"Created user {args.username!r} with role {args.role!r}.")
    else:
        ctx.authenticator.change_password(args.username, password)
        print(f"Password updated for {args.username!r}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
