from __future__ import annotations

from typing import Callable

import pandas as pd

from fap.pipeline import schema, transforms
from fap.pipeline.coordinates import coord_registry
from fap.providers.base import RawDataset

Step = Callable[[pd.DataFrame], pd.DataFrame]


class DataPipeline:
    """RawDataset -> validated, canonical, enriched event frame.

    Exactly one copy is made (inside schema.coerce_schema); all steps mutate
    that owned frame in place. The step list is data, not code: callers can
    insert custom steps without modifying this class.
    """

    def __init__(self, extra_steps: tuple[Step, ...] = ()) -> None:
        self._steps: tuple[Step, ...] = (
            transforms.clip_canonical,
            transforms.derive_movement,
            transforms.derive_zones,
            transforms.derive_time,
            transforms.derive_score_state,
            transforms.derive_plot_coords,
            *extra_steps,
        )

    def run(self, raw: RawDataset, *, flip_direction: bool = False,
            auto_orient: bool = True,
            column_mapping: dict[str, str] | None = None,
            coord_system: str | None = None,
            constants: dict[str, str] | None = None) -> pd.DataFrame:
        df = schema.clean_columns(raw.frame)
        mapping = column_mapping if column_mapping is not None else raw.column_mapping
        df = schema.apply_mapping(df, mapping)
        df = schema.apply_constants(df, constants)  # single-kind files inject e.g. event_type
        schema.validate(df)          # required columns must come from the source/mapping,
        df = schema.coerce_schema(df)  # coercion only fills in the optional remainder
        system = coord_system or raw.native_coord_system
        df = coord_registry.create(system).to_canonical(df)
        # A manual flip always wins. Otherwise auto-orient: single-direction tagged
        # feeds often attack toward x=0, which would leave every shot ~90m from the
        # model's goal (xG ~ 0) and mirror the attacking maps. Detection is
        # conservative and only flips on a clear reverse signal.
        if flip_direction:
            df = transforms.flip_left_to_right(df)
        elif auto_orient and transforms.detect_reverse_attack(df)[0]:
            df = transforms.flip_left_to_right(df)
        for step in self._steps:
            df = step(df)
        return df
