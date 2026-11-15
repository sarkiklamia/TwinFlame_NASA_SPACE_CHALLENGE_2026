"""Partition helpers for read-only historical harmonization."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping

from ...phases.phase_00_input_audit.column_mapping import (
    PLATFORM_ALIASES as INPUT_PLATFORM_ALIASES,
)


HALO_MINUTES = 240
SUPPORTED_PLATFORMS = (
    "MODIS_TERRA",
    "MODIS_AQUA",
    "VIIRS_NOAA20",
    "VIIRS_NOAA21",
)


@dataclass(frozen=True)
class ArchivePartition:
    """One UTC day of owned output plus a temporal matching halo."""

    activity_date_utc: date
    core_start_utc: datetime
    core_end_utc_exclusive: datetime
    read_start_utc: datetime
    read_end_utc_exclusive: datetime
    input_record_count: int
    platform_record_counts: Mapping[str, int]


def _normalized_platform(value: Any) -> str:
    return "".join(
        character
        for character in str(value or "").upper()
        if character.isalnum()
    )


_PLATFORM_LOOKUP = {
    _normalized_platform(alias): canonical
    for alias, canonical in INPUT_PLATFORM_ALIASES.items()
}


def canonical_platform(value: Any) -> str | None:
    """Return the Phase 00 canonical platform, if it is supported."""
    return _PLATFORM_LOOKUP.get(_normalized_platform(value))


def build_archive_partitions(
    date_platform_counts: Iterable[Mapping[str, Any]],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    halo_minutes: int = HALO_MINUTES,
) -> tuple[ArchivePartition, ...]:
    """Build partitions only for UTC dates with supported source records."""
    if isinstance(halo_minutes, bool) or not isinstance(halo_minutes, int):
        raise ValueError("halo_minutes must be an integer")
    if halo_minutes < 0:
        raise ValueError("halo_minutes cannot be negative")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    counts: dict[date, Counter[str]] = {}
    for record in date_platform_counts:
        raw_date = record.get("date_utc")
        if isinstance(raw_date, datetime):
            raw_date = raw_date.date()
        if isinstance(raw_date, str):
            raw_date = date.fromisoformat(raw_date)
        if not isinstance(raw_date, date):
            continue
        if start_date is not None and raw_date < start_date:
            continue
        if end_date is not None and raw_date > end_date:
            continue

        platform = canonical_platform(record.get("platform"))
        row_count = int(record.get("record_count", 0))
        if platform is None or row_count <= 0:
            continue
        counts.setdefault(raw_date, Counter())[platform] += row_count

    partitions = []
    halo = timedelta(minutes=halo_minutes)
    for activity_date in sorted(counts):
        core_start = datetime.combine(
            activity_date,
            time.min,
            tzinfo=timezone.utc,
        )
        core_end = core_start + timedelta(days=1)
        platform_counts = {
            platform: counts[activity_date].get(platform, 0)
            for platform in SUPPORTED_PLATFORMS
            if counts[activity_date].get(platform, 0) > 0
        }
        partitions.append(ArchivePartition(
            activity_date_utc=activity_date,
            core_start_utc=core_start,
            core_end_utc_exclusive=core_end,
            read_start_utc=core_start - halo,
            read_end_utc_exclusive=core_end + halo,
            input_record_count=sum(platform_counts.values()),
            platform_record_counts=platform_counts,
        ))

    return tuple(partitions)


def find_coverage_gaps(
    dates: Iterable[date],
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return missing-date ranges, optionally including coverage boundaries."""
    ordered = sorted(set(dates))
    gaps = []
    if ordered and start_date is not None and ordered[0] > start_date:
        gaps.append({
            "start_date": start_date.isoformat(),
            "end_date": (ordered[0] - timedelta(days=1)).isoformat(),
            "missing_days": (ordered[0] - start_date).days,
        })
    for left, right in zip(ordered, ordered[1:]):
        missing_start = left + timedelta(days=1)
        missing_end = right - timedelta(days=1)
        if missing_start <= missing_end:
            gaps.append({
                "start_date": missing_start.isoformat(),
                "end_date": missing_end.isoformat(),
                "missing_days": (missing_end - missing_start).days + 1,
            })
    if ordered and end_date is not None and ordered[-1] < end_date:
        gaps.append({
            "start_date": (ordered[-1] + timedelta(days=1)).isoformat(),
            "end_date": end_date.isoformat(),
            "missing_days": (end_date - ordered[-1]).days,
        })
    return tuple(gaps)


def count_duplicate_observation_identities(
    observations: Iterable[Any],
) -> int:
    """Count extra rows sharing a canonical (platform, detection_id)."""
    identities = Counter(
        (item.platform, str(item.detection_id))
        for item in observations
        if item.platform is not None and item.detection_id is not None
    )
    return sum(count - 1 for count in identities.values() if count > 1)


def filter_phase07_to_partition(
    phase07_result: Any,
    *,
    activity_date_utc: date,
    observations: Iterable[Any],
    metadata: dict[str, Any],
) -> tuple[Any, dict[str, int]]:
    """Keep only output owned by one date and replace run metadata."""
    from ...phases.phase_07_output_generation.orchestrator import (
        Phase07OutputResult,
    )
    from ...phases.phase_07_output_generation.run_metadata import (
        build_run_metadata,
    )
    from ...phases.phase_07_output_generation.schemas import OUTPUT_SCHEMAS
    from ...phases.phase_07_output_generation.output_validation import (
        validate_output_rows,
    )

    observation_dates: dict[tuple[str, str], date] = {}
    core_input_count = 0
    for observation in observations:
        timestamp = observation.acquisition_time_utc
        if timestamp is None:
            continue
        observation_date = timestamp.astimezone(timezone.utc).date()
        identity = (observation.platform, str(observation.detection_id))
        observation_dates[identity] = observation_date
        if observation_date == activity_date_utc:
            core_input_count += 1

    owned_edges = []
    for row in phase07_result.tables["harm_correspondence_edges"]:
        date_a = observation_dates.get((
            row["platform_a"], row["detection_id_a"],
        ))
        date_b = observation_dates.get((
            row["platform_b"], row["detection_id_b"],
        ))
        if date_a is not None and date_b is not None:
            if min(date_a, date_b) == activity_date_utc:
                owned_edges.append(dict(row))

    owned_clusters = [
        dict(row)
        for row in phase07_result.tables["harm_activity_clusters"]
        if row["activity_date_utc"] == activity_date_utc
    ]
    owned_cluster_ids = {
        row["activity_cluster_id"] for row in owned_clusters
    }

    tables = {
        "harm_correspondence_edges": tuple(owned_edges),
        "harm_activity_clusters": tuple(owned_clusters),
        "harm_cluster_members": tuple(
            dict(row)
            for row in phase07_result.tables["harm_cluster_members"]
            if row["activity_cluster_id"] in owned_cluster_ids
        ),
        "harm_sensor_activity_daily": tuple(
            dict(row)
            for row in phase07_result.tables["harm_sensor_activity_daily"]
            if row["date_utc"] == activity_date_utc
        ),
        "harm_correspondence_summary": tuple(
            dict(row)
            for row in phase07_result.tables["harm_correspondence_summary"]
            if row["date_utc"] == activity_date_utc
        ),
        "harm_frp_comparisons": tuple(
            dict(row)
            for row in phase07_result.tables["harm_frp_comparisons"]
            if row["date_utc"] == activity_date_utc
        ),
    }

    edges = tables["harm_correspondence_edges"]
    clusters = tables["harm_activity_clusters"]
    tables["harm_run_metadata"] = (build_run_metadata(
        run_id=metadata["run_id"],
        algorithm_version=metadata["algorithm_version"],
        config_id=metadata["config_id"],
        started_at_utc=metadata["started_at_utc"],
        finished_at_utc=datetime.now(timezone.utc),
        status="success",
        input_count=core_input_count,
        candidate_count=len(edges),
        correspondence_edge_count=len(edges),
        activity_cluster_count=len(clusters),
    ),)

    for table_name in OUTPUT_SCHEMAS:
        validate_output_rows(table_name, tables[table_name])

    return Phase07OutputResult(tables=tables), {
        table_name: len(rows)
        for table_name, rows in tables.items()
    }
