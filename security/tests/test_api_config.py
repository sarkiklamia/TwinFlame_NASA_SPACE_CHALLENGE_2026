
import pytest

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


def test_valid_url(cfg):
    url = cfg.area_url(
        "NOAA20", "-10,27,-1,36", day_range=1
    )

    assert "VIIRS_NOAA20_NRT" in url
    assert "/area/csv/" in url


def test_secret_redaction(cfg):
    url = cfg.area_url("NOAA20")

    safe = cfg.redact(url)

    assert "fake-test-key" not in safe
    assert "***" in safe


def test_missing_key(cfg):
    from dataclasses import replace

    missing = replace(cfg, map_key="")

    with pytest.raises(RuntimeError):
        missing.area_url("NOAA20")


def test_invalid_source(cfg):
    with pytest.raises(KeyError):
        cfg.get_source("UNKNOWN")


@pytest.mark.parametrize("days", [0, -1, 6])
def test_invalid_day_range(cfg, days):
    with pytest.raises(ValueError):
        cfg.area_url("NOAA20", day_range=days)


def test_invalid_bbox_format(cfg):
    with pytest.raises(ValueError):
        cfg.area_url("NOAA20", bbox="invalid")


@pytest.mark.xfail(
    strict=True,
    reason="Current implementation checks bbox syntax but not coordinate bounds",
)
def test_out_of_range_coordinates(cfg):
    with pytest.raises(ValueError):
        cfg.area_url("NOAA20", bbox="-10,200,-1,300")


@pytest.mark.xfail(
    strict=True,
    reason="Current implementation does not validate string dates",
)
def test_invalid_date(cfg):
    with pytest.raises(ValueError):
        cfg.area_url("NOAA20", on_date="not-a-date")

