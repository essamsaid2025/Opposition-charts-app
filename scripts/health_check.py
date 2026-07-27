"""Health / readiness probe (Phase 11.4/11.5).

    python scripts/health_check.py            # full health report (human)
    python scripts/health_check.py --json     # machine-readable, for monitors
    python scripts/health_check.py --config   # production config validation only

Exit code is 0 when healthy / production-ready, non-zero otherwise — so it drops
straight into a container HEALTHCHECK, a k8s readiness probe, or a CI gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fap.bootstrap import init_platform          # noqa: E402
from fap.config.validation import summarize      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--config", action="store_true", help="validate configuration only")
    args = ap.parse_args()

    platform = init_platform()

    if args.config:
        result = summarize(platform.settings)
        print(json.dumps(result, indent=2) if args.json else _fmt_config(result))
        return 0 if result["production_ready"] else 2

    report = platform.health()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"STATUS: {report['status'].upper()}")
        for c in report["checks"]:
            mark = "ok " if c["ok"] else "XX "
            print(f"  [{mark}] {c['name']:<22} {c['detail']} ({c['latency_ms']}ms)")
    return 0 if report["status"] == "healthy" else 1


def _fmt_config(result: dict) -> str:
    lines = [f"production_ready: {result['production_ready']}"]
    for level in ("fatal", "warnings", "info"):
        for msg in result.get(level, []):
            lines.append(f"  {msg}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
