from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class ReferenceCorrespondence:
    """An independently verified cross-platform detection pair."""
    platform_a: str
    detection_id_a: str
    platform_b: str
    detection_id_b: str


@dataclass(frozen=True)
class ActivityReferenceLabel:
    """Independent activity label for one detection on one UTC date."""
    platform: str
    detection_id: str
    activity_date_utc: date
    activity_id: str


@dataclass(frozen=True)
class BinaryClassificationMetrics:
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: Optional[int]
    precision: Optional[float]
    recall: Optional[float]
    f1: Optional[float]
    specificity: Optional[float]
    accuracy: Optional[float]


@dataclass(frozen=True)
class CandidateRecallResult:
    experiment_id: str
    time_threshold_minutes: float
    distance_threshold_km: float
    candidate_count: int
    reference_pair_count: int
    retrieved_reference_pair_count: int
    missed_reference_pairs: tuple[ReferenceCorrespondence, ...]
    candidate_recall: Optional[float]


@dataclass(frozen=True)
class CorrespondenceValidationResult:
    decision_count: int
    reference_pair_count: int
    metrics: BinaryClassificationMetrics


@dataclass(frozen=True)
class ActivityValidationResult:
    experiment_id: str
    distance_threshold_km: float
    labelled_detection_count: int
    unlabelled_detection_count: int
    metrics: BinaryClassificationMetrics


@dataclass(frozen=True)
class ThresholdComparison:
    validation_type: str
    experiment_id: str
    time_threshold_minutes: Optional[float]
    distance_threshold_km: float
    metric_name: str
    metric_value: Optional[float]
    selected: bool = False
