
from dataclasses import replace

import pytest

from config.settings import _validate, get_settings


@pytest.fixture
def settings():
    return get_settings()


# Invalid API timeout
@pytest.mark.parametrize("value", [0, -1, -30])
def test_invalid_timeout(settings, value):
    config = replace(settings, api_timeout=value)

    with pytest.raises(ValueError, match="API_TIMEOUT"):
        _validate(config)


# Invalid API retries
@pytest.mark.parametrize("value", [-1, -5])
def test_invalid_retries(settings, value):
    config = replace(settings, api_max_retries=value)

    with pytest.raises(ValueError, match="API_TIMEOUT"):
        _validate(config)


# Invalid retry delay
@pytest.mark.parametrize("value", [-1, -10])
def test_invalid_retry_delay(settings, value):
    config = replace(settings, api_retry_delay=value)

    with pytest.raises(ValueError, match="API_TIMEOUT"):
        _validate(config)


# Invalid batch size
@pytest.mark.parametrize("value", [0, -1])
def test_invalid_batch_size(settings, value):
    config = replace(settings, batch_size=value)

    with pytest.raises(ValueError, match="BATCH_SIZE"):
        _validate(config)


# Invalid DuckDB threads
@pytest.mark.parametrize("value", [0, -1])
def test_invalid_duckdb_threads(settings, value):
    config = replace(settings, duckdb_threads=value)

    with pytest.raises(ValueError, match="DUCKDB_THREADS"):
        _validate(config)


# Invalid application environment
def test_invalid_app_environment(settings):
    config = replace(settings, app_env="invalid")

    with pytest.raises(ValueError, match="APP_ENV"):
        _validate(config)


# Invalid output format
def test_invalid_output_format(settings):
    config = replace(settings, output_format="exe")

    with pytest.raises(ValueError, match="OUTPUT_FORMAT"):
        _validate(config)


# Valid configuration
def test_valid_configuration(settings):
    _validate(settings)
