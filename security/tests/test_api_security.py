
import pytest
from dataclasses import replace

from config.api_config import (
    FirmsApiConfig,
    SensorSource,
    validate_bbox,
    validate_date,
)


@pytest.fixture
def cfg():
    source = SensorSource(
        key="NOAA20",
        firms_source="VIIRS_NOAA20_NRT",
        instrument="VIIRS",
        resolution_m=375,
        raw_subdir="NOAA20",
        required_columns=("latitude", "longitude"),
    )

    return FirmsApiConfig(
        base_url="https://example.org/api",
        area_endpoint="area/csv",
        map_key="fake-secret-key",
        sources={"NOAA20": source},
    )


# TEST 1: Protect API key in logs
def test_api_key_not_exposed(cfg):
    url = cfg.area_url("NOAA20")
    safe_url = cfg.redact(url)

    assert "fake-secret-key" not in safe_url
    assert "***" in safe_url


# TEST 2: Protect API key in object representation
def test_api_key_hidden_in_repr(cfg):
    assert "fake-secret-key" not in repr(cfg)


# TEST 3: Reject invalid latitude
@pytest.mark.parametrize("bbox", [
    "-10,100,-1,110",
    "-10,-100,-1,30",
])
def test_invalid_latitude(bbox):
    with pytest.raises(ValueError):
        validate_bbox(bbox)


# TEST 4: Reject invalid longitude
@pytest.mark.parametrize("bbox", [
    "-200,20,-1,30",
    "-10,20,200,30",
])
def test_invalid_longitude(bbox):
    with pytest.raises(ValueError):
        validate_bbox(bbox)


# TEST 5: Reject reversed coordinates
@pytest.mark.parametrize("bbox", [
    "10,20,-10,30",
    "-10,40,-1,20",
])
def test_reversed_bbox(bbox):
    with pytest.raises(ValueError):
        validate_bbox(bbox)


# TEST 6: Reject invalid calendar dates
@pytest.mark.parametrize("date_value", [
    "2026-02-30",
    "2026-13-01",
    "not-a-date",
    "2026/11/14",
])
def test_invalid_dates(date_value):
    with pytest.raises(ValueError):
        validate_date(date_value)


# TEST 7: Reject invalid day range types
@pytest.mark.parametrize("days", [
    0,
    -1,
    6,
    True,
    1.5,
])
def test_invalid_day_range(cfg, days):
    with pytest.raises(ValueError):
        cfg.area_url("NOAA20", day_range=days)


# TEST 8: Reject missing API key
def test_missing_api_key(cfg):
    invalid_cfg = replace(cfg, map_key="")

    with pytest.raises(RuntimeError):
        invalid_cfg.area_url("NOAA20")


# TEST 9: Allow valid bounding box
def test_valid_bbox():
    validate_bbox("-10,27,-1,36")


# TEST 10: Allow valid date
def test_valid_date():
    assert validate_date("2026-11-14") == "2026-11-14"
