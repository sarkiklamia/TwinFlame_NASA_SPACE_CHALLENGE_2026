import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import ingestion.request_manager as request_manager_module

from config.api_config import load_sources_yaml
from ingestion.api_manager import APIManager
from storage.parquet_writer import ParquetWriter


# Preserve the real configuration loader.
original_loader = request_manager_module.load_sources_yaml

# Override only the partitioning settings in memory.
def load_test_config():
    config = original_loader()
    config["partitioning"] = {
        "strategy": "single",
        "bbox": "-120,-60,-30,15"
    }
    return config


def main():
    request_manager_module.load_sources_yaml = load_test_config

    try:
        print("Starting controlled APIManager integration test.")
        print("Sources: MODIS, NOAA20, NOAA21")
        print("Bounding box: -120,-60,-30,15")
        print("Expected requests: 3")

        manager = APIManager()
        summary = manager.run_once(day_range=1)

        print("\n========== INGESTION SUMMARY ==========")
        print("Status:", summary.status)
        print("Total requests:", summary.total_requests)
        print("Successful requests:", summary.total_successful_requests)
        print("Total saved rows:", summary.total_rows)
        print("Saved files:", len(summary.saved_files))

        for result in summary.source_results:
            print(f"\nSource: {result.source_key}")
            print("Status:", result.status)
            print("Requests:", result.request_count)
            print("Successful:", result.successful_requests)
            print("Empty responses:", result.empty_responses)
            print("Saved rows:", result.saved_rows)
            print("Errors:", len(result.errors))

            for error in result.errors:
                print("ERROR:", error)

        # Verify manager-level request execution.
        assert summary.total_requests == 3, (
            f"Expected 3 requests, got {summary.total_requests}"
        )

        assert summary.total_successful_requests == 3, (
            "Not all three API requests succeeded."
        )

        assert not summary.errors, (
            f"Ingestion errors: {summary.errors}"
        )

        # Verify every saved Parquet file can be read.
        writer = ParquetWriter()

        for saved_file in summary.saved_files:
            dataframe = writer.read_file(saved_file.path)

            assert len(dataframe) == saved_file.row_count

            print(
                f"\nREADBACK OK: {saved_file.source_key} "
                f"({len(dataframe)} rows)"
            )

        print("\nAPI MANAGER INTEGRATION TEST: PASSED")

    finally:
        request_manager_module.load_sources_yaml = original_loader


if __name__ == "__main__":
    main()
