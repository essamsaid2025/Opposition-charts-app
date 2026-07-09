import pandas as pd
import pytest

from fap.core.exceptions import DataValidationError
from fap.pipeline.pipeline import DataPipeline
from fap.providers.base import RawDataset


def test_pipeline_normalizes_120x80() -> None:
    raw = RawDataset(
        frame=pd.DataFrame({"event_type": ["pass"], "x": [60.0], "y": [40.0],
                            "x2": [120.0], "y2": [80.0]}),
        native_coord_system="120x80",
    )
    df = DataPipeline().run(raw)
    assert df.loc[0, "x"] == pytest.approx(50.0)
    assert df.loc[0, "x2"] == pytest.approx(100.0)
    assert df.loc[0, "into_final_third"]
    assert "y_plot" in df.columns


def test_pipeline_rejects_missing_columns() -> None:
    raw = RawDataset(frame=pd.DataFrame({"foo": [1]}))
    with pytest.raises(DataValidationError):
        DataPipeline().run(raw)
