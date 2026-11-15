
import os
import csv
import io
import requests
import pytest

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = "https://firms.modaps.eosdis.nasa.gov"

SOURCES = [
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
]

REQUIRED_COLUMNS = {
    "latitude",
    "longitude",
    "acq_date",
    "satellite",
    "confidence",
}

@pytest.mark.parametrize("source", SOURCES)
def test_csv_retrieval(source):
    key = os.getenv("NASA_MAP_KEY")
    assert key, "NASA_MAP_KEY missing"

    area = "-10,30,-7,32"
    date = "2026-11-10"

    url = (
        f"{BASE_URL}/api/area/csv/"
        f"{key}/{source}/{area}/1/{date}"
    )

    response = requests.get(url, timeout=30)

    print(f"\nSource: {source}")
    print("HTTP status:", response.status_code)
    print("Content type:", response.headers.get("Content-Type"))

    # Never print the request URL: it contains MAP_KEY
    assert response.status_code == 200, (
        f"HTTP status: {response.status_code}"
    )

    reader = csv.DictReader(io.StringIO(response.text))
    columns = set(reader.fieldnames or [])

    print("CSV columns:", sorted(columns))

    if not REQUIRED_COLUMNS.issubset(columns):
        print("Response: missing expected fire data columns")
        print("Response size:", len(response.content), "bytes")
        pytest.fail("Unexpected CSV response format")

    rows = list(reader)

    print("Fire detections:", len(rows))

    if not rows:
        print("Valid CSV, but no detections for this area/date")
        return

    for row in rows:
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])

        assert -90 <= latitude <= 90
        assert -180 <= longitude <= 180

    print("CSV structure and coordinates: VALID")
