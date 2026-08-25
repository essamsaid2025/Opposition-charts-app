"""Download StatsBomb Open Data and extract a clean, one-row-per-shot table.

Pipeline stage 1:  download/load  ->  extract shots  ->  clean

This module is deliberately free of any modelling logic. It is responsible for:

  * downloading (and locally caching) the raw StatsBomb JSON,
  * walking the selected competitions/seasons/matches,
  * pulling out every ``Shot`` event,
  * flattening the nested StatsBomb structure into documented flat columns,
  * deriving the *actual outcome* label ``goal`` (1/0),
  * carrying ``statsbomb_xg`` through as a **benchmark-only** column.

The heavy raw JSON is cached under ``config.CACHE_DIR`` (outside git and outside
any cloud-synced folder). Re-running is cheap: cached files are reused.

See ``docs``/``README`` and ``DATASET.md`` for the full column dictionary.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

from . import config

# --------------------------------------------------------------------------- #
# Low-level cached HTTP fetch
# --------------------------------------------------------------------------- #
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "internal-xg-model/1.0 (research)"})


def _cache_path(rel: str) -> Path:
    return config.CACHE_DIR / rel


def _fetch_json(rel_url: str, *, retries: int = 3, timeout: int = 60) -> Any:
    """Fetch ``{base}/{rel_url}`` as JSON, caching the raw bytes on disk.

    ``rel_url`` is relative to the StatsBomb data root, e.g.
    ``"events/3773386.json"``. The cached copy mirrors that path under
    ``config.CACHE_DIR`` so a rerun never re-downloads.
    """
    cache_file = _cache_path(rel_url)
    if cache_file.exists() and cache_file.stat().st_size > 0:
        with cache_file.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    url = f"{config.SB_OPEN_DATA_BASE}/{rel_url}"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = _SESSION.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            # Write atomically-ish so an interrupted run never leaves a partial
            # file that a later run would treat as a valid cache hit.
            tmp = cache_file.with_suffix(cache_file.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh)
            tmp.replace(cache_file)
            return data
        except Exception as exc:  # noqa: BLE001 - network is best-effort
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_exc}")


# --------------------------------------------------------------------------- #
# Catalogue helpers
# --------------------------------------------------------------------------- #
def load_competitions() -> list[dict]:
    return _fetch_json("competitions.json")


def load_matches(competition_id: int, season_id: int) -> list[dict]:
    return _fetch_json(f"matches/{competition_id}/{season_id}.json")


def load_events(match_id: int) -> list[dict]:
    return _fetch_json(f"events/{match_id}.json")


# --------------------------------------------------------------------------- #
# Shot extraction
# --------------------------------------------------------------------------- #
def _g(d: dict | None, *keys: str, default: Any = None) -> Any:
    """Safe nested getter: _g(shot, 'body_part', 'name')."""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


# StatsBomb play_pattern names that indicate the shot originated from a dead ball
_SET_PIECE_PATTERNS = {"From Corner", "From Free Kick"}
# Shot types that are themselves dead-ball shots
_SET_PIECE_SHOT_TYPES = {"Free Kick", "Penalty"}


def _extract_shots_from_match(match: dict, competition: str, season: str) -> list[dict]:
    """Return a list of flat shot dictionaries for one match."""
    match_id = match["match_id"]
    events = load_events(match_id)

    # Build a lookup of pass events so we can characterise the assist (the
    # "key pass") without relying on StatsBomb's freeze-frame data.
    events_by_id = {e["id"]: e for e in events}

    rows: list[dict] = []
    for e in events:
        if _g(e, "type", "name") != "Shot":
            continue
        shot = e.get("shot", {}) or {}
        loc = e.get("location") or [None, None]
        shot_x = loc[0] if len(loc) > 0 else None
        shot_y = loc[1] if len(loc) > 1 else None

        outcome = _g(shot, "outcome", "name")
        goal = 1 if outcome == "Goal" else 0

        shot_type = _g(shot, "type", "name")            # Open Play / Penalty / Free Kick / Corner / Kick Off
        play_pattern = _g(e, "play_pattern", "name")

        penalty = shot_type == "Penalty"
        free_kick = shot_type == "Free Kick"
        set_piece = penalty or free_kick or (play_pattern in _SET_PIECE_PATTERNS)
        open_play = not set_piece

        # Assist characterisation from the key pass (reproducible from our own
        # event data in future: we would know the preceding pass).
        kp_id = shot.get("key_pass_id")
        assisted = kp_id is not None
        assist_cross = False
        assist_through_ball = False
        assist_cutback = False
        assist_type = None
        if assisted and kp_id in events_by_id:
            kp = events_by_id[kp_id].get("pass", {}) or {}
            assist_cross = bool(kp.get("cross", False))
            assist_through_ball = _g(kp, "technique", "name") == "Through Ball"
            assist_cutback = bool(kp.get("cut_back", False))
            if assist_cross:
                assist_type = "cross"
            elif assist_through_ball:
                assist_type = "through_ball"
            elif assist_cutback:
                assist_type = "cutback"
            else:
                assist_type = "pass"

        rows.append(
            {
                # --- identifiers / context (not model features) ---
                "match_id": match_id,
                "competition": competition,
                "season": season,
                "match_date": match.get("match_date"),
                "team": _g(e, "team", "name"),
                "player": _g(e, "player", "name"),
                "minute": e.get("minute"),
                "second": e.get("second"),
                "period": e.get("period"),
                # --- geometry (raw StatsBomb coords; normalised in features.py) ---
                "shot_x": shot_x,
                "shot_y": shot_y,
                # --- target ---
                "goal": goal,
                "outcome": outcome,
                # --- qualitative shot descriptors (candidate features) ---
                "body_part": _g(shot, "body_part", "name"),
                "shot_type": shot_type,
                "technique": _g(shot, "technique", "name"),
                "play_pattern": play_pattern,
                # --- context flags ---
                "set_piece": set_piece,
                "open_play": open_play,
                "penalty": penalty,
                "free_kick": free_kick,
                "one_on_one": bool(shot.get("one_on_one", False)),
                "first_time": bool(shot.get("first_time", False)),
                "open_goal": bool(shot.get("open_goal", False)),
                "aerial_won": bool(shot.get("aerial_won", False)),
                "follows_dribble": bool(shot.get("follows_dribble", False)),
                # --- assist context ---
                "assisted": assisted,
                "assist_type": assist_type,
                "assist_cross": assist_cross,
                "assist_through_ball": assist_through_ball,
                "assist_cutback": assist_cutback,
                # --- BENCHMARK ONLY: never a feature or a target ---
                "statsbomb_xg": shot.get("statsbomb_xg"),
            }
        )
    return rows


def build_shot_dataframe(
    selection: Iterable[tuple[int, int, str]] | None = None,
    *,
    max_workers: int = 8,
    progress_path: Path | None = None,
    limit_matches: int | None = None,
) -> pd.DataFrame:
    """Download the selected competitions and return a one-row-per-shot table.

    Parameters
    ----------
    selection : iterable of (competition_id, season_id, label)
        Defaults to ``config.COMPETITION_SELECTION``.
    max_workers : int
        Thread pool size for parallel per-match downloads.
    progress_path : Path | None
        If given, a human-readable progress line is appended here after each
        competition (useful when running head-less via ``pythonw``).
    limit_matches : int | None
        If set, only the first N matches *per competition-season* are used.
        Handy for quick smoke tests.
    """
    selection = list(selection or config.COMPETITION_SELECTION)

    def log(msg: str) -> None:
        if progress_path is not None:
            with Path(progress_path).open("a", encoding="utf-8") as fh:
                fh.write(msg + "\n")

    all_rows: list[dict] = []
    for comp_id, season_id, label in selection:
        try:
            matches = load_matches(comp_id, season_id)
        except Exception as exc:  # noqa: BLE001
            log(f"[SKIP] {label}: could not load match list ({exc})")
            continue
        if limit_matches is not None:
            matches = matches[:limit_matches]

        comp_name = matches[0]["competition"]["competition_name"] if matches else label
        season_name = matches[0]["season"]["season_name"] if matches else ""

        rows_before = len(all_rows)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {
                ex.submit(_extract_shots_from_match, m, comp_name, season_name): m["match_id"]
                for m in matches
            }
            for fut in as_completed(futures):
                mid = futures[fut]
                try:
                    all_rows.extend(fut.result())
                except Exception as exc:  # noqa: BLE001
                    log(f"    [warn] match {mid} failed: {exc}")
        log(f"[OK] {label}: {len(matches)} matches -> {len(all_rows) - rows_before} shots "
            f"(cumulative {len(all_rows)})")

    df = pd.DataFrame(all_rows)
    return _clean(df)


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Basic, documented cleaning applied at extraction time.

    - Drop shots with no recorded location (cannot compute geometry).
    - Ensure the target is a clean 0/1 integer.
    - Leave qualitative fields as-is; missing-value handling for modelling is
      done later in the preprocessing pipeline (so it is saved with the model).
    """
    if df.empty:
        return df
    n0 = len(df)
    df = df.dropna(subset=["shot_x", "shot_y"]).copy()
    df["goal"] = df["goal"].astype(int)
    df.attrs["dropped_no_location"] = n0 - len(df)
    # Stable ordering aids reproducibility of any downstream index-based ops.
    df = df.sort_values(["match_id", "minute", "second"]).reset_index(drop=True)
    return df


def save_processed(df: pd.DataFrame) -> None:
    config.ensure_dirs()
    try:
        df.to_parquet(config.PROCESSED_SHOTS, index=False)
    except Exception:  # pragma: no cover - parquet engine optional
        pass
    df.to_csv(config.PROCESSED_SHOTS_CSV, index=False)


def load_processed() -> pd.DataFrame:
    if config.PROCESSED_SHOTS.exists():
        try:
            return pd.read_parquet(config.PROCESSED_SHOTS)
        except Exception:  # pragma: no cover
            pass
    return pd.read_csv(config.PROCESSED_SHOTS_CSV)
