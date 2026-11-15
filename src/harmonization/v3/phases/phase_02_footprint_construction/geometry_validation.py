import math


VALID_STATUSES = {
    "ineligible",
    "center_only",
    "conservative_envelope",
}


def validate_geometry_result(result) -> None:
    if result.geometry_status not in VALID_STATUSES:
        raise ValueError(
            f"Unknown geometry status: {result.geometry_status!r}"
        )

    if result.geometry_status == "ineligible":
        if result.center_point is not None or result.spatial_envelope is not None:
            raise ValueError("Ineligible observations must not have geometries.")

        if result.qc_result.eligible_for_spatial_matching:
            raise ValueError("Ineligible geometry conflicts with Phase 1 QC.")

        return

    if not result.qc_result.eligible_for_spatial_matching:
        raise ValueError("Geometry exists for a spatially ineligible observation.")

    center = result.center_point

    if center is None or center.is_empty or not center.is_valid:
        raise ValueError("Eligible observation requires a valid centre point.")

    if result.geometry_status == "center_only":
        if result.spatial_envelope is not None:
            raise ValueError("Center-only result must not contain an envelope.")

        if result.envelope_radius_km is not None:
            raise ValueError("Center-only result must not have an envelope radius.")

        return

    envelope = result.spatial_envelope

    if envelope is None or envelope.is_empty or not envelope.is_valid:
        raise ValueError("Conservative envelope must be a valid geometry.")

    if not envelope.covers(center):
        raise ValueError("Conservative envelope must cover the detection centre.")

    radius = result.envelope_radius_km

    if radius is None or not math.isfinite(radius) or radius <= 0:
        raise ValueError("Conservative envelope requires a positive finite radius.")

    if result.provenance.orientation_known:
        raise ValueError("Orientation must be unknown for this envelope method.")

    limitations = " ".join(result.provenance.limitations)

    if "actual sensor pixel footprint" not in limitations:
        raise ValueError(
            "Provenance must state that this is not an actual sensor footprint."
        )


def validate_phase_02_output(qc_results, geometry_results) -> None:
    if len(qc_results) != len(geometry_results):
        raise ValueError("Phase 2 must return one result per Phase 1 input.")

    for qc_result, geometry_result in zip(qc_results, geometry_results):
        if geometry_result.qc_result is not qc_result:
            raise ValueError(
                "Phase 2 must preserve the original Phase 1 result."
            )

        validate_geometry_result(geometry_result)
