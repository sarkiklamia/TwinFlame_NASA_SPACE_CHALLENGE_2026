from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, isfinite, pi, radians, sin, sqrt

from pyproj import CRS, Geod, Transformer
from shapely import transform as shapely_transform


_WGS84_GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class ScreeningEnvelopeMetrics:
    """Spatial evidence measured on Phase 2 screening envelopes."""

    intersects: bool | None
    intersection_area_km2: float | None
    union_area_km2: float | None
    iou: float | None
    containment_a: float | None
    containment_b: float | None
    minimum_boundary_distance_km: float | None
    center_distance_km: float | None
    normalized_center_distance: float | None
    method: str | None


def _point_coordinates(geometry_result):
    point = geometry_result.center_point
    if point is None:
        envelope = geometry_result.spatial_envelope
        if envelope is None:
            return None
        point = envelope.centroid
    return float(point.x), float(point.y)


def _local_equal_area_transformer(point_a, point_b):
    lon_a, lat_a = point_a
    lon_b, lat_b = point_b
    x = cos(radians(lon_a)) + cos(radians(lon_b))
    y = sin(radians(lon_a)) + sin(radians(lon_b))
    lon_0 = lon_a if hypot(x, y) < 1e-12 else degrees(atan2(y, x))
    lat_0 = (lat_a + lat_b) / 2.0
    local_crs = CRS.from_proj4(
        f"+proj=laea +lat_0={lat_0} +lon_0={lon_0} "
        "+datum=WGS84 +units=m +no_defs +type=crs"
    )
    return Transformer.from_crs(
        CRS.from_epsg(4326),
        local_crs,
        always_xy=True,
    ).transform


def _geodesic_center_distance_km(point_a, point_b):
    if point_a is None or point_b is None:
        return None
    _, _, distance_m = _WGS84_GEOD.inv(
        point_a[0], point_a[1], point_b[0], point_b[1]
    )
    return distance_m / 1000.0


def evaluate_screening_envelope_metrics(
    geometry_a,
    geometry_b,
    *,
    center_distance_km: float | None = None,
) -> ScreeningEnvelopeMetrics:
    """Measure overlap evidence in a pair-centred equal-area projection.

    All polygon metrics describe Phase 2 conservative screening envelopes;
    they are not physical pixel-footprint metrics.
    """
    envelope_a = geometry_a.spatial_envelope
    envelope_b = geometry_b.spatial_envelope
    point_a = _point_coordinates(geometry_a)
    point_b = _point_coordinates(geometry_b)
    if center_distance_km is None:
        center_distance_km = _geodesic_center_distance_km(point_a, point_b)

    if envelope_a is None or envelope_b is None:
        return ScreeningEnvelopeMetrics(
            intersects=None,
            intersection_area_km2=None,
            union_area_km2=None,
            iou=None,
            containment_a=None,
            containment_b=None,
            minimum_boundary_distance_km=None,
            center_distance_km=center_distance_km,
            normalized_center_distance=None,
            method=None,
        )

    if point_a is None or point_b is None:
        raise ValueError("Envelope metrics require both geometry centres")
    transformer = _local_equal_area_transformer(point_a, point_b)
    projected_a = shapely_transform(
        envelope_a,
        transformer,
        interleaved=False,
    )
    projected_b = shapely_transform(
        envelope_b,
        transformer,
        interleaved=False,
    )

    if (
        projected_a.is_empty
        or projected_b.is_empty
        or not projected_a.is_valid
        or not projected_b.is_valid
    ):
        raise ValueError("Projected screening envelope is empty or invalid")

    area_a = projected_a.area
    area_b = projected_b.area
    intersection_area = projected_a.intersection(projected_b).area
    union_area = area_a + area_b - intersection_area
    if not all(isfinite(value) for value in (area_a, area_b, intersection_area, union_area)):
        raise ValueError("Projected screening-envelope area is not finite")
    if area_a <= 0 or area_b <= 0 or union_area <= 0:
        raise ValueError("Projected screening envelopes must have positive area")

    intersection_km2 = intersection_area / 1_000_000.0
    union_km2 = union_area / 1_000_000.0
    effective_radius_a_km = sqrt(area_a / pi) / 1000.0
    effective_radius_b_km = sqrt(area_b / pi) / 1000.0
    normalized_distance = (
        center_distance_km / (effective_radius_a_km + effective_radius_b_km)
        if center_distance_km is not None
        else None
    )

    return ScreeningEnvelopeMetrics(
        intersects=bool(projected_a.intersects(projected_b)),
        intersection_area_km2=intersection_km2,
        union_area_km2=union_km2,
        iou=max(0.0, min(1.0, intersection_area / union_area)),
        containment_a=max(0.0, min(1.0, intersection_area / area_a)),
        containment_b=max(0.0, min(1.0, intersection_area / area_b)),
        minimum_boundary_distance_km=(
            projected_a.boundary.distance(projected_b.boundary) / 1000.0
        ),
        center_distance_km=center_distance_km,
        normalized_center_distance=normalized_distance,
        method="pair_centered_lambert_azimuthal_equal_area",
    )


def evaluate_screening_envelope_intersection(geometry_a, geometry_b):
    """Compatibility helper returning only the conservative-envelope test."""
    return evaluate_screening_envelope_metrics(
        geometry_a,
        geometry_b,
    ).intersects
