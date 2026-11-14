
"""Coordinate geographic API requests for one FIRMS source."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from config.api_config import (
    FirmsApiConfig,
    get_firms_config,
    load_sources_yaml,
)
from ingestion.firms_client import FIRMSClient
from ingestion.geographic_partitioner import get_partitions
from ingestion.response_handler import (
    ResponseHandler,
    SavedRawFile,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceIngestionResult:
    source_key: str
    request_count: int
    successful_requests: int
    empty_responses: int
    saved_rows: int
    saved_files: tuple[SavedRawFile, ...] = field(
        default_factory=tuple
    )
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        if self.request_count == 0:
            return "NO_REQUESTS"

        if self.successful_requests == 0:
            return "FAILED"

        if self.errors:
            return "PARTIAL"

        if self.saved_files:
            return "SUCCESS"

        return "EMPTY"


class RequestManager:
    """Manage all requests and responses for a single source."""

    def __init__(
        self,
        client: FIRMSClient,
        config: FirmsApiConfig | None = None,
        handler: ResponseHandler | None = None,
    ) -> None:
        self.config = config or get_firms_config()
        self.client = client
        self.handler = handler or ResponseHandler(self.config)

    def run_source(
        self,
        source_key: str,
        day_range: int | None = None,
        on_date: str | None = None,
    ) -> SourceIngestionResult:
        source = self.config.get_source(source_key)

        if not source.enabled:
            logger.info(
                "Skipping disabled FIRMS source: %s",
                source_key,
            )
            return SourceIngestionResult(
                source_key=source_key,
                request_count=0,
                successful_requests=0,
                empty_responses=0,
                saved_rows=0,
            )

        yaml_data = load_sources_yaml()
        ingestion_settings = yaml_data.get("ingestion", {})

        if day_range is None:
            day_range = int(
                ingestion_settings.get("default_day_range", 1)
            )

        partitions = get_partitions(yaml_data)

        request_count = 0
        successful_requests = 0
        empty_responses = 0
        saved_rows = 0

        saved_files: list[SavedRawFile] = []
        errors: list[str] = []

        logger.info(
            "Starting source ingestion: source=%s partitions=%s",
            source_key,
            len(partitions),
        )

        for partition in partitions:
            request_count += 1

            try:
                response = self.client.fetch_area(
                    source_key=source_key,
                    bbox=partition.bbox,
                    day_range=day_range,
                    on_date=on_date,
                )

                successful_requests += 1

                handling_result = self.handler.handle(
                    response=response,
                    partition_id=partition.partition_id,
                )

                if handling_result.status == "EMPTY":
                    empty_responses += 1
                    continue

                if handling_result.saved_file is not None:
                    saved_files.append(
                        handling_result.saved_file
                    )
                    saved_rows += handling_result.row_count

            except Exception as exc:
                message = (
                    f"{partition.partition_id} "
                    f"({partition.bbox}): {exc}"
                )

                errors.append(message)

                logger.exception(
                    "Partition ingestion failed: source=%s partition=%s",
                    source_key,
                    partition.partition_id,
                )

        result = SourceIngestionResult(
            source_key=source_key,
            request_count=request_count,
            successful_requests=successful_requests,
            empty_responses=empty_responses,
            saved_rows=saved_rows,
            saved_files=tuple(saved_files),
            errors=tuple(errors),
        )

        logger.info(
            "Source ingestion finished: source=%s status=%s "
            "requests=%s successful=%s rows=%s errors=%s",
            source_key,
            result.status,
            result.request_count,
            result.successful_requests,
            result.saved_rows,
            len(result.errors),
        )

        return result
