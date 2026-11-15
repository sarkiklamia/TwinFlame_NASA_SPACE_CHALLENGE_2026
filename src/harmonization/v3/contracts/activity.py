from dataclasses import dataclass
from datetime import date, datetime
import math


@dataclass(frozen=True)
class ActivityThresholdExperiment:
    experiment_id: str
    distance_threshold_km: float

    def __post_init__(self):
        if not self.experiment_id:
            raise ValueError("experiment_id must not be empty")
        if not math.isfinite(self.distance_threshold_km) or self.distance_threshold_km <= 0:
            raise ValueError("distance_threshold_km must be finite and positive")


@dataclass(frozen=True)
class DailyActivityMembership:
    experiment_id: str
    cluster_id: str
    platform: str
    detection_id: str
    acquisition_time_utc: datetime


@dataclass(frozen=True)
class DailyActivityCluster:
    cluster_id: str
    experiment_id: str
    activity_date_utc: date
    distance_threshold_km: float
    member_count: int
    member_keys: tuple[tuple[str, str], ...]
    platform_counts: tuple[tuple[str, int], ...]
    min_acquisition_time_utc: datetime
    max_acquisition_time_utc: datetime
    maximum_edge_distance_km: float
    clustering_method: str = "connected_components"
    chaining_possible: bool = True


@dataclass(frozen=True)
class ActivityExperimentSummary:
    experiment_id: str
    distance_threshold_km: float
    detection_count: int
    cluster_count: int
    singleton_count: int
    largest_cluster_size: int


@dataclass(frozen=True)
class Phase04BResult:
    experiments: tuple[ActivityThresholdExperiment, ...]
    clusters: tuple[DailyActivityCluster, ...]
    memberships: tuple[DailyActivityMembership, ...]
    summaries: tuple[ActivityExperimentSummary, ...]
    memberships_retained: bool = True

    @property
    def total_cluster_count(self) -> int:
        return len(self.clusters)

    @property
    def total_membership_count(self) -> int:
        return sum(cluster.member_count for cluster in self.clusters)
