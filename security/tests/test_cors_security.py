
from dataclasses import replace

import pytest

from config.settings import _validate, get_settings


def test_production_wildcard_cors():
    settings = replace(
        get_settings(),
        app_env="production",
        cors_allowed_origins=("*",),
    )

    with pytest.raises(ValueError):
        _validate(settings)
