
"""HTTP client for NASA FIRMS Area CSV API."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from config.api_config import FirmsApiConfig, get_firms_config

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class FIRMSRequestError(RuntimeError):
    """Raised when a FIRMS request cannot be completed."""


@dataclass(frozen=True)
class FIRMSResponse:
    source_key: str
    firms_source: str
    requested_at: datetime
    status_code: int
    url_redacted: str
    body: str = field(repr=False)


class FIRMSClient:
    """Responsible only for HTTP communication with FIRMS."""

    def __init__(
        self,
        config: FirmsApiConfig | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config or get_firms_config()
        self.session = session or requests.Session()
        self._owns_session = session is None

        self.session.headers.update({
            "User-Agent": "PyroSync/1.0",
            "Accept": "text/csv",
        })

    def fetch_area(
        self,
        source_key: str,
        bbox: str = "world",
        day_range: int = 1,
        on_date: date | str | None = None,
    ) -> FIRMSResponse:
        """Request fire detections for one source and geographic area."""

        source = self.config.get_source(source_key)

        if not source.enabled:
            raise FIRMSRequestError(
                f"Source {source_key!r} is disabled."
            )

        url = self.config.area_url(
            key=source_key,
            bbox=bbox,
            day_range=day_range,
            on_date=on_date,
        )

        safe_url = self.config.redact(url)

        for attempt in range(self.config.max_retries + 1):
            requested_at = datetime.now(timezone.utc)

            try:
                response = self.session.get(
                    url,
                    timeout=self.config.timeout,
                )

                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt >= self.config.max_retries:
                        response.raise_for_status()

                    delay = self._retry_delay(response, attempt)

                    logger.warning(
                        "FIRMS temporary HTTP error %s for %s. "
                        "Retrying in %.1f seconds (attempt %s/%s).",
                        response.status_code,
                        safe_url,
                        delay,
                        attempt + 1,
                        self.config.max_retries,
                    )

                    time.sleep(delay)
                    continue

                response.raise_for_status()

                if not response.text.strip():
                    logger.info(
                        "FIRMS returned an empty response for %s.",
                        safe_url,
                    )

                logger.debug(
                    "FIRMS request succeeded: source=%s status=%s",
                    source_key,
                    response.status_code,
                )

                return FIRMSResponse(
                    source_key=source_key,
                    firms_source=source.firms_source,
                    requested_at=requested_at,
                    status_code=response.status_code,
                    url_redacted=safe_url,
                    body=response.text,
                )

            except requests.exceptions.HTTPError as exc:
                raise FIRMSRequestError(
                    f"FIRMS HTTP error for {source_key}: "
                    f"{self.config.redact(str(exc))}"
                ) from None

            except requests.exceptions.RequestException as exc:
                if attempt >= self.config.max_retries:
                    raise FIRMSRequestError(
                        f"FIRMS connection failed for {source_key}: "
                        f"{self.config.redact(str(exc))}"
                    ) from None

                delay = self._retry_delay(None, attempt)

                logger.warning(
                    "FIRMS connection error for %s. "
                    "Retrying in %.1f seconds.",
                    source_key,
                    delay,
                )

                time.sleep(delay)

        raise FIRMSRequestError(
            f"FIRMS request failed for {source_key}."
        )

    def _retry_delay(
        self,
        response: requests.Response | None,
        attempt: int,
    ) -> float:
        """Use Retry-After when available; otherwise exponential backoff."""

        if response is not None:
            retry_after = response.headers.get("Retry-After")

            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    try:
                        retry_date = parsedate_to_datetime(retry_after)
                        if retry_date.tzinfo is None:
                            retry_date = retry_date.replace(
                                tzinfo=timezone.utc
                            )

                        return max(
                            0.0,
                            (
                                retry_date
                                - datetime.now(timezone.utc)
                            ).total_seconds(),
                        )
                    except (TypeError, ValueError, OverflowError):
                        pass

        return self.config.retry_delay * (2 ** attempt)

    def close(self) -> None:
        """Close the HTTP session if this client created it."""

        if self._owns_session:
            self.session.close()

    def __enter__(self) -> "FIRMSClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
