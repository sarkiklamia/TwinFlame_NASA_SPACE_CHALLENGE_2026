from itertools import product

from .thresholds import (
    CandidateThresholdExperiment,
    DEFAULT_DISTANCE_THRESHOLDS_KM,
    DEFAULT_TIME_THRESHOLDS_MINUTES,
)


def _number_token(value: float) -> str:
    return format(value, "g").replace(".", "p")


def build_threshold_experiments(
    time_thresholds_minutes=DEFAULT_TIME_THRESHOLDS_MINUTES,
    distance_thresholds_km=DEFAULT_DISTANCE_THRESHOLDS_KM,
) -> tuple[CandidateThresholdExperiment, ...]:
    """Build every time-distance threshold combination."""

    times = tuple(float(value) for value in time_thresholds_minutes)
    distances = tuple(float(value) for value in distance_thresholds_km)

    if not times or not distances:
        raise ValueError("Both threshold collections must be non-empty")

    if len(set(times)) != len(times):
        raise ValueError("Time thresholds must be unique")

    if len(set(distances)) != len(distances):
        raise ValueError("Distance thresholds must be unique")

    return tuple(
        CandidateThresholdExperiment(
            experiment_id=(
                f"T{_number_token(time_value)}m"
                f"_D{_number_token(distance_value)}km"
            ),
            time_threshold_minutes=time_value,
            distance_threshold_km=distance_value,
        )
        for time_value, distance_value in product(times, distances)
    )
