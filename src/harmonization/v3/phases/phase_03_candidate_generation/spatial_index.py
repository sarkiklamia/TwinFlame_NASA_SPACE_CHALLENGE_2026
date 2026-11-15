import math

from pyproj import Geod


_WGS84_GEOD = Geod(ellps="WGS84")


def center_distance_km(geometry_a, geometry_b) -> float:
    """
    Calculate WGS84 geodesic distance between detection centres.

    Phase 2 envelopes are not treated as actual pixel footprints here.
    """
    observation_a = geometry_a.qc_result.observation
    observation_b = geometry_b.qc_result.observation

    longitude_a = float(observation_a.longitude)
    latitude_a = float(observation_a.latitude)
    longitude_b = float(observation_b.longitude)
    latitude_b = float(observation_b.latitude)

    values = (
        longitude_a,
        latitude_a,
        longitude_b,
        latitude_b,
    )

    if not all(math.isfinite(value) for value in values):
        raise ValueError(
            "Cannot calculate geodesic distance from non-finite coordinates"
        )

    _, _, distance_m = _WGS84_GEOD.inv(
        longitude_a,
        latitude_a,
        longitude_b,
        latitude_b,
    )

    distance_km = distance_m / 1000.0

    if not math.isfinite(distance_km):
        raise ValueError(
            "Geodesic distance calculation returned a non-finite value"
        )

    return distance_km


def passes_spatial_threshold(
    geometry_a,
    geometry_b,
    maximum_distance_km: float,
) -> tuple[bool, float]:
    distance_km = center_distance_km(geometry_a, geometry_b)

    return (
        distance_km <= maximum_distance_km,
        distance_km,
    )
