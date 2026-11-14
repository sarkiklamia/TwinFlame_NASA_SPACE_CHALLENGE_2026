
"""Scheduled incremental polling of NASA FIRMS NRT data."""

from __future__ import annotations

import logging
import threading
import time

from config.api_config import load_sources_yaml
from ingestion.api_manager import APIManager

logger = logging.getLogger(__name__)


class IncrementalIngestion:
    """Run FIRMS ingestion cycles at a configured interval."""

    def __init__(
        self,
        api_manager: APIManager | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.api_manager = api_manager or APIManager()
        self.stop_event = stop_event or threading.Event()

        yaml_data = load_sources_yaml()
        ingestion_settings = yaml_data.get("ingestion", {})

        self.polling_interval_minutes = float(
            ingestion_settings.get(
                "polling_interval_minutes",
                10,
            )
        )

        if self.polling_interval_minutes <= 0:
            raise ValueError(
                "polling_interval_minutes must be positive."
            )

        self.polling_interval_seconds = (
            self.polling_interval_minutes * 60
        )

        self.day_range = int(
            ingestion_settings.get("default_day_range", 1)
        )

    def stop(self) -> None:
        """Request a graceful stop of the polling loop."""
        self.stop_event.set()

    def run_forever(
        self,
        max_cycles: int | None = None,
    ) -> int:
        """
        Run immediately, then repeat at the configured interval.

        max_cycles is useful for testing. None means continuous polling.
        Returns the number of cycles attempted.
        """

        if max_cycles is not None and max_cycles <= 0:
            return 0

        cycle_count = 0

        logger.info(
            "Starting incremental ingestion: interval=%s minutes",
            self.polling_interval_minutes,
        )

        while not self.stop_event.is_set():
            cycle_start = time.monotonic()

            cycle_count += 1

            logger.info(
                "Starting polling cycle %s",
                cycle_count,
            )

            try:
                summary = self.api_manager.run_once(
                    day_range=self.day_range,
                )

                logger.info(
                    "Polling cycle %s: status=%s requests=%s "
                    "rows=%s duration=%.2f seconds",
                    cycle_count,
                    summary.status,
                    summary.total_requests,
                    summary.total_rows,
                    time.monotonic() - cycle_start,
                )

                if summary.errors:
                    for error in summary.errors:
                        logger.error(
                            "Ingestion error: %s",
                            error,
                        )

            except Exception:
                logger.exception(
                    "Unexpected failure in polling cycle %s.",
                    cycle_count,
                )

            if (
                max_cycles is not None
                and cycle_count >= max_cycles
            ):
                break

            elapsed = time.monotonic() - cycle_start

            remaining = max(
                0.0,
                self.polling_interval_seconds - elapsed,
            )

            if remaining > 0:
                logger.info(
                    "Next polling cycle in %.1f seconds.",
                    remaining,
                )

                self.stop_event.wait(remaining)

        logger.info(
            "Incremental ingestion stopped after %s cycles.",
            cycle_count,
        )

        return cycle_count


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        ),
    )

    ingestion = IncrementalIngestion()

    try:
        ingestion.run_forever()
    except KeyboardInterrupt:
        ingestion.stop()
        logger.info("Polling interrupted by user.")
