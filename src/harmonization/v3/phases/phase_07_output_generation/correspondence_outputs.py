from collections import defaultdict
from datetime import datetime
from statistics import mean, median
from typing import Any, Iterable

from ...contracts.correspondence import Phase04AResult
from .output_validation import validate_output_rows


def _unwrap_observation(value: Any) -> Any:
    return getattr(value, "observation", value)


def _observation_index(observations: Iterable[Any]) -> dict:
    index = {}

    for value in observations:
        observation = _unwrap_observation(value)
        key = (observation.platform, observation.detection_id)

        if None in key:
            raise ValueError(
                "Observation platform and detection_id must be present"
            )

        if key in index:
            raise ValueError(f"Duplicate observation identity: {key}")

        index[key] = observation

    return index


def _utc_timestamp(observation: Any, key: tuple) -> datetime:
    timestamp = getattr(observation, "acquisition_time_utc", None)

    if not isinstance(timestamp, datetime):
        raise ValueError(
            f"Missing or invalid acquisition timestamp for {key}"
        )

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(
            f"Acquisition timestamp must be timezone-aware UTC: {key}"
        )

    if timestamp.utcoffset().total_seconds() != 0:
        raise ValueError(
            f"Acquisition timestamp is not UTC: {key}"
        )

    return timestamp


def _decision_reason(evaluation: Any) -> str:
    return (
        "Phase 4A evaluates candidate and screening-envelope evidence "
        "only; correspondence classification is not implemented."
    )


def build_correspondence_edges(
    phase_04a_result: Phase04AResult,
    run_id: str,
) -> list[dict]:
    """Build one row per candidate evaluation per experiment."""
    if not run_id:
        raise ValueError("run_id must be a non-empty string")

    rows = []

    for evaluation in phase_04a_result.evaluations:
        candidate = evaluation.candidate

        rows.append({
            "correspondence_edge_id": candidate.candidate_id,
            "detection_id_a": candidate.detection_id_a,
            "detection_id_b": candidate.detection_id_b,
            "platform_a": candidate.platform_a,
            "platform_b": candidate.platform_b,
            "experiment_id": candidate.experiment_id,
            "time_threshold_minutes": candidate.time_threshold_minutes,
            "distance_threshold_km": candidate.distance_threshold_km,
            "time_difference_minutes": candidate.time_difference_minutes,
            "centre_distance_km": candidate.center_distance_km,
            "intersection_area_km2": evaluation.intersection_area_km2,
            "union_area_km2": evaluation.union_area_km2,
            "iou": evaluation.iou,
            "containment_a": evaluation.containment_a,
            "containment_b": evaluation.containment_b,
            "minimum_boundary_distance_km": (
                evaluation.minimum_boundary_distance_km
            ),
            "normalized_centre_distance": evaluation.normalized_center_distance,
            "metric_method": evaluation.metric_method,
            "decision_class": "not_classified",
            "decision_reason": _decision_reason(evaluation),
            "geometry_quality": evaluation.geometry_evidence_status,
            "run_id": run_id,
        })

    validate_output_rows("harm_correspondence_edges", rows)
    return rows


def build_correspondence_summary(
    phase_04a_result: Phase04AResult,
    observations: Iterable[Any],
    run_id: str,
) -> list[dict]:
    """
    Summarize candidates by earlier UTC date, platform pair,
    and threshold experiment.
    """
    if not run_id:
        raise ValueError("run_id must be a non-empty string")

    observation_by_key = _observation_index(observations)
    groups = defaultdict(list)

    for evaluation in phase_04a_result.evaluations:
        candidate = evaluation.candidate

        key_a = (candidate.platform_a, candidate.detection_id_a)
        key_b = (candidate.platform_b, candidate.detection_id_b)

        try:
            observation_a = observation_by_key[key_a]
            observation_b = observation_by_key[key_b]
        except KeyError as exc:
            raise ValueError(
                f"Missing observation required for candidate endpoint: "
                f"{exc.args[0]}"
            ) from exc

        timestamp_a = _utc_timestamp(observation_a, key_a)
        timestamp_b = _utc_timestamp(observation_b, key_b)

        summary_date = min(timestamp_a, timestamp_b).date()

        group_key = (
            summary_date,
            candidate.platform_pair,
            candidate.experiment_id,
            candidate.time_threshold_minutes,
            candidate.distance_threshold_km,
        )

        groups[group_key].append(evaluation)

    rows = []

    for group_key, evaluations in sorted(groups.items()):
        (
            summary_date,
            platform_pair,
            experiment_id,
            time_threshold,
            distance_threshold,
        ) = group_key

        time_differences = [
            item.candidate.time_difference_minutes
            for item in evaluations
        ]

        insufficient_geometry_count = sum(
            item.geometry_evidence_status
            != "both_screening_envelopes_available"
            for item in evaluations
        )

        rows.append({
            "date_utc": summary_date,
            "platform_pair": platform_pair,
            "experiment_id": experiment_id,
            "time_threshold_minutes": time_threshold,
            "distance_threshold_km": distance_threshold,
            "candidate_count": len(evaluations),
            "strong_count": 0,
            "possible_count": 0,
            "rejected_count": 0,
            "insufficient_geometry_count": insufficient_geometry_count,
            "mean_time_difference_minutes": mean(time_differences),
            "median_time_difference_minutes": median(time_differences),
            "mean_iou": None,
            "run_id": run_id,
        })

    validate_output_rows("harm_correspondence_summary", rows)
    return rows
