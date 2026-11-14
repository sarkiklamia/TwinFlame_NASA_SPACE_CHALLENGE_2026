
"""
FIRMS API response validation and raw Parquet storage.

Responsibilities:
- Validate API response content.
- Parse FIRMS CSV responses.
- Validate required source-specific columns.
- Preserve valid raw detections as Parquet.
- Write files atomically to avoid incomplete outputs.

This module does not clean, standardize, or deduplicate detections.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile

from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd

from config.api_config import FirmsApiConfig
from ingestion.firms_client import FIRMSResponse


logger = logging.getLogger(__name__)


class ResponseValidationError(Exception):
    """Raised when a FIRMS response is invalid."""


@dataclass(frozen=True)
class SavedRawFile:
    """Metadata describing a successfully saved raw response."""

    source_key: str
    partition_id: str
    path: Path
    row_count: int
    requested_at: datetime


@dataclass(frozen=True)
class ResponseHandlingResult:
    """Result of parsing and storing one API response."""

    status: str
    source_key: str
    partition_id: str
    row_count: int
    saved_file: SavedRawFile | None = None


class ResponseHandler:
    """Validate FIRMS CSV responses and save valid data as Parquet."""

    def __init__(self, config: FirmsApiConfig):
        self.config = config

    def handle(
        self,
        response: FIRMSResponse,
        partition_id: str,
    ) -> ResponseHandlingResult:
        """
        Process one successful HTTP response.

        EMPTY:
            The response contains valid CSV headers but no detections.

        SAVED:
            The response contains valid detections and was saved.

        Raises:
            ResponseValidationError:
                Invalid response body, malformed CSV, or missing columns.
        """

        source = self.config.get_source(response.source_key)

        if not response.body or not response.body.strip():
            raise ResponseValidationError(
                f"{response.source_key}: API returned an empty body."
            )

        body = response.body.lstrip()

        # Detect HTML error pages and proxy/server error responses.
        if body[:100].lower().startswith(
            ("<!doctype html", "<html", "<head")
        ):
            raise ResponseValidationError(
                f"{response.source_key}: API returned HTML instead "
                "of CSV. Check the API key and endpoint."
            )

        # Detect common JSON error responses.
        if body.startswith("{") or body.startswith("["):
            raise ResponseValidationError(
                f"{response.source_key}: API returned JSON instead "
                "of the expected CSV response."
            )

        try:
            dataframe = pd.read_csv(
                StringIO(response.body),
                on_bad_lines="error",
            )

        except (
            pd.errors.ParserError,
            pd.errors.EmptyDataError,
            UnicodeDecodeError,
        ) as exc:
            raise ResponseValidationError(
                f"{response.source_key}: Could not parse CSV: {exc}"
            ) from exc

        if dataframe.columns.empty:
            raise ResponseValidationError(
                f"{response.source_key}: CSV has no column headers."
            )

        # Validate the schema even when the response has zero rows.
        expected_columns = set(source.required_columns)
        actual_columns = set(dataframe.columns)

        missing_columns = expected_columns - actual_columns

        if missing_columns:
            raise ResponseValidationError(
                f"{response.source_key}: Missing required columns: "
                f"{sorted(missing_columns)}. "
                f"Received columns: {sorted(actual_columns)}"
            )

        if dataframe.empty:
            logger.info(
                "%s | %s | Valid CSV but no detections.",
                response.source_key,
                partition_id,
            )

            return ResponseHandlingResult(
                status="EMPTY",
                source_key=response.source_key,
                partition_id=partition_id,
                row_count=0,
            )

        # Preserve the API response without cleaning or modifying values.
        saved_file = self._save_parquet(
            dataframe=dataframe,
            source_key=response.source_key,
            partition_id=partition_id,
            requested_at=response.requested_at,
        )

        logger.info(
            "%s | %s | Saved %d raw detections to %s",
            response.source_key,
            partition_id,
            len(dataframe),
            saved_file.path,
        )

        return ResponseHandlingResult(
            status="SAVED",
            source_key=response.source_key,
            partition_id=partition_id,
            row_count=len(dataframe),
            saved_file=saved_file,
        )

    def _save_parquet(
        self,
        dataframe: pd.DataFrame,
        source_key: str,
        partition_id: str,
        requested_at: datetime,
    ) -> SavedRawFile:
        """Write a Parquet file atomically."""

        output_dir = self.config.raw_dir(source_key)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = requested_at.astimezone(
            timezone.utc
        ).strftime("%Y%m%dT%H%M%S_%fZ")

        partition_hash = hashlib.sha256(
            partition_id.encode("utf-8")
        ).hexdigest()[:10]

        filename = (
            f"{source_key}_{timestamp}_{partition_hash}.parquet"
        )

        final_path = output_dir / filename

        temporary_path: Path | None = None

        try:
            # Create the temporary file in the destination directory.
            # This allows os.replace() to remain on the same filesystem.
            with tempfile.NamedTemporaryFile(
                prefix=".firms_",
                suffix=".tmp",
                dir=output_dir,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)

            dataframe.to_parquet(
                temporary_path,
                engine="pyarrow",
                index=False,
            )

            # Atomic replacement: incomplete files are never exposed
            # under the final Parquet filename.
            os.replace(
                temporary_path,
                final_path,
            )

        except Exception:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

            raise

        return SavedRawFile(
            source_key=source_key,
            partition_id=partition_id,
            path=final_path,
            row_count=len(dataframe),
            requested_at=requested_at,
        )
