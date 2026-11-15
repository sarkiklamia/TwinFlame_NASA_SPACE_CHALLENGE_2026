
import pytest
from dataclasses import replace
from datetime import date

from config.api_config import FirmsApiConfig, SensorSource


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
        map_key="fake-test-key",
        sources={"NOAA20": source},
    )


# TEST 1: Valid API URL
def test_valid_url(cfg):
    url = cfg.area_url(
        "NOAA20",
        "-10,27,-1,36",
        day_range=1,
    )

    assert "VIIRS_NOAA20_NRT" in url
    assert "/area/csv/" in url


# TEST 2: API key redaction
def test_secret_redaction(cfg):
    url = cfg.area_url("NOAA20")

    safe_url = cfg.redact(url)

    assert "fake-test-key" not in safe_url
    assert "***" in safe_url


# TEST 3: Missing API key
def test_missing_key(cfg):
    missing = replace(cfg, map_key="")

    with pytest.raises(RuntimeError):
        missing.area_url("NOAA20")


# TEST 4: Invalid satellite source
def test_invalid_source(cfg):
    with pytest.raises(KeyError):
        cfg.get_source("UNKNOWN")


# TEST 5: Invalid day range
@pytest.mark.parametrize("days", [0, -1, 6])
def test_invalid_day_range(cfg, days):
    with pytest.raises(ValueError):
        cfg.area_url("NOAA20", day_range=days)


# TEST 6: Invalid bounding box format
def test_invalid_bbox_format(cfg):
    with pytest.raises(ValueError):
        cfg.area_url("NOAA20", bbox="invalid")


# TEST 7: Out-of-range coordinates
def test_out_of_range_coordinates(cfg):
    with pytest.raises(ValueError):
        cfg.area_url(
            "NOAA20",
            bbox="-10,200,-1,300",
        )


# TEST 8: Invalid date
def test_invalid_date(cfg):
    with pytest.raises(ValueError):
        cfg.area_url(
            "NOAA20",
            on_date="not-a-date",
        )
