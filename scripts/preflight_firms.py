
"""Controlled preflight checks for NASA FIRMS NRT ingestion.

This script does NOT start continuous polling.
It sends at most one small-area request per enabled source.
"""

from __future__ import annotations

import logging
import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import requests

# Make both the project root and src directory importable.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.api_config import (
    get_firms_config,
    load_sources_yaml,
)
from config.settings import get_settings
from ingestion.firms_client import FIRMSClient
from ingestion.geographic_partitioner import get_partitions
from ingestion.response_handler import ResponseHandler


logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)

logger = logging.getLogger("firms_preflight")

# Small test area in northern Morocco.
# Format: west, south, east, north.
TEST_BBOX = "-6.5,35.0,-5.5,36.0"

EXPECTED_SOURCES = {
    "MODIS": "MODIS_NRT",
    "NOAA20": "VIIRS_NOAA20_NRT",
    "NOAA21": "VIIRS_NOAA21_NRT",
}


def report(name: str, passed: bool, details: str = "") -> bool:
    status = "PASS" if passed else "FAIL"

    print(f"[{status}] {name}")

    if details:
        print(f"       {details}")

    return passed


def check_map_key_status(config) -> dict | None:
    """Read transaction usage without printing the secret URL."""

    endpoint = (
        "https://firms.modaps.eosdis.nasa.gov/"
        "mapserver/mapkey_status/"
    )

    try:
        response = requests.get(
            endpoint,
            params={"MAP_KEY": config.map_key},
            timeout=config.timeout,
        )

        response.raise_for_status()
        data = response.json()

        return data

    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "Could not retrieve transaction status: %s",
            exc,
        )
        return None


def validate_sources(config) -> bool:
    enabled = {
        source.key: source.firms_source
        for source in config.enabled_sources()
    }

    if enabled != EXPECTED_SOURCES:
        return report(
            "Enabled FIRMS sources",
            False,
            f"Expected {EXPECTED_SOURCES}; received {enabled}",
        )

    return report(
        "Enabled FIRMS sources",
        True,
        ", ".join(
            f"{key}={value}"
            for key, value in enabled.items()
        ),
    )


def validate_partitioning(yaml_data) -> bool:
    try:
        partitions = get_partitions(yaml_data)

        settings = yaml_data.get("partitioning", {})
        strategy = settings.get("strategy", "single")

        if strategy == "grid":
            expected_count = (
                360 / float(settings["tile_size_degrees"])
            ) * (
                180 / float(settings["tile_size_degrees"])
            )

            if len(partitions) != expected_count:
                return report(
                    "Geographic partitioning",
                    False,
                    f"Expected {expected_count:g} tiles; "
                    f"received {len(partitions)}",
                )

        return report(
            "Geographic partitioning",
            True,
            f"Strategy={strategy}; tiles={len(partitions)}",
        )

    except Exception as exc:
        return report(
            "Geographic partitioning",
            False,
            str(exc),
        )


def validate_dataframe(dataframe, source) -> bool:
    required = set(source.required_columns)
    actual = set(dataframe.columns)

    missing = required - actual

    if missing:
        return report(
            f"{source.key} CSV schema",
            False,
            f"Missing columns: {sorted(missing)}",
        )

    if dataframe.empty:
        return report(
            f"{source.key} CSV schema",
            True,
            "Headers are valid; response contains zero detections.",
        )

    latitude = pd.to_numeric(
        dataframe["latitude"],
        errors="coerce",
    )

    longitude = pd.to_numeric(
        dataframe["longitude"],
        errors="coerce",
    )

    invalid_coordinates = (
        latitude.isna()
        | longitude.isna()
        | ~latitude.between(-90, 90)
        | ~longitude.between(-180, 180)
    )

    if invalid_coordinates.any():
        return report(
            f"{source.key} coordinates",
            False,
            f"{int(invalid_coordinates.sum())} invalid rows",
        )

    return report(
        f"{source.key} CSV schema and coordinates",
        True,
        f"{len(dataframe)} rows; "
        f"{len(dataframe.columns)} columns; "
        "coordinates valid",
    )


def test_source(client, handler, config, source_key) -> bool:
    """Fetch and validate one small-area response."""

    print(f"\n--- Testing {source_key} ---")

    try:
        response = client.fetch_area(
            source_key=source_key,
            bbox=TEST_BBOX,
            day_range=1,
            on_date=None,
        )

        report(
            f"{source_key} HTTP response",
            response.status_code == 200,
            f"HTTP {response.status_code}",
        )
        if response.status_code != 200:
           return False

        dataframe = pd.read_csv(
            StringIO(response.body)
        )

        source = config.get_source(source_key)

        schema_ok = validate_dataframe(
            dataframe,
            source,
        )

        if not schema_ok:
            return False

        result = handler.handle(
            response=response,
            partition_id="preflight_test",
        )

        if result.status == "EMPTY":
            report(
                f"{source_key} response handling",
                True,
                "Valid CSV, but no detections in the test area.",
            )
            return True

        saved_file = result.saved_file

        if saved_file is None or not saved_file.path.is_file():
            return report(
                f"{source_key} Parquet file",
                False,
                "Expected output file was not created.",
            )

        report(
            f"{source_key} Parquet file",
            True,
            str(saved_file.path.relative_to(PROJECT_ROOT)),
        )

        parquet = pd.read_parquet(saved_file.path)

        parquet_ok = (
            len(parquet) == result.row_count
            and set(source.required_columns).issubset(
                parquet.columns
            )
        )

        return report(
            f"{source_key} Parquet round-trip",
            parquet_ok,
            f"CSV rows={result.row_count}; "
            f"Parquet rows={len(parquet)}",
        )

    except Exception as exc:
        return report(
            f"{source_key} API integration",
            False,
            str(exc),
        )


def main() -> int:
    print("\n========== FIRMS PREFLIGHT CHECKS ==========\n")

    checks: list[bool] = []

    try:
        settings = get_settings()
        settings.require_firms_key()

        config = get_firms_config()
        yaml_data = load_sources_yaml()

        checks.append(
            report(
                "Configuration and API key",
                True,
                "Settings and FIRMS configuration loaded.",
            )
        )

    except Exception as exc:
        report(
            "Configuration and API key",
            False,
            str(exc),
        )
        return 1

    checks.append(validate_sources(config))
    checks.append(validate_partitioning(yaml_data))

    before = check_map_key_status(config)

    if before:
        print(
            "\nFIRMS quota before tests:",
            {
                "current_transactions":
                    before.get("current_transactions"),
                "transaction_limit":
                    before.get("transaction_limit"),
                "transaction_interval":
                    before.get("transaction_interval"),
            },
        )

    handler = ResponseHandler(config)

    with FIRMSClient(config) as client:
        for source in config.enabled_sources():
            checks.append(
                test_source(
                    client=client,
                    handler=handler,
                    config=config,
                    source_key=source.key,
                )
            )

    after = check_map_key_status(config)

    if before and after:
        before_count = before.get("current_transactions")
        after_count = after.get("current_transactions")

        print("\nFIRMS quota after tests:", {
            "current_transactions": after_count,
            "transaction_limit": after.get("transaction_limit"),
            "transaction_interval": after.get(
                "transaction_interval"
            ),
        })

        if (
            isinstance(before_count, (int, float))
            and isinstance(after_count, (int, float))
        ):
            print(
                "Observed transaction-count difference:",
                after_count - before_count,
            )
            print(
                "Note: this is an observed difference, "
                "not a guaranteed per-request cost."
            )
    else:
        print(
            "\nWARNING: Transaction usage could not be compared."
        )

    print("\n========== PREFLIGHT SUMMARY ==========")

    passed = sum(checks)
    failed = len(checks) - passed

    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed:
        print(
            "\nPreflight failed. Do not start continuous polling."
        )
        return 1

    print(
        "\nPreflight passed. Global polling is still NOT authorized "
        "by this test; review transaction usage and schemas first."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
