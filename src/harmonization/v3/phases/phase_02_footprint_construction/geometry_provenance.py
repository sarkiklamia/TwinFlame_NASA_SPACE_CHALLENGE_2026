from ...contracts.geometry import GeometryProvenance


def center_only_provenance(reason: str) -> GeometryProvenance:
    return GeometryProvenance(
        method="detection_center_only",
        source_dimensions=(),
        orientation_known=False,
        assumptions=(),
        limitations=(
            reason,
            "No pixel footprint or spatial envelope is available.",
        ),
    )


def conservative_envelope_provenance() -> GeometryProvenance:
    return GeometryProvenance(
        method="local_aeqd_circular_envelope_from_scan_track",
        source_dimensions=("scan_km", "track_km"),
        orientation_known=False,
        assumptions=(
            "scan_km and track_km are treated as perpendicular side lengths",
            "the detection coordinate is the centre of the dimension envelope",
            "a circle with half-diagonal radius encloses the rectangle "
            "regardless of its orientation",
        ),
        limitations=(
            "This is a conservative screening envelope, not the actual "
            "sensor pixel footprint.",
            "Pixel orientation and footprint vertices are unavailable.",
            "Envelope area and overlap are not physical pixel area or "
            "fractional pixel overlap.",
        ),
    )
