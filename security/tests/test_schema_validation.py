
import csv
from datetime import date

import pytest


REQUIRED_COLUMNS = {"latitude", "longitude", "acq_date"}


@pytest.fixture
def records(tmp_path):
    path = tmp_path / "sample.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=sorted(REQUIRED_COLUMNS))
        writer.writeheader()
        writer.writerow({
            "latitude": "30.0",
            "longitude": "-9.0",
            "acq_date": "2026-11-10",
        })

    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        assert REQUIRED_COLUMNS.issubset(reader.fieldnames or [])

    assert rows
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

