"""Passing analysis - arrow-map plugins (each an independent registered plugin)."""
from __future__ import annotations

from fap.visuals import analysis as A
from fap.visuals.maps._builders import arrow_map

_C = "Passing"

arrow_map("pass_map", "Pass Map", lambda df, ctx: A.passes(df), category=_C,
          description="All passes with outcome split.")
arrow_map("successful_passes", "Successful Passes",
          lambda df, ctx: A.successful(A.passes(df)), category=_C,
          split_outcome=False, ok_label="Completed")
arrow_map("failed_passes", "Failed Passes",
          lambda df, ctx: A.unsuccessful(A.passes(df)), category=_C,
          split_outcome=False)
arrow_map("forward_passes", "Forward Passes",
          lambda df, ctx: A.forward(A.passes(df)), category=_C)
arrow_map("backward_passes", "Backward Passes",
          lambda df, ctx: A.backward(A.passes(df)), category=_C)
arrow_map("sideways_passes", "Sideways Passes",
          lambda df, ctx: A.sideways(A.passes(df)), category=_C)
arrow_map("progressive_passes", "Progressive Passes",
          lambda df, ctx: A.progressive(A.passes(df)), category=_C,
          description="Passes ≥25% closer to goal (min 10 units).")
arrow_map("line_breaking_passes", "Line Breaking Passes",
          lambda df, ctx: A.line_breaking(A.passes(df)), category=_C,
          description="Forward central passes gaining ≥15 units (event-data proxy).")
arrow_map("vertical_passes", "Vertical Passes",
          lambda df, ctx: A.vertical(A.passes(df)), category=_C)
arrow_map("switches_of_play", "Switches of Play",
          lambda df, ctx: A.switches(A.passes(df)), category=_C, curved=True,
          description="Passes crossing ≥40 lateral units.")
arrow_map("long_passes", "Long Passes",
          lambda df, ctx: A.long_passes(A.passes(df)), category=_C)
arrow_map("short_passes", "Short Passes",
          lambda df, ctx: A.short_passes(A.passes(df)), category=_C)
arrow_map("crosses_map", "Crosses",
          lambda df, ctx: A.crosses(df), category=_C, curved=True)
arrow_map("key_passes", "Key Passes",
          lambda df, ctx: A.key_passes(A.passes(df)), category=_C,
          split_outcome=False)
arrow_map("assists_map", "Assists",
          lambda df, ctx: A.assists(A.passes(df)), category=_C,
          split_outcome=False)
arrow_map("gk_pass_map", "Goalkeeper Pass Map",
          lambda df, ctx: A.passes(A.goalkeeper(df)), category="Goalkeeper")
arrow_map("launch_map", "Launch Map",
          lambda df, ctx: A.long_passes(A.passes(A.goalkeeper(df))),
          category="Goalkeeper", description="Goalkeeper launches (≥30 units).")
