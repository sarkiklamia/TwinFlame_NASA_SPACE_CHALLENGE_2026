
import csv
import os
from pathlib import Path

import pytest


def get_sample_path():
    value = os.getenv("TWINFLAME_SAMPLE_CSV")

    if not value:
        pytest.skip(
            "Set TWINFLAME_SAMPLE_CSV to a real NASA sample file"
        )

    path = Path(value)

    if not path.is_file():
        pytest.skip(f"Sample file not available: {path}")

    return path


def test_sample_file_exists():
    path = get_sample_path()
    assert path.is_file()


def test_sample_csv_readable():
    path = get_sample_path()

    with path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)
        assert reader.fieldnames is not None
        assert len(reader.fieldnames) > 0


def test_sample_csv_has_coordinates():
    path = get_sample_path()

    with path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)
        columns = set(reader.fieldnames or [])

    assert {"latitude", "longitude"}.issubset(columns)

