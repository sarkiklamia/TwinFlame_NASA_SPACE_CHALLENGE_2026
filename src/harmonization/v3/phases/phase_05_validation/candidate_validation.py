from collections import defaultdict

from harmonization.v3.contracts.validation import (
    CandidateRecallResult,
    ReferenceCorrespondence,
)


def _identity(platform, detection_id):
    return str(platform), str(detection_id)


def _pair_key(platform_a, detection_id_a, platform_b, detection_id_b):
    left = _identity(platform_a, detection_id_a)
    right = _identity(platform_b, detection_id_b)

    if left == right:
        raise ValueError("A correspondence reference cannot pair a detection with itself")

    return tuple(sorted((left, right)))


def _reference_key(reference):
    return _pair_key(
        reference.platform_a,
        reference.detection_id_a,
        reference.platform_b,
        reference.detection_id_b,
    )


def validate_candidate_recall(phase03_result, reference_pairs):
    """
    Measure candidate-generation recall against independent known pairs.

    This measures retrieval only. It does not measure correspondence precision.
    """
    references = tuple(reference_pairs)
    reference_by_key = {}

    for reference in references:
        if not isinstance(reference, ReferenceCorrespondence):
            raise TypeError("reference_pairs must contain ReferenceCorrespondence objects")

        key = _reference_key(reference)
        if key in reference_by_key:
            raise ValueError(f"Duplicate reference correspondence: {key}")
        reference_by_key[key] = reference

    candidates_by_experiment = defaultdict(set)

    for candidate in phase03_result.candidates:
        key = _pair_key(
            candidate.platform_a,
            candidate.detection_id_a,
            candidate.platform_b,
            candidate.detection_id_b,
        )
        candidates_by_experiment[candidate.experiment_id].add(key)

    experiment_by_id = {
        experiment.experiment_id: experiment
        for experiment in phase03_result.experiments
    }

    results = []

    for experiment_id in sorted(experiment_by_id):
        experiment = experiment_by_id[experiment_id]
        candidate_keys = candidates_by_experiment.get(experiment_id, set())

        retrieved = tuple(
            sorted(
                key for key in reference_by_key
                if key in candidate_keys
            )
        )

        missed_keys = sorted(
            key for key in reference_by_key
            if key not in candidate_keys
        )

        missed_references = tuple(
            reference_by_key[key] for key in missed_keys
        )

        recall = (
            len(retrieved) / len(reference_by_key)
            if reference_by_key
            else None
        )

        results.append(
            CandidateRecallResult(
                experiment_id=experiment_id,
                time_threshold_minutes=experiment.time_threshold_minutes,
                distance_threshold_km=experiment.distance_threshold_km,
                candidate_count=len(candidate_keys),
                reference_pair_count=len(reference_by_key),
                retrieved_reference_pair_count=len(retrieved),
                missed_reference_pairs=missed_references,
                candidate_recall=recall,
            )
        )

    return tuple(results)
