import sys
from pathlib import Path
from io import StringIO

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.firms_client import FIRMSClient

# Small geographic area to avoid downloading a global response.
BBOX = "-13,27,-1,36"

with FIRMSClient() as client:
    for source_key in ("NOAA20", "NOAA21"):
        print("\n" + "=" * 60)
        print(f"API SOURCE: {source_key}")
        print("=" * 60)

        try:
            response = client.fetch_area(
                source_key=source_key,
                bbox=BBOX,
                day_range=1,
            )

            print("HTTP status:", response.status_code)
            print("FIRMS source:", response.firms_source)

            if not response.body.strip():
                print("Empty response body.")
                continue

            df = pd.read_csv(
                StringIO(response.body),
                nrows=5,
            )

            print("API columns:")
            print(df.columns.tolist())

            print("\nFirst rows:")
            print(df.head(3).to_string(index=False))

        except Exception as exc:
            print(f"Request failed: {type(exc).__name__}: {exc}")
