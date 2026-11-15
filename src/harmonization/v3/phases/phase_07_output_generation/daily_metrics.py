import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any, Iterable

from ...contracts.observation import ObservationQCResult
from ...phases.phase_01_quality_control.quality_rules import (
    evaluate_observation,
)
from .output_validation import validate_output_rows


_BRIGHTNESS_FIELDS = {
    "MODIS_TERRA": ("brightness_native", "bright_t31"),
    "MODIS_AQUA": ("brightness_native", "bright_t31"),
    "VIIRS_NOAA20": ("bright_ti4", "bright_ti5"),
    "VIIRS_NOAA21": ("bright_ti4", "bright_ti5"),
}


def _validate_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")


def _unwrap_and_assess(value: Any) -> ObservationQCResult:
    if isinstance(value, ObservationQCResult):
        return value
    return evaluate_observation(value)


def _utc_timestamp(observation: Any) -> datetime:
    timestamp = getattr(observation, "acquisition_time_utc", None)

    if not isinstance(timestamp, datetime):
        raise ValueError(
            "Every observation must have a valid acquisition_time_utc"
        )

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(
            "Every acquisition timestamp must be timezone-aware"
        )

    return timestamp.astimezone(timezone.utc)


def _finite_measurement(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _brightness_fields(platform: str) -> tuple[str, str]:
    try:
        return _BRIGHTNESS_FIELDS[platform]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported platform for daily brightness metrics: {platform}"
        ) from exc


def _summarize(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None

    return mean(values), median(values)


def build_sensor_activity_daily(
    observations: Iterable[Any],
    run_id: str,
) -> list[dict]:
    """
    Build one daily activity row per UTC date and platform.

    Raw observations are assessed using Phase 1 QC. Existing
    ObservationQCResult wrappers retain their supplied eligibility flags.

    FRP statistics use FRP-eligible observations only.
    Brightness statistics use all finite available native measurements.
    """
    _validate_run_id(run_id)

    grouped: dict[tuple, dict] = {}
    seen_ids: set[tuple[str, str]] = set()

    for value in observations:
        qc_result = _unwrap_and_assess(value)
        observation = qc_result.observation

        platform_value = getattr(observation, "platform", None)
        platform = str(
            getattr(platform_value, "value", platform_value) or ""
        ).strip()

        if not platform:
            raise ValueError("Observation platform must be present")

        timestamp = _utc_timestamp(observation)
        date_utc = timestamp.date()

        detection_id = getattr(observation, "detection_id", None)
        if detection_id is not None and str(detection_id).strip():
            identity = (platform, str(detection_id))
            if identity in seen_ids:
                raise ValueError(
                    f"Duplicate observation identity: {identity}"
                )
            seen_ids.add(identity)

        key = (date_utc, platform)

        if key not in grouped:
            band_1_field, band_2_field = _brightness_fields(platform)
            grouped[key] = {
                "detection_count": 0,
                "matching_eligible_count": 0,
                "frp_eligible_count": 0,
                "frp_values": [],
                "band_1_field": band_1_field,
                "band_2_field": band_2_field,
                "band_1_values": [],
                "band_2_values": [],
            }

        bucket = grouped[key]
        bucket["detection_count"] += 1

        if qc_result.eligible_for_spatial_matching:
            bucket["matching_eligible_count"] += 1

        if qc_result.eligible_for_frp_analysis:
            frp = _finite_measurement(
                getattr(observation, "frp_mw", None)
            )
            if frp is None or frp < 0:
                raise ValueError(
                    "FRP-eligible observation has invalid FRP"
                )

            bucket["frp_eligible_count"] += 1
            bucket["frp_values"].append(frp)

        band_1 = _finite_measurement(
            getattr(observation, bucket["band_1_field"], None)
        )
        band_2 = _finite_measurement(
            getattr(observation, bucket["band_2_field"], None)
        )

        if band_1 is not None:
            bucket["band_1_values"].append(band_1)

        if band_2 is not None:
            bucket["band_2_values"].append(band_2)

    rows = []

    for (date_utc, platform), bucket in sorted(grouped.items()):
        frp_values = bucket["frp_values"]
        band_1_mean, band_1_median = _summarize(
            bucket["band_1_values"]
        )
        band_2_mean, band_2_median = _summarize(
            bucket["band_2_values"]
        )

        rows.append({
            "date_utc": date_utc,
            "platform": platform,
            "detection_count": bucket["detection_count"],
            "matching_eligible_count": bucket[
                "matching_eligible_count"
            ],
            "frp_eligible_count": bucket["frp_eligible_count"],
            "frp_sum_mw": math.fsum(frp_values) if frp_values else None,
            "frp_mean_mw": mean(frp_values) if frp_values else None,
            "frp_median_mw": median(frp_values) if frp_values else None,
            "brightness_band_1_mean_k": band_1_mean,
            "brightness_band_1_median_k": band_1_median,
            "brightness_band_2_mean_k": band_2_mean,
            "brightness_band_2_median_k": band_2_median,
            "run_id": run_id,
        })

    validate_output_rows("harm_sensor_activity_daily", rows)
    return rows
