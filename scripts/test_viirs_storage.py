import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from io import StringIO
import pandas as pd

from config.api_config import get_firms_config
from ingestion.firms_client import FIRMSClient
from ingestion.response_handler import ResponseHandler
from storage.parquet_writer import ParquetWriter


def main():
    config = get_firms_config()
    client = FIRMSClient(config)
    handler = ResponseHandler(config)
    writer = ParquetWriter()

    bbox = "-120,-60,-30,15"

    try:
        for source in ("NOAA20", "NOAA21"):
            print(f"\n{'=' * 55}")
            print(f"TESTING {source}")

            response = client.fetch_area(
                source_key=source,
                bbox=bbox,
                day_range=1
            )

            print("FIRMS source:", response.firms_source)
            print("Response bytes:", len(response.body))

            if not response.body or not response.body.strip():
                print("EMPTY RESPONSE: nothing to save.")
                continue

            original = pd.read_csv(StringIO(response.body))

            if original.empty:
                print("NO DETECTIONS: headers only; no file created.")
                continue

            print("API rows:", len(original))

            result = handler.handle(
                response,
                partition_id="south_america_storage_test"
            )

            print("Handler status:", result.status)

            if result.status != "SAVED":
                raise RuntimeError(
                    f"{source}: response was not saved."
                )

            saved = writer.read_file(result.saved_file.path)

            required = set(config.get_source(source).required_columns)
            missing = required - set(saved.columns)

            if missing:
                raise RuntimeError(
                    f"{source}: missing columns {sorted(missing)}"
                )

            if len(original) != len(saved):
                raise RuntimeError(
                    f"{source}: API/Parquet row count mismatch."
                )

            brightness = [
                c for c in (
                    "brightness", "bright_t31",
                    "bright_ti4", "bright_ti5"
                )
                if c in saved.columns
            ]

            print("Saved file:", result.saved_file.path)
            print("Saved rows:", len(saved))
            print("Native brightness fields:", brightness)
            print(f"{source}: STORAGE PASSED")

        print("\nVIIRS API STORAGE TEST FINISHED")

    finally:
        client.close()


if __name__ == "__main__":
    main()
