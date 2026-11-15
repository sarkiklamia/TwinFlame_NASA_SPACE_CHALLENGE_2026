
"""Continuous worldwide NASA FIRMS API ingestion."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    harmonization
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config.api_config import get_firms_config, load_sources_yaml
from ingestion.api_incremental_processor import APIIncrementalProcessor
from ingestion.firms_client import FIRMSClient
from ingestion.response_handler import ResponseHandler
from harmonization.v3.phases.phase_09_incremental_processing.incremental_runner import (
    DEFAULT_OUTPUT_ROOT as PHASE09_OUTPUT_ROOT,
    DEFAULT_PHASE08_ROOT,
    run_phase_09,
)


from config.api_config import get_firms_config, load_sources_yaml
from ingestion.firms_client import FIRMSClient
from ingestion.response_handler import ResponseHandler
 main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

logger = logging.getLogger("firms_worldwide_ingestion")
stop_event = threading.Event()


def request_stop(signum, frame):
    logger.info("Stop requested. Finishing current operation...")
    stop_event.set()


def main():
    config = get_firms_config()

    if not config.map_key or not str(config.map_key).strip():
        raise RuntimeError("FIRMS_MAP_KEY is missing from .env")

    yaml_data = load_sources_yaml()
    ingestion_settings = yaml_data.get("ingestion", {})

    interval_minutes = float(
        ingestion_settings.get("polling_interval_minutes", 10)
    )

    configured_days = int(
        ingestion_settings.get("default_day_range", 1)
    )
 harmonization
    harmonization_interval_minutes = float(
        ingestion_settings.get("harmonization_interval_minutes", 60)
    )
 main

    # Include yesterday as well as today.
    day_range = max(2, configured_days)

    if interval_minutes <= 0:
        raise ValueError("Polling interval must be positive.")
 harmonization
    if harmonization_interval_minutes <= 0:
        raise ValueError("Harmonization interval must be positive.")
 main

    if not 1 <= day_range <= 5:
        raise ValueError("FIRMS day_range must be between 1 and 5.")

    sources = config.enabled_sources()

    if not sources:
        raise RuntimeError("No enabled FIRMS sources found.")

    for source in sources:
        config.raw_dir(source.key).mkdir(
            parents=True,
            exist_ok=True,
        )

    handler = ResponseHandler(config)
 harmonization
    processor = APIIncrementalProcessor(raw_api_dir=config.raw_api_dir)
main

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    interval_seconds = interval_minutes * 60
 harmonization
    harmonization_interval_seconds = harmonization_interval_minutes * 60
    last_harmonization_attempt = None
 main
    cycle = 0

    logger.info("Starting worldwide FIRMS ingestion.")
    logger.info("Sensors: %s", ", ".join(s.key for s in sources))
    logger.info("Area: world")
    logger.info("Day range: %s days", day_range)
    logger.info("Polling interval: %s minutes", interval_minutes)
 harmonization
    logger.info(
        "Phase 09 harmonization interval: %s minutes",
        harmonization_interval_minutes,
    )
 main
    logger.info("Requests per cycle: %s", len(sources))

    with FIRMSClient(config) as client:

        while not stop_event.is_set():
            cycle += 1
            cycle_start = time.monotonic()

            total_rows = 0
            saved_files = 0
            successful_requests = 0

            logger.info("========== CYCLE %s ==========", cycle)

            for source in sources:
                if stop_event.is_set():
                    break

                try:
                    logger.info(
                        "Requesting worldwide data: %s (%s)",
                        source.key,
                        source.firms_source,
                    )

                    response = client.fetch_area(
                        source_key=source.key,
                        bbox="world",
                        day_range=day_range,
                    )

                    successful_requests += 1

                    result = handler.handle(
                        response=response,
                        partition_id="world",
                    )

                    if result.saved_file is not None:
                        saved_files += 1
                        total_rows += result.row_count

                        logger.info(
                            "%s: saved %s detections to %s",
                            source.key,
                            result.row_count,
                            result.saved_file.path,
                        )
                    else:
                        logger.warning(
                            "%s: valid response, but no detections.",
                            source.key,
                        )

                except Exception:
                    logger.exception(
                        "Failed to ingest source %s.",
                        source.key,
                    )

harmonization
            # Import every completed response file, including files left
            # pending by an earlier interrupted or failed processing cycle.
            processing_completed = False
            try:
                processing = processor.process_pending()
                processing_completed = True
                logger.info(
                    "CYCLE %s PROCESSING | succeeded=%s failed=%s skipped=%s new_rows=%s",
                    cycle,
                    processing.succeeded,
                    processing.failed,
                    processing.skipped_files,
                    processing.inserted_rows,
                )
            except Exception:
                logger.exception(
                    "Could not process pending API files after cycle %s.",
                    cycle,
                )

            now = time.monotonic()
            if processing_completed and (
                last_harmonization_attempt is None
                or now - last_harmonization_attempt
                >= harmonization_interval_seconds
            ):
                try:
                    harmonization = run_phase_09(
                        database=processor.database_path,
                        phase08_output_root=DEFAULT_PHASE08_ROOT,
                        output_root=PHASE09_OUTPUT_ROOT,
                    )
                    logger.info(
                        "PHASE 09 | status=%s watermark=%s new_detections=%s "
                        "affected_dates=%s message=%s error=%s",
                        harmonization.get("status"),
                        harmonization.get("watermark_processing_id"),
                        harmonization.get("new_api_detection_count", 0),
                        harmonization.get("affected_date_count", 0),
                        harmonization.get("message", ""),
                        harmonization.get("error", ""),
                    )
                except Exception:
                    logger.exception(
                        "Phase 09 incremental harmonization failed after cycle %s.",
                        cycle,
                    )
                finally:
                    last_harmonization_attempt = time.monotonic()

 main
            elapsed = time.monotonic() - cycle_start

            logger.info(
                "CYCLE %s SUMMARY | successful requests=%s/%s "
                "| detections=%s | files=%s | duration=%.1fs",
                cycle,
                successful_requests,
                len(sources),
                total_rows,
                saved_files,
                elapsed,
            )

            if stop_event.is_set():
                break

            remaining = max(0, interval_seconds - elapsed)

            logger.info(
                "Next cycle starts in %.1f seconds.",
                remaining,
            )

            stop_event.wait(remaining)

    logger.info("Worldwide ingestion stopped.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Could not start FIRMS ingestion.")
        raise
