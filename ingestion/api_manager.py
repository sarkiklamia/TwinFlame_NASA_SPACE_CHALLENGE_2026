
"""High-level manager for one complete FIRMS API ingestion cycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from config.api_config import FirmsApiConfig, get_firms_config
from ingestion.firms_client import FIRMSClient
from ingestion.request_manager import (
    RequestManager,
    SourceIngestionResult,
)
from ingestion.response_handler import ResponseHandler, SavedRawFile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class APIIngestionSummary:
    ingestion_id: str
    start_time: datetime
    end_time: datetime
    source_results: tuple[SourceIngestionResult, ...]

    @property
    def total_requests(self) -> int:
        return sum(
            result.request_count
            for result in self.source_results
        )

    @property
    def total_successful_requests(self) -> int:
        return sum(
            result.successful_requests
            for result in self.source_results
        )

    @property
    def total_rows(self) -> int:
        return sum(
            result.saved_rows
            for result in self.source_results
        )

    @property
    def saved_files(self) -> tuple[SavedRawFile, ...]:
        return tuple(
            file
            for result in self.source_results
            for file in result.saved_files
        )

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(
            f"{result.source_key}: {error}"
            for result in self.source_results
            for error in result.errors
        )

    @property
    def status(self) -> str:
        if not self.source_results:
            return "NO_SOURCES"

        statuses = [
            result.status
            for result in self.source_results
        ]

        failed_statuses = {"FAILED", "NO_REQUESTS"}

        if all(status in failed_statuses for status in statuses):
            return "FAILED"

        if any(
            status in failed_statuses or status == "PARTIAL"
            for status in statuses
        ):
            return "PARTIAL"

        if any(status == "SUCCESS" for status in statuses):
            return "SUCCESS"

        return "EMPTY"


class APIManager:
    """Run and summarize one complete NRT ingestion cycle."""

    def __init__(
        self,
        config: FirmsApiConfig | None = None,
    ) -> None:
        self.config = config or get_firms_config()

    def run_once(
        self,
        day_range: int | None = None,
        on_date: str | None = None,
    ) -> APIIngestionSummary:
        ingestion_id = uuid4().hex
        start_time = datetime.now(timezone.utc)

        logger.info(
            "Starting FIRMS ingestion cycle: %s",
            ingestion_id,
        )

        source_results: list[SourceIngestionResult] = []

        with FIRMSClient(self.config) as client:
            handler = ResponseHandler(self.config)

            request_manager = RequestManager(
                client=client,
                config=self.config,
                handler=handler,
            )

            for source in self.config.enabled_sources():
                try:
                    result = request_manager.run_source(
                        source_key=source.key,
                        day_range=day_range,
                        on_date=on_date,
                    )

                    source_results.append(result)

                except Exception as exc:
                    logger.exception(
                        "Unexpected source-level failure: %s",
                        source.key,
                    )

                    source_results.append(
                        SourceIngestionResult(
                            source_key=source.key,
                            request_count=0,
                            successful_requests=0,
                            empty_responses=0,
                            saved_rows=0,
                            errors=(str(exc),),
                        )
                    )

        end_time = datetime.now(timezone.utc)

        summary = APIIngestionSummary(
            ingestion_id=ingestion_id,
            start_time=start_time,
            end_time=end_time,
            source_results=tuple(source_results),
        )

        logger.info(
            "FIRMS ingestion cycle completed: id=%s status=%s "
            "requests=%s successful=%s rows=%s files=%s",
            summary.ingestion_id,
            summary.status,
            summary.total_requests,
            summary.total_successful_requests,
            summary.total_rows,
            len(summary.saved_files),
        )

        return summary
