"""Match-level data splitting with no shot leakage across splits (Checkpoint 3).

Two splitters, both operating on whole matches (a match never straddles splits):

* ``match_level_split`` — the PRIMARY split used for model selection and final
  test reporting. Matches are shuffled (seeded) and sliced 70/15/15, so every
  split is representative of the full competition mix.

* ``chronological_split`` — a robustness check. Matches are ordered by date and
  sliced 70/15/15, so the test set is strictly *later* than training (a
  time-generalisation stress test). Because our selection mixes leagues and
  later tournaments, this split is intentionally distribution-shifted and is
  reported separately, never used to tune anything.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_FRACS = (0.70, 0.15, 0.15)


def _slice_by_matches(df: pd.DataFrame, ordered_match_ids: list, fracs) -> dict[str, pd.DataFrame]:
    n = len(ordered_match_ids)
    n_train = int(round(n * fracs[0]))
    n_val = int(round(n * fracs[1]))
    train_ids = set(ordered_match_ids[:n_train])
    val_ids = set(ordered_match_ids[n_train : n_train + n_val])
    test_ids = set(ordered_match_ids[n_train + n_val :])
    return {
        "train": df[df["match_id"].isin(train_ids)].copy(),
        "val": df[df["match_id"].isin(val_ids)].copy(),
        "test": df[df["match_id"].isin(test_ids)].copy(),
    }


def match_level_split(df: pd.DataFrame, seed: int = 42, fracs=DEFAULT_FRACS) -> dict[str, pd.DataFrame]:
    """Representative match-level split (seeded shuffle)."""
    match_ids = df["match_id"].drop_duplicates().to_numpy()
    rng = np.random.default_rng(seed)
    rng.shuffle(match_ids)
    return _slice_by_matches(df, list(match_ids), fracs)


def chronological_split(df: pd.DataFrame, fracs=DEFAULT_FRACS) -> dict[str, pd.DataFrame]:
    """Time-ordered match-level split (earliest -> train, latest -> test)."""
    order = (
        df[["match_id", "match_date"]]
        .drop_duplicates("match_id")
        .sort_values(["match_date", "match_id"])
    )
    return _slice_by_matches(df, order["match_id"].tolist(), fracs)


def describe_split(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, part in splits.items():
        rows.append(
            {
                "split": name,
                "matches": part["match_id"].nunique(),
                "shots": len(part),
                "goals": int(part["goal"].sum()),
                "goal_rate": round(float(part["goal"].mean()), 4) if len(part) else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def assert_no_match_overlap(splits: dict[str, pd.DataFrame]) -> None:
    ids = {k: set(v["match_id"].unique()) for k, v in splits.items()}
    keys = list(ids)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            overlap = ids[keys[i]] & ids[keys[j]]
            if overlap:
                raise ValueError(f"Match overlap between {keys[i]} and {keys[j]}: {len(overlap)} matches")
