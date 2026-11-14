
import csv
import os
from datetime import date
from pathlib import Path

import pytest


REQUIRED_COLUMNS = {
    "latitude",
    "longitude",
    "acq_date",
}


@pytest.fixture
def records():
    value = os.getenv("TWINFLAME_SAMPLE_CSV")

    if not value:
        pytest.skip("TWINFLAME_SAMPLE_CSV not configured")

    path = Path(value)

    if not path.is_file():
        pytest.skip("NASA sample CSV not available")

    with path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])

        if not REQUIRED_COLUMNS.issubset(columns):
            pytest.fail("Required NASA columns missing")

        rows = list(reader)

    if not rows:
        pytest.skip("Sample has no hotspot records")

    return rows


def test_valid_latitude(records):
    for row in records:
        latitude = float(row["latitude"])
        assert -90 <= latitude <= 90


def test_valid_longitude(records):
    for row in records:
        longitude = float(row["longitude"])
        assert -180 <= longitude <= 180


def test_valid_acquisition_date(records):
    for row in records:
        date.fromisoformat(row["acq_date"])


def test_required_columns(records):
    for row in records:
        assert REQUIRED_COLUMNS.issubset(row.keys())

