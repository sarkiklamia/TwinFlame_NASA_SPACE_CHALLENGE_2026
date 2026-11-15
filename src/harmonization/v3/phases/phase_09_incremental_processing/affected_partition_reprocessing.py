"""Determine which complete UTC-day partitions a new API batch affects."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from typing import Any, Iterable

from ...storage.duckdb_manager import open_database
from ..phase_08_historical_processing.partition_processing import (
    build_archive_partitions,
)


def affected_activity_dates(new_records: Iterable[dict[str, Any]]) -> tuple[date, ...]:
    """Include each arrival date and its predecessor for midnight matches.

    Candidate edges are owned by the earlier endpoint's UTC date. A newly
    received record on date D can therefore replace edges owned by D-1 when
    its acquisition time is within the 240-minute match window of midnight.
    Reprocessing D-1 is safe even when the new record is not near midnight.
    """
    dates = set()
    for record in new_records:
        value = record.get("acquisition_time_utc")
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                value = value.replace(tzinfo=timezone.utc)
            record_date = value.astimezone(timezone.utc).date()
        elif isinstance(value, date):
            record_date = value
        elif isinstance(value, str) and value.strip():
            parsed = datetime.fromisoformat(
                value.strip().replace("Z", "+00:00")
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            record_date = parsed.astimezone(timezone.utc).date()
        else:
            continue
        dates.add(record_date)
        dates.add(record_date - timedelta(days=1))
    return tuple(sorted(dates))


def fetch_affected_date_counts(
    database: str,
    dates: Iterable[date],
    *,
    table: str = "UNIFIED_DETECTIONS",
) -> list[dict[str, Any]]:
    """Count supported source rows only for affected dates, read-only."""
    ordered_dates = tuple(sorted(set(dates)))
    if not ordered_dates:
        return []
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError(f"Invalid table identifier: {table!r}")
    placeholders = ", ".join("?" for _ in ordered_dates)
    with open_database(database, read_only=True) as connection:
        rows = connection.execute(
            f"SELECT CAST(acquisition_time_utc AS DATE) AS date_utc, "
            f"platform, COUNT(*) AS record_count FROM \"{table}\" "
            "WHERE acquisition_time_utc IS NOT NULL "
            f"AND CAST(acquisition_time_utc AS DATE) IN ({placeholders}) "
            "GROUP BY 1, 2 ORDER BY 1, 2",
            list(ordered_dates),
        ).fetchall()
    return [
        {
            "date_utc": row[0].isoformat(),
            "platform": row[1],
            "record_count": int(row[2]),
        }
        for row in rows
    ]


def build_affected_partitions(
    database: str,
    new_records: Iterable[dict[str, Any]],
    *,
    table: str = "UNIFIED_DETECTIONS",
):
    """Return only existing source-date partitions affected by new records."""
    dates = affected_activity_dates(new_records)
    if not dates:
        return ()
    counts = fetch_affected_date_counts(database, dates, table=table)
    return build_archive_partitions(
        counts,
        start_date=dates[0],
        end_date=dates[-1],
    )
