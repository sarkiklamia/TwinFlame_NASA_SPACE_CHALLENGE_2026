from collections import Counter, defaultdict

from ...contracts.candidate import (
    CandidateExperimentSummary,
    CandidatePair,
    Phase03Result,
)
from ...config.experiments import build_threshold_experiments
from .spatial_index import center_distance_km
from .temporal_filter import (
    _utc_timestamp,
    count_temporal_pairs,
    iter_spatiotemporal_pairs,
)


SUPPORTED_PLATFORM_PAIRS = (
    ("MODIS_TERRA", "MODIS_AQUA"),
    ("VIIRS_NOAA20", "VIIRS_NOAA21"),
    ("MODIS_TERRA", "VIIRS_NOAA20"),
    ("MODIS_TERRA", "VIIRS_NOAA21"),
    ("MODIS_AQUA", "VIIRS_NOAA20"),
    ("MODIS_AQUA", "VIIRS_NOAA21"),
)


def _extract_phase_02_results(phase_02_input):
    if hasattr(phase_02_input, "results"):
        return tuple(phase_02_input.results)

    return tuple(phase_02_input)


def _prepare_records(geometry_results):
    records_by_platform = defaultdict(list)
    seen_ids = set()

    for geometry in geometry_results:
        qc_result = geometry.qc_result

        if not qc_result.eligible_for_spatial_matching:
            continue

        if geometry.center_point is None:
            continue

        observation = qc_result.observation
        platform = observation.platform
        detection_id = observation.detection_id

        if not platform or not detection_id:
            continue

        identity = (platform, detection_id)

        if identity in seen_ids:
            raise ValueError(
                "Duplicate detection identity in Phase 3 input: "
                f"{platform}/{detection_id}"
            )

        seen_ids.add(identity)

        timestamp = _utc_timestamp(observation)

        records_by_platform[platform].append(
            (timestamp, geometry)
        )

    for platform in records_by_platform:
        records_by_platform[platform].sort(
            key=lambda item: (
                item[0],
                item[1].qc_result.observation.detection_id,
            )
        )

    return records_by_platform


def _validate_experiments(experiments):
    experiments = tuple(experiments)

    if not experiments:
        raise ValueError(
            "At least one threshold experiment is required"
        )

    identifiers = [
        item.experiment_id for item in experiments
    ]

    if len(set(identifiers)) != len(identifiers):
        raise ValueError(
            "Threshold experiment IDs must be unique"
        )

    return experiments


def run_phase_03(
    phase_02_input,
    experiments=None,
    platform_pairs=SUPPORTED_PLATFORM_PAIRS,
) -> Phase03Result:
    """
    Generate cross-platform candidate pairs.

    A candidate MUST satisfy both conditions simultaneously:

        absolute time difference <= T
        AND
        WGS84 centre distance <= D

    Each threshold experiment is evaluated independently.
    """
    geometry_results = _extract_phase_02_results(
        phase_02_input
    )

    if experiments is None:
        experiments = build_threshold_experiments()

    experiments = _validate_experiments(experiments)

    platform_pairs = tuple(
        tuple(pair) for pair in platform_pairs
    )

    if len(set(platform_pairs)) != len(platform_pairs):
        raise ValueError(
            "Platform pairs must not contain duplicates"
        )

    for pair in platform_pairs:
        if len(pair) != 2 or pair[0] == pair[1]:
            raise ValueError(
                f"Invalid cross-platform pair: {pair!r}"
            )

    records_by_platform = _prepare_records(
        geometry_results
    )

    maximum_time = max(
        item.time_threshold_minutes
        for item in experiments
    )

    maximum_distance = max(
        item.distance_threshold_km
        for item in experiments
    )

    # Count the broad temporal window without retaining all pairs, then use
    # a conservative 3D spatial index before exact geodesic measurements.
    temporal_pair_count = count_temporal_pairs(
        records_by_platform,
        platform_pairs,
        maximum_time,
    )
    measured_pairs = []

    for geometry_a, geometry_b, time_difference in iter_spatiotemporal_pairs(
        records_by_platform,
        platform_pairs,
        maximum_time,
        maximum_distance,
    ):
        distance = center_distance_km(
            geometry_a,
            geometry_b,
        )

        if distance > maximum_distance:
            continue

        observation_a = geometry_a.qc_result.observation
        observation_b = geometry_b.qc_result.observation

        measured_pairs.append(
            (
                observation_a,
                observation_b,
                time_difference,
                distance,
            )
        )

    candidates = []
    summaries = []

    # Evaluate all threshold experiments independently.
    for experiment in experiments:
        counts_by_pair = Counter()
        experiment_candidates = []

        for (
            observation_a,
            observation_b,
            time_difference,
            distance,
        ) in measured_pairs:

            # BOTH conditions are mandatory.
            if time_difference > experiment.time_threshold_minutes:
                continue

            if distance > experiment.distance_threshold_km:
                continue

            platform_a = observation_a.platform
            platform_b = observation_b.platform

            id_a = observation_a.detection_id
            id_b = observation_b.detection_id

            pair_label = (
                f"{platform_a}__{platform_b}"
            )

            candidate = CandidatePair(
                candidate_id=(
                    f"{experiment.experiment_id}|"
                    f"{platform_a}|{id_a}|"
                    f"{platform_b}|{id_b}"
                ),
                experiment_id=experiment.experiment_id,
                detection_id_a=id_a,
                detection_id_b=id_b,
                platform_a=platform_a,
                platform_b=platform_b,
                platform_pair=pair_label,
                time_difference_minutes=time_difference,
                center_distance_km=distance,
                time_threshold_minutes=(
                    experiment.time_threshold_minutes
                ),
                distance_threshold_km=(
                    experiment.distance_threshold_km
                ),
            )

            experiment_candidates.append(candidate)
            counts_by_pair[pair_label] += 1

        candidates.extend(experiment_candidates)

        summaries.append(
            CandidateExperimentSummary(
                experiment_id=experiment.experiment_id,
                time_threshold_minutes=(
                    experiment.time_threshold_minutes
                ),
                distance_threshold_km=(
                    experiment.distance_threshold_km
                ),
                temporal_pairs_examined=temporal_pair_count,
                pairs_within_maximum_distance=len(measured_pairs),
                candidate_count=len(experiment_candidates),
                candidate_counts_by_platform_pair=tuple(
                    (
                        f"{platform_a}__{platform_b}",
                        counts_by_pair.get(
                            f"{platform_a}__{platform_b}",
                            0,
                        ),
                    )
                    for platform_a, platform_b in platform_pairs
                ),
            )
        )

    return Phase03Result(
        experiments=experiments,
        candidates=tuple(candidates),
        summaries=tuple(summaries),
    )
