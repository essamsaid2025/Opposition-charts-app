"""Build-up and transition plugins."""
from __future__ import annotations

import pandas as pd

from fap.visuals import analysis as A
from fap.visuals.maps._builders import arrow_map, density_map

_CB, _CT = "Build-up", "Transitions"


def _phase(df: pd.DataFrame, x0: float, x1: float) -> pd.DataFrame:
    d = A.movement(df)
    return d[d["x"].between(x0, x1)]


def _goal_kick_sequences(df: pd.DataFrame) -> pd.DataFrame:
    starts = df[(df["event_type"].str.lower().isin(["goal_kick", "goal kick"]))
                | (df["play_pattern"].str.lower().str.contains("goal kick", na=False))]
    seq_ids = set(starts["sequence_id"].astype(str)) - {""}
    if seq_ids:
        return df[df["sequence_id"].astype(str).isin(seq_ids)
                  & df["event_type"].str.lower().isin(["pass", "carry", "dribble"])]
    return A.passes(df)[A.passes(df)["x"] <= 10]


arrow_map("goal_kick_buildup", "Goal Kick Build-up",
          lambda df, ctx: _goal_kick_sequences(df), category=_CB,
          description="Sequences starting from goal kicks (or deep restarts).")
arrow_map("first_phase_buildup", "First Phase Build-up",
          lambda df, ctx: _phase(df, 0, 33.33), category=_CB)
arrow_map("second_phase_buildup", "Second Phase Build-up",
          lambda df, ctx: _phase(df, 33.33, 66.67), category=_CB)
arrow_map("third_phase_buildup", "Third Phase Build-up",
          lambda df, ctx: _phase(df, 66.67, 100), category=_CB)
arrow_map("progression_routes", "Progression Routes",
          lambda df, ctx: A.progressive(A.successful(A.movement(df))), category=_CB,
          description="Successful progressive routes upfield.")
arrow_map("exit_routes", "Exit Routes",
          lambda df, ctx: A.movement(df)[(A.movement(df)["x"] < 33.33)
                                         & (A.movement(df)["end_x"] >= 33.33)],
          category=_CB, description="How the team plays out of the defensive third.")
arrow_map("press_resistance_map", "Press Resistance",
          lambda df, ctx: A.under_pressure(A.movement(df)), category=_CB,
          description="On-ball actions attempted under pressure, by outcome.")

arrow_map("fast_attacks", "Fast Attacks",
          lambda df, ctx: A.sequence_reaching(A.movement(df), 66.67, within_seconds=15),
          category=_CT, description="Sequences reaching the final third within 15s.")
arrow_map("counter_attacks", "Counter Attacks",
          lambda df, ctx: A.sequence_reaching(A.movement(df), 83.0, within_seconds=12),
          category=_CT, description="Sequences reaching the box within 12s.")
density_map("counter_press_map", "Counter Press",
            lambda df, ctx: A.counterpress_window(df), category=_CT)
density_map("transition_heatmap", "Transition Heatmap",
            lambda df, ctx: A.sequence_reaching(df, 66.67, within_seconds=15),
            category=_CT)
