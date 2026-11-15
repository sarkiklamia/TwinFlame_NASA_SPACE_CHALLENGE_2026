from dataclasses import dataclass


@dataclass(frozen=True)
class CandidatePair:
    """One cross-platform candidate relationship under one experiment."""

    candidate_id: str
    experiment_id: str

    detection_id_a: str
    detection_id_b: str

    platform_a: str
    platform_b: str
    platform_pair: str

    time_difference_minutes: float
    center_distance_km: float

    time_threshold_minutes: float
    distance_threshold_km: float


@dataclass(frozen=True)
class CandidateExperimentSummary:
    experiment_id: str
    time_threshold_minutes: float
    distance_threshold_km: float
    temporal_pairs_examined: int
    pairs_within_maximum_distance: int
    candidate_count: int
    candidate_counts_by_platform_pair: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Phase03Result:
    experiments: tuple
    candidates: tuple[CandidatePair, ...]
    summaries: tuple[CandidateExperimentSummary, ...]

    @property
    def experiment_count(self) -> int:
        return len(self.experiments)

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)
