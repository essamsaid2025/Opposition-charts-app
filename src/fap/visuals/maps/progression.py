"""Ball progression plugins."""
from __future__ import annotations

import pandas as pd

from fap.visuals import analysis as A
from fap.visuals.maps._builders import arrow_map, density_map

_C = "Progression"

arrow_map("carry_map", "Carry Map", lambda df, ctx: A.carries(df), category=_C)
arrow_map("progressive_carries", "Progressive Carries",
          lambda df, ctx: A.progressive(A.carries(df)), category=_C)
arrow_map("driving_runs", "Driving Runs",
          lambda df, ctx: A.carries(df)[A.carries(df)["distance"].fillna(0) >= 15],
          category=_C, description="Carries covering ≥15 units.")
arrow_map("ball_progression", "Ball Progression",
          lambda df, ctx: A.progressive(A.movement(df)), category=_C,
          description="Progressive passes and carries together.")
arrow_map("ball_movement", "Ball Movement",
          lambda df, ctx: A.movement(df), category=_C)
arrow_map("ball_advancement", "Ball Advancement",
          lambda df, ctx: A.forward(A.movement(df)), category=_C,
          description="All forward ball movement.")
density_map("progression_heatmap", "Ball Progression Heatmap",
            lambda df, ctx: A.progressive(A.movement(df)), category=_C)
