
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
        map_key="fake-secret-key",
        sources={"NOAA20": source},
    )


def test_http_error_redaction(cfg):
    url = cfg.area_url("NOAA20")

    error_message = (
        f"HTTP 500 Server Error for URL: {url}"
    )

    safe_error = cfg.redact(error_message)

    assert "fake-secret-key" not in safe_error
    assert "***" in safe_error


def test_timeout_error_redaction(cfg):
    url = cfg.area_url("NOAA20")

    error_message = f"Timeout while requesting {url}"

    safe_error = cfg.redact(error_message)

    assert "fake-secret-key" not in safe_error
    assert "***" in safe_error
