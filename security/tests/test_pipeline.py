
import pandas as pd
import pytest

from processing.data_pipeline import DataPipeline


def valid_viirs_rows() -> pd.DataFrame:
    row = {
        "latitude": 30.0,
        "longitude": -9.0,
        "bright_ti4": 330.0,
        "bright_ti5": 290.0,
        "scan": 1.0,
        "track": 1.0,
        "acq_date": "2026-11-10",
        "acq_time": 1234,
        "satellite": "N20",
        "instrument": "VIIRS",
        "confidence": "n",
        "version": "2.0",
        "frp": 12.5,
        "daynight": "D",
    }
    invalid = {**row, "latitude": 95.0}
    return pd.DataFrame([row, invalid])


def test_pipeline_processes_and_rejects_rows():
    result = DataPipeline().process(valid_viirs_rows(), profile="firms_api")

    assert result["source"] == "VIIRS"
    assert result["metrics"] == {
        "input_rows": 2,
        "accepted_rows": 1,
        "rejected_rows": 1,
    }
    assert len(result["accepted"]) == 1
    assert len(result["rejected"]) == 1
    assert "quality_reasons" not in result["accepted"].columns


def test_pipeline_invalid_input_handling():
    invalid = valid_viirs_rows().drop(columns=["bright_ti4"])

    with pytest.raises(ValueError, match="Schema validation failed"):
        DataPipeline().process(invalid, profile="firms_api")


def test_pipeline_rejects_unknown_schema_profile():
    with pytest.raises(ValueError, match="Unknown schema profile"):
        DataPipeline().process(valid_viirs_rows(), profile="not-a-profile")
