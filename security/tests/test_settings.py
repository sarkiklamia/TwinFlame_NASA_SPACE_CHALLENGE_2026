import pytest
from dataclasses import replace

from config.settings import get_settings


@pytest.fixture
def settings():
    return get_settings()


def test_secret_not_in_repr(settings):
    fake = replace(settings, firms_map_key="fake-secret")
    assert "fake-secret" not in repr(fake)


def test_missing_map_key(settings):
    fake = replace(settings, firms_map_key="")
    with pytest.raises(RuntimeError):
        fake.require_firms_key()


def test_placeholder_map_key(settings):
    fake = replace(
        settings,
        firms_map_key="your_firms_map_key_here"
    )
    with pytest.raises(RuntimeError):
        fake.require_firms_key()


def test_valid_map_key(settings):
    fake = replace(settings, firms_map_key="test-key")
    assert fake.require_firms_key() == "test-key"


def test_default_cors(settings):
    assert isinstance(settings.cors_allowed_origins, tuple)


def test_production_flag(settings):
    fake = replace(settings, app_env="production")
    assert fake.is_production is True
