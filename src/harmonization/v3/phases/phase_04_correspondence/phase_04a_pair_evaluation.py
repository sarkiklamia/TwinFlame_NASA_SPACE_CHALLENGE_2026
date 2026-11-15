from ...contracts.correspondence import (
    CorrespondenceEvaluation,
    Phase04AResult,
)
from .decision_rules import (
    candidate_evaluation_status,
    geometry_evidence_status,
)
from .spatial_metrics import evaluate_screening_envelope_metrics


def _extract_candidates(value):
    if hasattr(value, "candidates"):
        return tuple(value.candidates)
    return tuple(value)


def _extract_geometries(value):
    if hasattr(value, "results"):
        return tuple(value.results)
    return tuple(value)


def _geometry_index(geometry_results):
    index = {}

    for geometry in geometry_results:
        observation = geometry.qc_result.observation
        key = (observation.platform, observation.detection_id)

        if key in index:
            raise ValueError(
                "Duplicate geometry identity in Phase 4A input: "
                f"{key[0]}/{key[1]}"
            )

        index[key] = geometry

    return index


def _provenance_values(geometry, attribute):
    value = getattr(geometry.provenance, attribute, ())
    return tuple(value or ())


def run_phase_04a(phase_03_input, phase_02_input):
    """
    Evaluate every Phase 3 candidate independently.

    Many-to-many relationships and experiment identities are preserved.
    This phase does not classify candidates as confirmed matches.
    """
    candidates = _extract_candidates(phase_03_input)
    geometries = _geometry_index(
        _extract_geometries(phase_02_input)
    )

    candidate_ids = [item.candidate_id for item in candidates]

    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError(
            "Candidate IDs must be unique in Phase 4A input"
        )

    evaluations = []
    metrics_by_pair = {}

    for candidate in candidates:
        key_a = (candidate.platform_a, candidate.detection_id_a)
        key_b = (candidate.platform_b, candidate.detection_id_b)

        if key_a not in geometries:
            raise ValueError(
                f"Missing Phase 2 geometry for candidate endpoint: {key_a}"
            )

        if key_b not in geometries:
            raise ValueError(
                f"Missing Phase 2 geometry for candidate endpoint: {key_b}"
            )

        geometry_a = geometries[key_a]
        geometry_b = geometries[key_b]

        pair_key = (key_a, key_b)
        metrics = metrics_by_pair.get(pair_key)
        if metrics is None:
            metrics = evaluate_screening_envelope_metrics(
                geometry_a,
                geometry_b,
                center_distance_km=candidate.center_distance_km,
            )
            metrics_by_pair[pair_key] = metrics

        evaluations.append(
            CorrespondenceEvaluation(
                candidate=candidate,
                evaluation_status=candidate_evaluation_status(),
                geometry_evidence_status=geometry_evidence_status(
                    geometry_a, geometry_b
                ),
                geometry_status_a=geometry_a.geometry_status,
                geometry_status_b=geometry_b.geometry_status,
                geometry_method_a=geometry_a.provenance.method,
                geometry_method_b=geometry_b.provenance.method,
                screening_envelopes_intersect=metrics.intersects,
                geometry_assumptions_a=_provenance_values(
                    geometry_a, "assumptions"
                ),
                geometry_assumptions_b=_provenance_values(
                    geometry_b, "assumptions"
                ),
                geometry_limitations_a=_provenance_values(
                    geometry_a, "limitations"
                ),
                geometry_limitations_b=_provenance_values(
                    geometry_b, "limitations"
                ),
                intersection_area_km2=metrics.intersection_area_km2,
                union_area_km2=metrics.union_area_km2,
                iou=metrics.iou,
                containment_a=metrics.containment_a,
                containment_b=metrics.containment_b,
                minimum_boundary_distance_km=(
                    metrics.minimum_boundary_distance_km
                ),
                normalized_center_distance=(
                    metrics.normalized_center_distance
                ),
                metric_method=metrics.method,
            )
        )

    return Phase04AResult(evaluations=tuple(evaluations))
