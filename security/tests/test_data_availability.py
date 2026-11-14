
import os
import csv
import io
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

def test_noaa_data_availability():
    key = os.getenv("NASA_MAP_KEY")
    assert key, "NASA_MAP_KEY missing"

    url = (
        "https://firms.modaps.eosdis.nasa.gov/"
        f"api/data_availability/csv/{key}/all"
    )

    response = requests.get(url, timeout=20)
    assert response.status_code == 200

    rows = list(csv.DictReader(io.StringIO(response.text)))

    sources = [
        "VIIRS_NOAA20_NRT",
        "VIIRS_NOAA21_NRT"
    ]

    for source in sources:
        matches = [
            row for row in rows
            if row["data_id"] == source
        ]

        assert matches, f"{source} not found"

        row = matches[0]

        assert row["min_date"], "Missing min_date"
        assert row["max_date"], "Missing max_date"

        print(f"\n{source}")
        print("First available:", row["min_date"])
        print("Last available:", row["max_date"])
