"""REFERENCE IMPLEMENTATION - the template every future metric follows."""
from __future__ import annotations

import pandas as pd

from fap.core.plugin import PluginInfo
from fap.core.types import MetricResult
from fap.metrics.base import Metric, metric_registry


@metric_registry.register
class TotalEvents(Metric):
    info = PluginInfo(id="total_events", name="Events", category="volume",
                      description="Count of events after filters.")

    def compute(self, df: pd.DataFrame) -> MetricResult:
        n = int(len(df))
        return MetricResult(id=self.info.id, label=self.info.name, value=n, formatted=f"{n:,}")
