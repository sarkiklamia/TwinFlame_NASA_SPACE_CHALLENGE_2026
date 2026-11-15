import pytest

from config.api_config import FirmsApiConfig, SensorSource


def make_config(base_url):
    source = SensorSource(
        key="NOAA20",
        firms_source="VIIRS_NOAA20_NRT",
        instrument="VIIRS",
        resolution_m=375,
        raw_subdir="NOAA20",
        required_columns=(),
    )
    return FirmsApiConfig(
        base_url=base_url,
        area_endpoint="area/csv",
        map_key="FAKE_TEST_KEY",
        sources={"NOAA20": source},
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/api",
        "https://user:pass@example.com/api",
        "https://example.com/api?token=secret",
        "https://example.com/api#fragment",
        "https:///api",
    ],
)
def test_unsafe_base_urls_are_rejected(url):
    with pytest.raises(ValueError):
        make_config(url).area_url("NOAA20")


def test_https_base_url_is_accepted():
    cfg = make_config("https://example.com/api")
    assert cfg.area_url("NOAA20").startswith(
        "https://example.com/api/"
    )
