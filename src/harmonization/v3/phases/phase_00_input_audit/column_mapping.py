
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import re
from typing import Any, Mapping


PLATFORM_ALIASES = {
    "MODIS_TERRA": "MODIS_TERRA",
    "MODIS TERRA": "MODIS_TERRA",
    "TERRA": "MODIS_TERRA",
    "MOD14": "MODIS_TERRA",
    "MODIS_AQUA": "MODIS_AQUA",
    "MODIS AQUA": "MODIS_AQUA",
    "AQUA": "MODIS_AQUA",
    "MYD14": "MODIS_AQUA",
    "VIIRS_NOAA20": "VIIRS_NOAA20",
    "VIIRS NOAA20": "VIIRS_NOAA20",
    "NOAA20": "VIIRS_NOAA20",
    "NOAA-20": "VIIRS_NOAA20",
    "J1": "VIIRS_NOAA20",
    "VIIRS_NOAA21": "VIIRS_NOAA21",
    "VIIRS NOAA21": "VIIRS_NOAA21",
    "NOAA21": "VIIRS_NOAA21",
    "NOAA-21": "VIIRS_NOAA21",
    "J2": "VIIRS_NOAA21",
}


def _normalize_platform(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


_NORMALIZED_PLATFORM_ALIASES = {
    _normalize_platform(alias): canonical
    for alias, canonical in PLATFORM_ALIASES.items()
}


@dataclass(frozen=True)
class CanonicalInputRecord:
    detection_id: str | None
    source_record_id: int | None
    source: str | None
    platform: str | None
    raw_platform: str | None
    latitude: float | None
    longitude: float | None
    acquisition_time_utc: datetime | None
    confidence_native: str | None
    frp_mw: float | None
    brightness_native: float | None
    bright_t31: float | None
    bright_ti4: float | None
    bright_ti5: float | None
    scan_km: float | None
    track_km: float | None
    daynight: str | None
    raw_record: Mapping[str, Any]
    mapping_issues: tuple[str, ...]
    ingested_at_utc: datetime | None = None


def _is_missing(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip() == ""
    )


def _parse_acquisition_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def _parse_acquisition_time(value: Any) -> time:
    raw = str(value).strip()

    if ":" in raw:
        return time.fromisoformat(raw)

    if not raw.isdigit() or len(raw) > 4:
        raise ValueError(f"Unsupported acq_time: {value!r}")

    return datetime.strptime(raw.zfill(4), "%H%M").time()


def _utc_timestamp(acq_date: Any, acq_time: Any) -> datetime:
    return datetime.combine(
        _parse_acquisition_date(acq_date),
        _parse_acquisition_time(acq_time),
        tzinfo=timezone.utc,
    )


def _parse_utc_datetime(value: Any) -> datetime:
    """Parse a timestamp and normalize it to timezone-aware UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    else:
        raise ValueError(f"Unsupported timestamp value: {value!r}")

    if parsed.tzinfo is None:
        # Database TIMESTAMP values are stored as UTC by project convention.
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)

    return parsed


def _map_timestamp(
    row: Mapping[str, Any],
    field: str,
    issues: list[str],
    missing_issue: str,
    invalid_issue: str,
) -> datetime | None:
    value = row.get(field)

    if _is_missing(value):
        issues.append(missing_issue)
        return None

    try:
        return _parse_utc_datetime(value)
    except (TypeError, ValueError, OverflowError):
        issues.append(invalid_issue)
        return None


def _map_optional_float(
    row: Mapping[str, Any],
    field: str,
    issues: list[str],
) -> float | None:
    value = row.get(field)

    if _is_missing(value):
        return None

    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        issues.append(f"invalid_numeric:{field}")
        return None


def _map_optional_int(
    row: Mapping[str, Any],
    field: str,
    issues: list[str],
) -> int | None:
    value = row.get(field)

    if _is_missing(value):
        return None

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        issues.append(f"invalid_integer:{field}")
        return None


def _map_optional_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return str(value).strip()


def map_input_record(row: Mapping[str, Any]) -> CanonicalInputRecord:
    """
    Map one legacy or actual UNIFIED_DETECTIONS row.

    Mapping problems are recorded in mapping_issues.
    All original source values are retained in raw_record.
    Scientific quality and eligibility decisions belong to Phase 1.
    """
    issues: list[str] = []
    raw_record = dict(row)

    is_database_schema = "acquisition_time_utc" in row

    # Detection identifier: BIGINT is safely represented as a string.
    detection_id = _map_optional_text(row.get("detection_id"))
    if detection_id is None:
        issues.append("missing_detection_id")

    # Platform: only the four project platforms are accepted.
    raw_platform = _map_optional_text(row.get("platform"))
    platform = None

    if raw_platform is None:
        issues.append("missing_platform")
    else:
        platform = _NORMALIZED_PLATFORM_ALIASES.get(
            _normalize_platform(raw_platform)
        )
        if platform is None:
            issues.append("unsupported_platform")

    # Acquisition timestamp.
    if is_database_schema:
        acquisition_time_utc = _map_timestamp(
            row,
            "acquisition_time_utc",
            issues,
            "missing_acquisition_time_utc",
            "invalid_acquisition_timestamp",
        )
    else:
        acquisition_time_utc = None

        if _is_missing(row.get("acq_date")):
            issues.append("missing_acq_date")
        elif _is_missing(row.get("acq_time")):
            issues.append("missing_acq_time")
        else:
            try:
                acquisition_time_utc = _utc_timestamp(
                    row.get("acq_date"),
                    row.get("acq_time"),
                )
            except (TypeError, ValueError, OverflowError):
                issues.append("invalid_acquisition_timestamp")

    # Ingestion timestamp: available in the actual database schema.
    ingested_at_utc = None
    if is_database_schema:
        ingested_at_utc = _map_timestamp(
            row,
            "ingested_at",
            issues,
            "missing_ingested_at",
            "invalid_ingested_at",
        )

    # Source-specific field names.
    brightness_field = (
        "brightness_native" if is_database_schema else "brightness"
    )
    scan_field = "scan" if is_database_schema else "scan_km"
    track_field = "track" if is_database_schema else "track_km"

    # The new database schema has no legacy `id` field.
    # file_id identifies a source file, not an individual detection.
    source_record_id = (
        None
        if is_database_schema
        else _map_optional_int(row, "id", issues)
    )

    return CanonicalInputRecord(
        detection_id=detection_id,
        source_record_id=source_record_id,
        source=_map_optional_text(row.get("source")),
        platform=platform,
        raw_platform=raw_platform,
        latitude=_map_optional_float(row, "latitude", issues),
        longitude=_map_optional_float(row, "longitude", issues),
        acquisition_time_utc=acquisition_time_utc,
        confidence_native=_map_optional_text(
            row.get("confidence_native")
        ),
        frp_mw=_map_optional_float(row, "frp_mw", issues),
        brightness_native=_map_optional_float(
            row, brightness_field, issues
        ),
        bright_t31=_map_optional_float(row, "bright_t31", issues),
        bright_ti4=_map_optional_float(row, "bright_ti4", issues),
        bright_ti5=_map_optional_float(row, "bright_ti5", issues),
        scan_km=_map_optional_float(row, scan_field, issues),
        track_km=_map_optional_float(row, track_field, issues),
        daynight=_map_optional_text(row.get("daynight")),
        raw_record=raw_record,
        mapping_issues=tuple(issues),
        ingested_at_utc=ingested_at_utc,
    )
