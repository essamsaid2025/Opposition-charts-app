"""Build the processed one-row-per-shot dataset from StatsBomb Open Data.

Usage (from the internal-xg/ directory):

    python scripts/build_dataset.py             # full default selection
    python scripts/build_dataset.py --smoke     # 3 matches per comp (quick test)

Raw JSON is cached under ~/.cache/statsbomb_open_data (override XG_CACHE_DIR).
Only the small processed table is written into data/processed/.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make ``src`` importable when run as a plain script.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from xg import config, data_loader  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true", help="only 3 matches per comp-season")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--progress", type=str, default=str(ROOT / "reports" / "build_progress.log"))
    args = ap.parse_args()

    config.ensure_dirs()
    Path(args.progress).write_text("", encoding="utf-8")  # reset log

    df = data_loader.build_shot_dataframe(
        max_workers=args.workers,
        progress_path=Path(args.progress),
        limit_matches=3 if args.smoke else None,
    )
    data_loader.save_processed(df)

    summary = [
        f"rows (shots): {len(df)}",
        f"matches: {df['match_id'].nunique()}",
        f"goals: {int(df['goal'].sum())}  base rate: {df['goal'].mean():.4f}",
        f"competitions: {df['competition'].nunique()}",
        f"saved: {config.PROCESSED_SHOTS_CSV}",
    ]
    with Path(args.progress).open("a", encoding="utf-8") as fh:
        fh.write("\n=== SUMMARY ===\n" + "\n".join(summary) + "\n")


if __name__ == "__main__":
    main()
