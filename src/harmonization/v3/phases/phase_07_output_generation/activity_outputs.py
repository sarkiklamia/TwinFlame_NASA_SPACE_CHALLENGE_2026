import math
from datetime import timezone

from pyproj import Geod

from ...contracts.activity import Phase04BResult
from .output_validation import validate_output_rows


_GEOD = Geod(ellps="WGS84")

_PLATFORM_COLUMNS = {
    "MODIS_TERRA": "terra_count",
    "MODIS_AQUA": "aqua_count",
    "VIIRS_NOAA20": "noaa20_count",
    "VIIRS_NOAA21": "noaa21_count",
}


def _validate_run_id(run_id):
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")


def _extract_geometry_results(phase02_result):
    if hasattr(phase02_result, "results"):
        return tuple(phase02_result.results)
    return tuple(phase02_result)


def _build_observation_index(phase02_result):
    index = {}

    for geometry_result in _extract_geometry_results(phase02_result):
        qc_result = geometry_result.qc_result
        observation = qc_result.observation

        platform = str(getattr(observation.platform, "value", observation.platform))
        detection_id = str(observation.detection_id)
        key = (platform, detection_id)

        if key in index:
            raise ValueError(f"Duplicate observation identity: {key}")

        point = geometry_result.center_point
        if point is None:
            continue

        longitude = float(point.x)
        latitude = float(point.y)

        if (
            not math.isfinite(longitude)
            or not math.isfinite(latitude)
            or not -180 <= longitude <= 180
            or not -90 <= latitude <= 90
        ):
            raise ValueError(f"Invalid centre coordinates for {key}")

        index[key] = (longitude, latitude)

    return index


def _spherical_centroid(coordinates):
    """Calculate a geographic centroid using unit-sphere averaging."""
    x = y = z = 0.0

    for longitude, latitude in coordinates:
        lon = math.radians(longitude)
        lat = math.radians(latitude)
        cos_lat = math.cos(lat)

        x += cos_lat * math.cos(lon)
        y += cos_lat * math.sin(lon)
        z += math.sin(lat)

    magnitude = math.sqrt(x * x + y * y + z * z)

    if magnitude < 1e-12:
        raise ValueError("Cluster centroid is undefined for its member coordinates")

    longitude = math.degrees(math.atan2(y, x))
    latitude = math.degrees(math.atan2(z, math.hypot(x, y)))

    return latitude, longitude


def _extent_upper_bound_km(coordinates, centroid_latitude, centroid_longitude):
    """Return a linear-time conservative upper bound on cluster diameter.

    The triangle inequality bounds every pairwise member distance by twice
    the maximum geodesic distance from the spherical centroid. This can
    overstate the exact diameter, so the value is explicitly an upper bound.
    """
    maximum_radius_km = 0.0
    for longitude, latitude in coordinates:
        _, _, distance_m = _GEOD.inv(
            centroid_longitude,
            centroid_latitude,
            longitude,
            latitude,
        )
        maximum_radius_km = max(maximum_radius_km, distance_m / 1000.0)
    return 2.0 * maximum_radius_km


def _experiment_method(experiment_id, distance_threshold_km):
    return (
        f"connected_components"
        f"|experiment_id={experiment_id}"
        f"|distance_threshold_km={distance_threshold_km:g}"
        f"|chaining_possible=true"
        f"|extent_metric=2x_max_centroid_radius_upper_bound"
    )


def build_activity_clusters(
    phase_04b_result: Phase04BResult,
    phase02_result,
    run_id: str,
) -> list[dict]:
    """
    Build daily activity-cluster output rows.

    Coordinates are obtained from Phase 2 geometry results.
    Cluster extent is a conservative upper bound on maximum pairwise
    centre distance, calculated as twice the largest member distance from
    the spherical centroid.
    Cluster area is intentionally NULL because Phase 4B does not
    construct a physical cluster boundary.
    """
    _validate_run_id(run_id)

    observation_index = _build_observation_index(phase02_result)

    rows = []

    for cluster in phase_04b_result.clusters:
        if len(cluster.member_keys) != cluster.member_count:
            raise ValueError(
                f"Member key count mismatch for cluster {cluster.cluster_id}"
            )

        coordinates = []

        for key in cluster.member_keys:
            if key not in observation_index:
                raise ValueError(
                    f"Missing Phase 2 centre coordinates for cluster member {key}"
                )

            coordinates.append(observation_index[key])

        centroid_latitude, centroid_longitude = _spherical_centroid(coordinates)
        cluster_extent_km = _extent_upper_bound_km(
            coordinates,
            centroid_latitude,
            centroid_longitude,
        )

        platform_counts = dict(cluster.platform_counts)

        row = {
            "activity_cluster_id": cluster.cluster_id,
            "activity_date_utc": cluster.activity_date_utc,
            "centroid_latitude": centroid_latitude,
            "centroid_longitude": centroid_longitude,
            "member_count": cluster.member_count,
            "terra_count": platform_counts.get("MODIS_TERRA", 0),
            "aqua_count": platform_counts.get("MODIS_AQUA", 0),
            "noaa20_count": platform_counts.get("VIIRS_NOAA20", 0),
            "noaa21_count": platform_counts.get("VIIRS_NOAA21", 0),
            "sensor_count": sum(count > 0 for count in platform_counts.values()),
            "start_time_utc": cluster.min_acquisition_time_utc.astimezone(timezone.utc),
            "end_time_utc": cluster.max_acquisition_time_utc.astimezone(timezone.utc),
            "cluster_extent_km": cluster_extent_km,
            "cluster_area_km2": None,
            "cluster_method": _experiment_method(
                cluster.experiment_id,
                cluster.distance_threshold_km,
            ),
            "run_id": run_id,
        }

        rows.append(row)

    validate_output_rows("harm_activity_clusters", rows)
    return rows


def build_cluster_members(
    phase_04b_result: Phase04BResult,
    run_id: str,
) -> list[dict]:
    """Build one output row per Phase 4B detection-cluster membership."""
    _validate_run_id(run_id)

    rows = []
    experiments = {
        item.experiment_id: item
        for item in phase_04b_result.experiments
    }

    for cluster in phase_04b_result.clusters:
        if len(cluster.member_keys) != cluster.member_count:
            raise ValueError(
                f"Member key count mismatch for cluster {cluster.cluster_id}"
            )

        experiment = experiments.get(cluster.experiment_id)
        if experiment is None:
            raise ValueError(
                f"Missing activity experiment: {cluster.experiment_id}"
            )

        method = _experiment_method(
            cluster.experiment_id,
            experiment.distance_threshold_km,
        )
        for platform, detection_id in cluster.member_keys:
            rows.append({
                "activity_cluster_id": cluster.cluster_id,
                "detection_id": detection_id,
                "platform": platform,
                "membership_method": method,
                "membership_distance_km": None,
                "membership_quality": None,
                "run_id": run_id,
            })

    if (
        phase_04b_result.memberships_retained
        and len(rows) != len(phase_04b_result.memberships)
    ):
        raise ValueError("Cluster member keys do not reconcile with memberships")

    validate_output_rows("harm_cluster_members", rows)
    return rows
