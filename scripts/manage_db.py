"""Database operations CLI (Phase 11.1) — runs against the same database the app
uses (backend chosen by configuration: sqlite or libSQL/Turso).

    python scripts/manage_db.py status                 # schema version + pending
    python scripts/manage_db.py migrate                # apply pending migrations
    python scripts/manage_db.py rollback <version>     # step back to <version>
    python scripts/manage_db.py backup <path>          # sqlite online backup

Migrations are also applied automatically when the app opens the database; this
CLI is for explicit operational control (CI/CD steps, maintenance windows).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fap.bootstrap import init_platform  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Show schema version and pending migrations")
    sub.add_parser("migrate", help="Apply any pending migrations")
    rb = sub.add_parser("rollback", help="Roll back to a target version")
    rb.add_argument("version", type=int)
    bk = sub.add_parser("backup", help="Online backup (sqlite backend)")
    bk.add_argument("path")
    args = parser.parse_args()

    platform = init_platform()
    db = platform.db                      # opening the DB applies pending migrations

    if args.command == "status":
        print(f"backend         : {db.backend}")
        print(f"schema version  : {db.schema_version()}")
        print(f"applied         : {db.applied_versions()}")
        print(f"pending         : {db.pending_versions() or 'none'}")
        return 0
    if args.command == "migrate":
        pending = db.pending_versions()
        print("migrations up to date" if not pending
              else f"applied on open; now at v{db.schema_version()}")
        return 0
    if args.command == "rollback":
        rolled = db.rollback(args.version)
        print(f"rolled back versions: {rolled or 'none'} (now v{db.schema_version()})")
        return 0
    if args.command == "backup":
        dest = db.backup(args.path)
        print(f"backup written to {dest}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
