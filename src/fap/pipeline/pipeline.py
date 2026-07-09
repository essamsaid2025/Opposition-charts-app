from __future__ import annotations

from typing import Callable

import pandas as pd

from fap.pipeline import schema, transforms
from fap.pipeline.coordinates import coord_registry
from fap.providers.base import RawDataset

Step = Callable[[pd.DataFrame], pd.DataFrame]


class DataPipeline:
    """RawDataset -> validated, canonical, enriched event frame.

    The step list is data, not code: callers can insert custom steps
    (e.g. club-specific derived columns) without modifying this class.
    """

    def __init__(self, extra_steps: tuple[Step, ...] = ()) -> None:
        self._steps: tuple[Step, ...] = (
            transforms.clip_canonical,
            transforms.derive_movement,
            transforms.derive_zones,
            transforms.derive_time,
            transforms.derive_plot_coords,
            *extra_steps,
        )

    def run(self, raw: RawDataset, *, flip_direction: bool = False) -> pd.DataFrame:
        df = schema.coerce_schema(raw.frame)
        if raw.column_mapping:
            df = df.rename(columns=raw.column_mapping)
        schema.validate(df)
        df = coord_registry.create(raw.native_coord_system).to_canonical(df)
        if flip_direction:
            df = transforms.flip_left_to_right(df)
        for step in self._steps:
            df = step(df)
        return df
