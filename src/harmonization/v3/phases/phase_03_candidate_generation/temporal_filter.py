from bisect import bisect_left, bisect_right
from datetime import timezone
import math


_EARTH_RADIUS_KM = 6371.0088
_SPATIAL_PREFILTER_MARGIN = 1.01


def _utc_timestamp(observation) -> float:
    timestamp = observation.acquisition_time_utc

    if timestamp is None or timestamp.tzinfo is None:
        raise ValueError(
            f"Observation {observation.detection_id!r} "
            "has no timezone-aware timestamp"
        )

    return timestamp.astimezone(timezone.utc).timestamp()


def iter_temporal_pairs(
    records_by_platform: dict,
    platform_pairs: tuple[tuple[str, str], ...],
    maximum_time_difference_minutes: float,
):
    """
    Yield pairs inside the broadest configured temporal window.

    This is a preliminary filter only. The exact spatial condition
    must also pass before a pair becomes a candidate.
    """
    maximum_seconds = maximum_time_difference_minutes * 60.0

    for platform_a, platform_b in platform_pairs:
        records_a = records_by_platform.get(platform_a, ())
        records_b = records_by_platform.get(platform_b, ())

        if not records_a or not records_b:
            continue

        timestamps_b = [item[0] for item in records_b]

        for timestamp_a, geometry_a in records_a:
            lower = bisect_left(
                timestamps_b,
                timestamp_a - maximum_seconds,
            )
            upper = bisect_right(
                timestamps_b,
                timestamp_a + maximum_seconds,
            )

            for index in range(lower, upper):
                timestamp_b, geometry_b = records_b[index]

                yield (
                    geometry_a,
                    geometry_b,
                    abs(timestamp_a - timestamp_b) / 60.0,
                )


def count_temporal_pairs(
    records_by_platform: dict,
    platform_pairs: tuple[tuple[str, str], ...],
    maximum_time_difference_minutes: float,
) -> int:
    """Count temporal-window pairs without constructing the pair list."""
    maximum_seconds = maximum_time_difference_minutes * 60.0
    total = 0

    for platform_a, platform_b in platform_pairs:
        records_a = records_by_platform.get(platform_a, ())
        records_b = records_by_platform.get(platform_b, ())
        if not records_a or not records_b:
            continue

        timestamps_b = [item[0] for item in records_b]
        for timestamp_a, _ in records_a:
            lower = bisect_left(timestamps_b, timestamp_a - maximum_seconds)
            upper = bisect_right(timestamps_b, timestamp_a + maximum_seconds)
            total += upper - lower

    return total


def _unit_sphere_cell(geometry, cell_size_km: float) -> tuple[int, int, int]:
    observation = geometry.qc_result.observation
    latitude = math.radians(float(observation.latitude))
    longitude = math.radians(float(observation.longitude))
    cos_latitude = math.cos(latitude)
    x = _EARTH_RADIUS_KM * cos_latitude * math.cos(longitude)
    y = _EARTH_RADIUS_KM * cos_latitude * math.sin(longitude)
    z = _EARTH_RADIUS_KM * math.sin(latitude)
    return (
        math.floor(x / cell_size_km),
        math.floor(y / cell_size_km),
        math.floor(z / cell_size_km),
    )


def iter_spatiotemporal_pairs(
    records_by_platform: dict,
    platform_pairs: tuple[tuple[str, str], ...],
    maximum_time_difference_minutes: float,
    maximum_distance_km: float,
):
    """Yield a conservative spatial-and-temporal prefilter of pair rows.

    A 3D unit-sphere grid limits distance calculations to nearby buckets.
    The bucket radius includes a small margin for ellipsoid-versus-sphere
    differences; exact WGS84 distance remains the final spatial check.
    """
    if maximum_distance_km <= 0 or not math.isfinite(maximum_distance_km):
        raise ValueError("Maximum distance must be finite and positive")

    search_distance_km = maximum_distance_km * _SPATIAL_PREFILTER_MARGIN
    cell_size_km = 2.0 * _EARTH_RADIUS_KM * math.sin(
        search_distance_km / (2.0 * _EARTH_RADIUS_KM)
    )
    if cell_size_km <= 0 or not math.isfinite(cell_size_km):
        raise ValueError("Could not build spatial prefilter for distance")

    maximum_seconds = maximum_time_difference_minutes * 60.0
    buckets_by_platform = {}

    for platform, records in records_by_platform.items():
        buckets = {}
        for timestamp, geometry in records:
            cell = _unit_sphere_cell(geometry, cell_size_km)
            buckets.setdefault(cell, []).append((timestamp, geometry))
        buckets_by_platform[platform] = {
            cell: (
                [item[0] for item in bucket_records],
                bucket_records,
            )
            for cell, bucket_records in buckets.items()
        }

    offsets = tuple(
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
    )

    for platform_a, platform_b in platform_pairs:
        records_a = records_by_platform.get(platform_a, ())
        buckets_b = buckets_by_platform.get(platform_b, {})
        if not records_a or not buckets_b:
            continue

        for timestamp_a, geometry_a in records_a:
            cell_a = _unit_sphere_cell(geometry_a, cell_size_km)
            lower_time = timestamp_a - maximum_seconds
            upper_time = timestamp_a + maximum_seconds

            for dx, dy, dz in offsets:
                neighbor_cell = (
                    cell_a[0] + dx,
                    cell_a[1] + dy,
                    cell_a[2] + dz,
                )
                indexed_bucket = buckets_b.get(neighbor_cell)
                if indexed_bucket is None:
                    continue

                bucket_timestamps, bucket_records = indexed_bucket
                lower = bisect_left(bucket_timestamps, lower_time)
                upper = bisect_right(bucket_timestamps, upper_time)
                for index in range(lower, upper):
                    timestamp_b, geometry_b = bucket_records[index]
                    yield (
                        geometry_a,
                        geometry_b,
                        abs(timestamp_a - timestamp_b) / 60.0,
                    )
