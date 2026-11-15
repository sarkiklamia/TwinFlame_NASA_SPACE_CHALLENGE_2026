import math
from typing import Any

from ...contracts.observation import ObservationQCResult


def _is_finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def evaluate_observation(observation: Any) -> ObservationQCResult:
    """
    Evaluate usability without deleting or modifying the input observation.

    Spatial eligibility and FRP eligibility are deliberately separate.
    """
    issues = list(observation.mapping_issues)
    warnings: list[str] = []
    spatial_reasons: list[str] = []

    # Stable identifier
    if not observation.detection_id:
        spatial_reasons.append("missing_detection_id")

    # Supported sensor/platform
    if not observation.platform:
        spatial_reasons.append("unsupported_or_missing_platform")

    # Acquisition timestamp must already be UTC-aware.
    timestamp = observation.acquisition_time_utc
    if timestamp is None:
        spatial_reasons.append("missing_or_invalid_acquisition_timestamp")
    elif timestamp.tzinfo is None or timestamp.utcoffset() is None:
        spatial_reasons.append("acquisition_timestamp_not_timezone_aware")

    # Geographic coordinates
    latitude = observation.latitude
    longitude = observation.longitude

    if latitude is None or not _is_finite(latitude):
        spatial_reasons.append("missing_or_invalid_latitude")
    elif not -90.0 <= latitude <= 90.0:
        spatial_reasons.append("latitude_out_of_range")

    if longitude is None or not _is_finite(longitude):
        spatial_reasons.append("missing_or_invalid_longitude")
    elif not -180.0 <= longitude <= 180.0:
        spatial_reasons.append("longitude_out_of_range")

    spatial_eligible = not spatial_reasons
    issues.extend(spatial_reasons)

    # FRP eligibility is assessed independently from spatial eligibility.
    frp_reasons: list[str] = []

    if not spatial_eligible:
        frp_reasons.append("not_spatially_eligible")

    frp = observation.frp_mw

    if frp is None:
        frp_reasons.append("missing_frp")
        warnings.append("missing_frp")
    elif not _is_finite(frp):
        frp_reasons.append("non_finite_frp")
        issues.append("non_finite_frp")
    elif frp < 0:
        frp_reasons.append("negative_frp")
        issues.append("negative_frp")

    frp_eligible = spatial_eligible and not any(
        reason in {
            "missing_frp",
            "non_finite_frp",
            "negative_frp",
        }
        for reason in frp_reasons
    )

    # Optional measurements are recorded as warnings, not spatial exclusions.
    optional_measurements = {
        "brightness": observation.brightness_native,
        "bright_t31": observation.bright_t31,
        "bright_ti4": observation.bright_ti4,
        "bright_ti5": observation.bright_ti5,
        "scan_km": observation.scan_km,
        "track_km": observation.track_km,
    }

    for field, value in optional_measurements.items():
        if value is None:
            warnings.append(f"missing_{field}")
        elif not _is_finite(value):
            warnings.append(f"non_finite_{field}")

    # This flag means at least one native brightness field is present and
    # finite. Sentinel, band, unit, and cross-sensor semantics are not
    # certified by this availability check.
    brightness_fields = ("brightness", "bright_t31", "bright_ti4", "bright_ti5")
    brightness_values = tuple(optional_measurements[name] for name in brightness_fields)
    brightness_eligible = any(
        _is_finite(value)
        for value in brightness_values
    )

    # Pixel dimensions are not used here to reject spatial observations.
    # Phase 2 will decide how geometry can be constructed from available data.

    return ObservationQCResult(
        observation=observation,
        eligible_for_spatial_matching=spatial_eligible,
        eligible_for_frp_analysis=frp_eligible,
        qc_issues=tuple(dict.fromkeys(issues)),
        qc_warnings=tuple(dict.fromkeys(warnings)),
        eligible_for_brightness_analysis=brightness_eligible,
    )
