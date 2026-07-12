"""Defensive analysis plugins."""
from __future__ import annotations

from fap.visuals import analysis as A
from fap.visuals.maps._builders import arrow_map, density_map, scatter_map

_C = "Defensive"

scatter_map("defensive_actions", "Defensive Actions",
            lambda df, ctx: A.defensive(df), category=_C, by_type=True)
scatter_map("interceptions", "Interceptions",
            lambda df, ctx: A.defensive(df, ("interception",)), category=_C)
scatter_map("recoveries", "Recoveries",
            lambda df, ctx: A.defensive(df, ("recovery",)), category=_C,
            color_role="success")
scatter_map("tackles", "Tackles",
            lambda df, ctx: A.defensive(df, ("tackle",)), category=_C)
scatter_map("blocks", "Blocks",
            lambda df, ctx: A.defensive(df, ("block",)), category=_C)
scatter_map("pressures", "Pressures",
            lambda df, ctx: A.defensive(df, ("pressure",)), category=_C,
            color_role="warning")
scatter_map("counter_pressures", "Counter Pressures",
            lambda df, ctx: A.counterpress_window(df), category=_C,
            color_role="warning",
            description="Defensive actions within 6s of a turnover.")
scatter_map("ball_wins", "Ball Wins",
            lambda df, ctx: A.successful(A.defensive(
                df, ("recovery", "interception", "tackle", "duel"))),
            category=_C, color_role="success")
scatter_map("ball_losses", "Ball Losses",
            lambda df, ctx: A.turnovers(df), category=_C, color_role="danger")
scatter_map("clearances", "Clearances",
            lambda df, ctx: A.defensive(df, ("clearance",)), category=_C)
scatter_map("aerial_duels", "Aerial Duels",
            lambda df, ctx: A.defensive(df, ("duel",))[
                A.defensive(df, ("duel",))["sub_event"].str.contains(
                    "aerial|air", case=False, na=False)], category=_C)
scatter_map("ground_duels", "Ground Duels",
            lambda df, ctx: A.defensive(df, ("duel",))[
                ~A.defensive(df, ("duel",))["sub_event"].str.contains(
                    "aerial|air", case=False, na=False)], category=_C)
scatter_map("turnovers_map", "Turnovers",
            lambda df, ctx: A.turnovers(df), category=_C, color_role="danger")
scatter_map("counterpress_recoveries", "Counterpress Recoveries",
            lambda df, ctx: A.counterpress_window(df)[
                A.counterpress_window(df)["event_type"].str.lower().eq("recovery")],
            category=_C, color_role="success")

density_map("defensive_heatmap", "Defensive Heatmap",
            lambda df, ctx: A.defensive(df), category=_C)
density_map("pressing_heatmap", "Pressing Heatmap",
            lambda df, ctx: A.defensive(df, ("pressure", "duel", "tackle")),
            category=_C)
density_map("recovery_heatmap", "Recovery Heatmap",
            lambda df, ctx: A.defensive(df, ("recovery", "interception")),
            category=_C)
