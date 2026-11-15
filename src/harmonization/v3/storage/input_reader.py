import re
from pathlib import Path
from typing import Any, Iterable
from datetime import datetime, timezone

from collections.abc import Iterator
from ..phases.phase_00_input_audit.schema_validation import validate_schema
from .duckdb_manager import open_database


PLATFORM_ALIASES = {
    "MODIS_TERRA": {"MODIS_TERRA", "MODIS TERRA", "TERRA", "MOD14"},
    "MODIS_AQUA": {"MODIS_AQUA", "MODIS AQUA", "AQUA", "MYD14"},
    "VIIRS_NOAA20": {"VIIRS_NOAA20", "VIIRS NOAA20", "NOAA20", "NOAA-20", "J1"},
    "VIIRS_NOAA21": {"VIIRS_NOAA21", "VIIRS NOAA21", "NOAA21", "NOAA-21", "J2"},
}


def _normalize_platform(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def _resolve_platforms(requested, available):
    if requested is None:
        return None
    if isinstance(requested, str):
        requested = [requested]

    aliases = {
        _normalize_platform(alias): canonical
        for canonical, names in PLATFORM_ALIASES.items()
        for alias in names | {canonical}
    }
    available_map = {_normalize_platform(v): v for v in available}
    resolved = set()

    for platform in requested:
        token = _normalize_platform(platform)
        canonical = aliases.get(token)
        actual = available_map.get(_normalize_platform(
            canonical)) if canonical else available_map.get(token)

        if actual is None:
            raise ValueError(
                f"Unknown or unavailable platform: {platform}. "
                f"Available: {sorted(available)}"
            )
        resolved.add(actual)

    return sorted(resolved)


def _normalize_utc_bound(value, name):
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _normalize_acquisition_range(start, end_exclusive):
    normalized_start = _normalize_utc_bound(start, "acquisition_start_utc")
    normalized_end = _normalize_utc_bound(
        end_exclusive,
        "acquisition_end_utc_exclusive",
    )
    if (
        normalized_start is not None
        and normalized_end is not None
        and normalized_start >= normalized_end
    ):
        raise ValueError(
            "acquisition_start_utc must be earlier than "
            "acquisition_end_utc_exclusive"
        )
    return normalized_start, normalized_end


def _build_filter_clause(
    *,
    selected_platforms,
    columns,
    acquisition_start_utc,
    acquisition_end_utc_exclusive,
):
    conditions = []
    parameters = []

    if selected_platforms is not None:
        if not selected_platforms:
            return "", []
        placeholders = ", ".join("?" for _ in selected_platforms)
        conditions.append(f"platform IN ({placeholders})")
        parameters.extend(selected_platforms)

    has_time_filter = (
        acquisition_start_utc is not None
        or acquisition_end_utc_exclusive is not None
    )
    if has_time_filter and "acquisition_time_utc" not in columns:
        raise ValueError(
            "Acquisition-time filtering requires the database schema "
            "with acquisition_time_utc"
        )

    if acquisition_start_utc is not None:
        conditions.append("acquisition_time_utc >= ?")
        parameters.append(acquisition_start_utc)
    if acquisition_end_utc_exclusive is not None:
        conditions.append("acquisition_time_utc < ?")
        parameters.append(acquisition_end_utc_exclusive)

    if not conditions:
        return "", parameters
    return " WHERE " + " AND ".join(conditions), parameters


def load_unified_detections(
    database: str | Path,
    table: str = "UNIFIED_DETECTIONS",
    platforms: str | Iterable[str] | None = None,
    *,
    acquisition_start_utc: datetime | None = None,
    acquisition_end_utc_exclusive: datetime | None = None,
) -> list[dict[str, Any]]:

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError(f"Invalid table identifier: {table}")

    database = str(database)
    start_utc, end_utc = _normalize_acquisition_range(
        acquisition_start_utc,
        acquisition_end_utc_exclusive,
    )

    with open_database(database, read_only=(database != ":memory:")) as con:
        description = con.execute(f'DESCRIBE "{table}"').fetchall()
        columns = [row[0] for row in description]
        column_types = {row[0]: row[1] for row in description}

        validation = validate_schema(columns, column_types)

        if not validation.valid:
            raise ValueError(validation.summary())

        available = [
            row[0]
            for row in con.execute(
                f'SELECT DISTINCT platform FROM "{table}" '
                'WHERE platform IS NOT NULL'
            ).fetchall()
        ]

        selected = _resolve_platforms(platforms, available)
        if selected == []:
            return []

        where_clause, parameters = _build_filter_clause(
            selected_platforms=selected,
            columns=columns,
            acquisition_start_utc=start_utc,
            acquisition_end_utc_exclusive=end_utc,
        )
        query = f'SELECT * FROM "{table}"{where_clause}'

        result = con.execute(query, parameters)
        names = [item[0] for item in result.description]

        return [
            dict(zip(names, row))
            for row in result.fetchall()
        ]

def iter_unified_detections(
    database: str | Path,
    table: str = "UNIFIED_DETECTIONS",
    platforms: str | Iterable[str] | None = None,
    batch_size: int = 50_000,
    *,
    acquisition_start_utc: datetime | None = None,
    acquisition_end_utc_exclusive: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Stream real UNIFIED_DETECTIONS records in bounded batches.

    Defaults to the four supported platforms.
    Keeps the DuckDB database read-only.
    """

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError(f"Invalid table identifier: {table}")

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    database = str(database)
    start_utc, end_utc = _normalize_acquisition_range(
        acquisition_start_utc,
        acquisition_end_utc_exclusive,
    )

    with open_database(database, read_only=(database != ":memory:")) as con:
        description = con.execute(
            f'DESCRIBE "{table}"'
        ).fetchall()

        columns = [row[0] for row in description]
        column_types = {
            row[0]: row[1] for row in description
        }

        validation = validate_schema(columns, column_types)

        if not validation.valid:
            raise ValueError(validation.summary())

        available = [
            row[0]
            for row in con.execute(
                f'SELECT DISTINCT platform FROM "{table}" '
                'WHERE platform IS NOT NULL'
            ).fetchall()
        ]

        if platforms is None:
            supported_tokens = {
                _normalize_platform(alias)
                for canonical, aliases in PLATFORM_ALIASES.items()
                for alias in aliases | {canonical}
            }
            selected = sorted(
                value
                for value in available
                if _normalize_platform(value) in supported_tokens
            )
        else:
            selected = _resolve_platforms(platforms, available)

        if selected == []:
            return

        where_clause, parameters = _build_filter_clause(
            selected_platforms=selected,
            columns=columns,
            acquisition_start_utc=start_utc,
            acquisition_end_utc_exclusive=end_utc,
        )
        query = f'SELECT * FROM "{table}"{where_clause}'

        result = con.execute(query, parameters)
        names = [item[0] for item in result.description]

        while True:
            batch = result.fetchmany(batch_size)

            if not batch:
                break

            for row in batch:
                yield dict(zip(names, row))

