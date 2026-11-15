from collections import defaultdict
from datetime import timezone
import hashlib
import math

from pyproj import Geod

from harmonization.v3.config.thresholds import (
    DEFAULT_ACTIVITY_DISTANCE_THRESHOLDS_KM,
)
from harmonization.v3.contracts.activity import (
    ActivityExperimentSummary,
    ActivityThresholdExperiment,
    DailyActivityCluster,
    DailyActivityMembership,
    Phase04BResult,
)


_GEOD = Geod(ellps="WGS84")
_EARTH_RADIUS_KM = 6371.0088


def _platform_name(value):
    return str(getattr(value, "value", value))


def _utc_datetime(value):
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Eligible observations must have timezone-aware acquisition times")
    return value.astimezone(timezone.utc)


def _threshold_id(distance_km):
    value = f"{distance_km:g}".replace(".", "p")
    return f"ACT_D{value}km"


def _make_experiments(distance_thresholds_km):
    thresholds = tuple(float(value) for value in distance_thresholds_km)

    if not thresholds:
        raise ValueError("At least one activity distance threshold is required")

    if len(set(thresholds)) != len(thresholds):
        raise ValueError("Activity distance thresholds must be unique")

    experiments = []
    for threshold in thresholds:
        experiment = ActivityThresholdExperiment(
            experiment_id=_threshold_id(threshold),
            distance_threshold_km=threshold,
        )
        experiments.append(experiment)

    return tuple(experiments)


def _extract_observations(phase02_result):
    if hasattr(phase02_result, "results"):
        return tuple(phase02_result.results)
    return tuple(phase02_result)


def _prepare_detections(phase02_result):
    detections = []
    seen = set()

    for geometry_result in _extract_observations(phase02_result):
        qc_result = geometry_result.qc_result

        if not qc_result.eligible_for_spatial_matching:
            continue

        observation = qc_result.observation
        detection_id = getattr(observation, "detection_id", None)
        platform_value = getattr(observation, "platform", None)
        timestamp = getattr(observation, "acquisition_time_utc", None)
        point = geometry_result.center_point

        if detection_id is None or str(detection_id).strip() == "":
            raise ValueError("Spatially eligible observation has no detection_id")
        if platform_value is None:
            raise ValueError(f"Eligible detection {detection_id} has no platform")
        if point is None:
            raise ValueError(f"Eligible detection {detection_id} has no centre point")

        platform = _platform_name(platform_value)
        detection_id = str(detection_id)
        timestamp = _utc_datetime(timestamp)

        longitude = float(point.x)
        latitude = float(point.y)

        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise ValueError(f"Detection {detection_id} has non-finite centre coordinates")
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError(f"Detection {detection_id} has out-of-range centre coordinates")

        identity = (platform, detection_id)
        if identity in seen:
            raise ValueError(f"Duplicate eligible detection identity: {identity}")
        seen.add(identity)

        detections.append({
            "key": identity,
            "platform": platform,
            "detection_id": detection_id,
            "timestamp": timestamp,
            "date": timestamp.date(),
            "longitude": longitude,
            "latitude": latitude,
        })

    return tuple(detections)


def _unit_sphere_xyz(longitude, latitude):
    lon = math.radians(longitude)
    lat = math.radians(latitude)
    cos_lat = math.cos(lat)

    return (
        _EARTH_RADIUS_KM * cos_lat * math.cos(lon),
        _EARTH_RADIUS_KM * cos_lat * math.sin(lon),
        _EARTH_RADIUS_KM * math.sin(lat),
    )


def _geodesic_distance_km(a, b):
    _, _, distance_m = _GEOD.inv(
        a["longitude"],
        a["latitude"],
        b["longitude"],
        b["latitude"],
    )
    return distance_m / 1000.0


def _connected_components(detections, threshold_km):
    """
    Build daily connected components.

    The 3D grid is used only to find possible neighbours. Every accepted
    connection is checked using the exact WGS84 geodesic distance.

    Connected components permit transitive chaining: cluster diameter may
    exceed threshold_km even though every graph edge is within the threshold.
    """
    count = len(detections)
    if count == 0:
        return []

    chord_limit = 2.0 * _EARTH_RADIUS_KM * math.sin(
        threshold_km / (2.0 * _EARTH_RADIUS_KM)
    )
    cell_size = chord_limit

    xyz = [
        _unit_sphere_xyz(item["longitude"], item["latitude"])
        for item in detections
    ]

    buckets = defaultdict(list)
    for index, (x, y, z) in enumerate(xyz):
        cell = (
            math.floor(x / cell_size),
            math.floor(y / cell_size),
            math.floor(z / cell_size),
        )
        buckets[cell].append(index)

    parent = list(range(count))
    rank = [0] * count
    maximum_edge_by_root = [0.0] * count

    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left, right, edge_distance):
        root_left = find(left)
        root_right = find(right)

        if root_left == root_right:
            maximum_edge_by_root[root_left] = max(
                maximum_edge_by_root[root_left], edge_distance
            )
            return

        if rank[root_left] < rank[root_right]:
            root_left, root_right = root_right, root_left

        parent[root_right] = root_left
        maximum_edge_by_root[root_left] = max(
            maximum_edge_by_root[root_left],
            maximum_edge_by_root[root_right],
            edge_distance,
        )

        if rank[root_left] == rank[root_right]:
            rank[root_left] += 1

    neighbour_offsets = (
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
    )

    offsets = tuple(neighbour_offsets)

    for index, (x, y, z) in enumerate(xyz):
        cell = (
            math.floor(x / cell_size),
            math.floor(y / cell_size),
            math.floor(z / cell_size),
        )

        for dx, dy, dz in offsets:
            neighbour_cell = (
                cell[0] + dx,
                cell[1] + dy,
                cell[2] + dz,
            )

            for other_index in buckets.get(neighbour_cell, ()):
                if other_index <= index:
                    continue

                distance = _geodesic_distance_km(
                    detections[index],
                    detections[other_index],
                )

                if distance <= threshold_km + 1e-9:
                    union(index, other_index, distance)

    components = defaultdict(list)
    for index in range(count):
        components[find(index)].append(index)

    result = []
    for root, indices in components.items():
        result.append((
            [detections[index] for index in indices],
            maximum_edge_by_root[find(root)],
        ))

    return result


def _stable_cluster_id(experiment_id, activity_date, member_keys):
    identity_text = "|".join(
        f"{platform}:{detection_id}"
        for platform, detection_id in sorted(member_keys)
    )
    digest = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()[:16]
    return f"{experiment_id}|{activity_date.isoformat()}|{digest}"


def run_phase_04b(
    phase02_result,
    distance_thresholds_km=DEFAULT_ACTIVITY_DISTANCE_THRESHOLDS_KM,
    retain_intermediate_results=True,
):
    """
    Cluster all spatially eligible detections into daily spatial activity groups.

    Grouping is independent for each UTC date and each distance threshold.
    No temporal proximity condition is applied within a UTC date.
    """
    if not isinstance(retain_intermediate_results, bool):
        raise ValueError("retain_intermediate_results must be a boolean")

    detections = _prepare_detections(phase02_result)
    experiments = _make_experiments(distance_thresholds_km)

    detections_by_date = defaultdict(list)
    for detection in detections:
        detections_by_date[detection["date"]].append(detection)

    all_clusters = []
    all_memberships = []
    summaries = []

    for experiment in experiments:
        experiment_clusters = []
        experiment_memberships = [] if retain_intermediate_results else None

        for activity_date in sorted(detections_by_date):
            daily_detections = sorted(
                detections_by_date[activity_date],
                key=lambda item: item["key"],
            )

            components = _connected_components(
                daily_detections,
                experiment.distance_threshold_km,
            )

            for members, maximum_edge_distance in components:
                members = sorted(members, key=lambda item: item["key"])
                member_keys = tuple(item["key"] for item in members)

                cluster_id = _stable_cluster_id(
                    experiment.experiment_id,
                    activity_date,
                    member_keys,
                )

                platform_counts = defaultdict(int)
                for item in members:
                    platform_counts[item["platform"]] += 1

                timestamps = [item["timestamp"] for item in members]

                cluster = DailyActivityCluster(
                    cluster_id=cluster_id,
                    experiment_id=experiment.experiment_id,
                    activity_date_utc=activity_date,
                    distance_threshold_km=experiment.distance_threshold_km,
                    member_count=len(members),
                    member_keys=member_keys,
                    platform_counts=tuple(sorted(platform_counts.items())),
                    min_acquisition_time_utc=min(timestamps),
                    max_acquisition_time_utc=max(timestamps),
                    maximum_edge_distance_km=maximum_edge_distance,
                )

                experiment_clusters.append(cluster)

                if retain_intermediate_results:
                    for item in members:
                        experiment_memberships.append(
                            DailyActivityMembership(
                                experiment_id=experiment.experiment_id,
                                cluster_id=cluster_id,
                                platform=item["platform"],
                                detection_id=item["detection_id"],
                                acquisition_time_utc=item["timestamp"],
                            )
                        )

        experiment_clusters.sort(
            key=lambda item: (
                item.activity_date_utc,
                item.cluster_id,
            )
        )
        if retain_intermediate_results:
            experiment_memberships.sort(
                key=lambda item: (
                    item.acquisition_time_utc,
                    item.platform,
                    item.detection_id,
                )
            )

        sizes = [cluster.member_count for cluster in experiment_clusters]
        detection_count = (
            len(experiment_memberships)
            if retain_intermediate_results
            else sum(sizes)
        )

        summaries.append(
            ActivityExperimentSummary(
                experiment_id=experiment.experiment_id,
                distance_threshold_km=experiment.distance_threshold_km,
                detection_count=detection_count,
                cluster_count=len(experiment_clusters),
                singleton_count=sum(size == 1 for size in sizes),
                largest_cluster_size=max(sizes, default=0),
            )
        )

        all_clusters.extend(experiment_clusters)
        if retain_intermediate_results:
            all_memberships.extend(experiment_memberships)

    return Phase04BResult(
        experiments=experiments,
        clusters=tuple(all_clusters),
        memberships=(
            tuple(all_memberships)
            if retain_intermediate_results
            else ()
        ),
        summaries=tuple(summaries),
        memberships_retained=retain_intermediate_results,
    )
