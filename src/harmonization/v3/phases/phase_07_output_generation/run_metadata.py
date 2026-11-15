from datetime import datetime, timezone
import math
from typing import Any

from .output_validation import validate_output_rows


_ALLOWED_STATUSES = {"running", "success", "partial", "failed"}

_COUNT_FIELDS = (
    "input_count",
    "candidate_count",
    "correspondence_edge_count",
    "activity_cluster_count",
)


def _validate_identifier(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _validate_utc_timestamp(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")

    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{name} must be expressed in UTC")

    return value.astimezone(timezone.utc)


def _validate_count(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")

    if value < 0:
        raise ValueError(f"{name} cannot be negative")

    return value


def build_run_metadata(
    *,
    run_id: str,
    algorithm_version: str,
    config_id: str,
    started_at_utc: datetime,
    status: str,
    input_count: int,
    candidate_count: int,
    correspondence_edge_count: int,
    activity_cluster_count: int,
    finished_at_utc: datetime | None = None,
    failed_stage: str | None = None,
    error_summary: str | None = None,
) -> dict[str, Any]:
    """
    Build one validated harm_run_metadata row.

    Timestamps must be timezone-aware UTC datetimes.
    Duration is calculated from the supplied timestamps.
    Counts must be supplied by the caller; they are never inferred.
    """
    run_id = _validate_identifier("run_id", run_id)
    algorithm_version = _validate_identifier(
        "algorithm_version", algorithm_version
    )
    config_id = _validate_identifier("config_id", config_id)

    if status not in _ALLOWED_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(_ALLOWED_STATUSES)}"
        )

    started_at_utc = _validate_utc_timestamp(
        "started_at_utc", started_at_utc
    )

    if status == "running":
        if finished_at_utc is not None:
            raise ValueError(
                "A running run cannot have finished_at_utc"
            )
    else:
        if finished_at_utc is None:
            raise ValueError(
                f"finished_at_utc is required when status is '{status}'"
            )

        finished_at_utc = _validate_utc_timestamp(
            "finished_at_utc", finished_at_utc
        )

        if finished_at_utc < started_at_utc:
            raise ValueError(
                "finished_at_utc cannot precede started_at_utc"
            )

    if status == "failed":
        failed_stage = _validate_identifier(
            "failed_stage", failed_stage
        )
    elif failed_stage is not None:
        failed_stage = _validate_identifier(
            "failed_stage", failed_stage
        )

    if error_summary is not None:
        if not isinstance(error_summary, str):
            raise ValueError("error_summary must be a string or None")
        error_summary = error_summary.strip() or None

    counts = {
        name: _validate_count(name, value)
        for name, value in {
            "input_count": input_count,
            "candidate_count": candidate_count,
            "correspondence_edge_count": correspondence_edge_count,
            "activity_cluster_count": activity_cluster_count,
        }.items()
    }

    duration_seconds = None
    if finished_at_utc is not None:
        duration_seconds = (
            finished_at_utc - started_at_utc
        ).total_seconds()

        if not math.isfinite(duration_seconds):
            raise ValueError("Calculated duration is not finite")

    row = {
        "run_id": run_id,
        "algorithm_version": algorithm_version,
        "config_id": config_id,
        "started_at_utc": started_at_utc,
        "finished_at_utc": finished_at_utc,
        "duration_seconds": duration_seconds,
        "status": status,
        **counts,
        "failed_stage": failed_stage,
        "error_summary": error_summary,
    }

    validate_output_rows("harm_run_metadata", [row])
    return row
