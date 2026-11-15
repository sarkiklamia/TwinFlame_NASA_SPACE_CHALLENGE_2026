import math

from shapely.geometry import Point

from ...contracts.geometry import ObservationGeometryResult
from ...utils.geo_utils import build_conservative_envelope
from .geometry_provenance import (
    center_only_provenance,
    conservative_envelope_provenance,
)


def _valid_dimension(value) -> bool:
    return (
        isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def build_observation_geometry(qc_result) -> ObservationGeometryResult:
    observation = qc_result.observation

    if not qc_result.eligible_for_spatial_matching:
        return ObservationGeometryResult(
            qc_result=qc_result,
            center_point=None,
            spatial_envelope=None,
            geometry_status="ineligible",
            envelope_radius_km=None,
            provenance=center_only_provenance(
                "Observation failed Phase 1 spatial eligibility."
            ),
            geometry_issues=("spatially_ineligible",),
        )

    center = Point(observation.longitude, observation.latitude)

    scan_km = observation.scan_km
    track_km = observation.track_km

    invalid_dimensions = []

    if not _valid_dimension(scan_km):
        invalid_dimensions.append("scan_km")

    if not _valid_dimension(track_km):
        invalid_dimensions.append("track_km")

    if invalid_dimensions:
        return ObservationGeometryResult(
            qc_result=qc_result,
            center_point=center,
            spatial_envelope=None,
            geometry_status="center_only",
            envelope_radius_km=None,
            provenance=center_only_provenance(
                "Missing, non-finite, or non-positive dimensions: "
                + ", ".join(invalid_dimensions)
            ),
            geometry_issues=tuple(
                f"unavailable_or_invalid:{field}"
                for field in invalid_dimensions
            ),
        )

    try:
        envelope, radius_km = build_conservative_envelope(
            longitude=observation.longitude,
            latitude=observation.latitude,
            scan_km=scan_km,
            track_km=track_km,
        )
    except (ValueError, OverflowError) as exc:
        return ObservationGeometryResult(
            qc_result=qc_result,
            center_point=center,
            spatial_envelope=None,
            geometry_status="center_only",
            envelope_radius_km=None,
            provenance=center_only_provenance(
                f"Envelope construction failed: {exc}"
            ),
            geometry_issues=("envelope_construction_failed",),
        )

    return ObservationGeometryResult(
        qc_result=qc_result,
        center_point=center,
        spatial_envelope=envelope,
        geometry_status="conservative_envelope",
        envelope_radius_km=radius_km,
        provenance=conservative_envelope_provenance(),
        geometry_issues=(),
    )
