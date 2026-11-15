from dataclasses import dataclass
from .candidate import CandidatePair


@dataclass(frozen=True)
class CorrespondenceEvaluation:
    """Evidence record for one candidate, not a confirmed correspondence."""

    candidate: CandidatePair
    evaluation_status: str
    geometry_evidence_status: str
    geometry_status_a: str
    geometry_status_b: str
    geometry_method_a: str
    geometry_method_b: str
    screening_envelopes_intersect: bool | None
    geometry_assumptions_a: tuple[str, ...]
    geometry_assumptions_b: tuple[str, ...]
    geometry_limitations_a: tuple[str, ...]
    geometry_limitations_b: tuple[str, ...]
    intersection_area_km2: float | None = None
    union_area_km2: float | None = None
    iou: float | None = None
    containment_a: float | None = None
    containment_b: float | None = None
    minimum_boundary_distance_km: float | None = None
    normalized_center_distance: float | None = None
    metric_method: str | None = None


@dataclass(frozen=True)
class Phase04AResult:
    evaluations: tuple[CorrespondenceEvaluation, ...]

    @property
    def candidate_count(self):
        return len(self.evaluations)

    @property
    def envelope_comparable_count(self):
        return sum(
            item.screening_envelopes_intersect is not None
            for item in self.evaluations
        )

    @property
    def envelope_intersection_count(self):
        return sum(
            item.screening_envelopes_intersect is True
            for item in self.evaluations
        )

    @property
    def counts_by_experiment(self):
        counts = {}
        for item in self.evaluations:
            key = item.candidate.experiment_id
            counts[key] = counts.get(key, 0) + 1
        return tuple(sorted(counts.items()))
