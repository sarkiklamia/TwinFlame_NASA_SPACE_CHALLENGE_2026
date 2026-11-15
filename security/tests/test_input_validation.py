
import math
from datetime import date
import pytest


def validate_coordinates(latitude, longitude):
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        return False

    if not isinstance(latitude, (int, float)):
        return False

    if not isinstance(longitude, (int, float)):
        return False

    return (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def validate_date(value):
    try:
        parsed = date.fromisoformat(value)
        return parsed <= date.today()
    except (ValueError, TypeError):
        return False


# TEST 1: Valid coordinates
@pytest.mark.parametrize("lat,lon", [
    (30, -9),
    (90, 180),
    (-90, -180),
    (0, 0),
])
def test_valid_coordinates(lat, lon):
    assert validate_coordinates(lat, lon)


# TEST 2: Invalid coordinates
@pytest.mark.parametrize("lat,lon", [
    (200, -9),
    (30, 500),
    (-100, 0),
    ("abc", -9),
    (None, 20),
    (float("nan"), 0),
    (True, 0),
])
def test_invalid_coordinates(lat, lon):
    assert not validate_coordinates(lat, lon)


# TEST 3: Valid date
def test_valid_date():
    assert validate_date("2026-11-10")


# TEST 4: Invalid dates
@pytest.mark.parametrize("value", [
    "2026-13-40",
    "hello",
    "",
    None,
])
def test_invalid_date(value):
    assert not validate_date(value)
