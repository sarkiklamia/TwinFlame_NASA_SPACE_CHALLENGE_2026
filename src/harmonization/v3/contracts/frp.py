from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class SpatialSupportAssignment:
    detection_id: str
    platform: str
    cell_id: str
    grid_resolution_km: float
    cell_x: int
    cell_y: int
    projected_x_m: float
    projected_y_m: float


@dataclass(frozen=True)
class TemporalSupportMembership:
    detection_id: str
    platform: str
    support_group_id: str
    support_date_utc: date
    group_start_utc: datetime
    group_end_utc: datetime
    max_group_span_minutes: float


@dataclass(frozen=True)
class CommonSupportMembership:
    detection_id: str
    platform: str
    support_unit_id: str
    spatial_cell_id: str
    temporal_group_id: str
    support_date_utc: date


@dataclass(frozen=True)
class SensorFRPAggregate:
    support_unit_id: str
    spatial_cell_id: str
    temporal_group_id: str
    support_date_utc: date
    platform: str
    observation_count: int
    frp_mean_mw: float
    frp_median_mw: float
    frp_min_mw: float
    frp_max_mw: float


@dataclass(frozen=True)
class FRPComparison:
    support_unit_id: str
    platform_a: str
    platform_b: str
    frp_a_mw: float
    frp_b_mw: float
    difference_mw: float
    relative_difference: float | None


@dataclass(frozen=True)
class CalibrationResult:
    platform_reference: str
    platform_target: str
    method: str
    intercept_mw: float
    slope: float
    training_count: int
    validation_count: int
    validation_metrics: tuple[tuple[str, float], ...]
    accepted: bool
    rejection_reasons: tuple[str, ...]


@dataclass(frozen=True)
class Phase06Result:
    spatial_assignments: tuple[SpatialSupportAssignment, ...]
    temporal_memberships: tuple[TemporalSupportMembership, ...]
    common_support_memberships: tuple[CommonSupportMembership, ...]
    sensor_aggregates: tuple[SensorFRPAggregate, ...]
    comparisons: tuple[FRPComparison, ...]
    calibration_results: tuple[CalibrationResult, ...]
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class SpatialSupportExperimentResult:
    grid_resolution_km: float
    assignments: tuple[SpatialSupportAssignment, ...]

@dataclass(frozen=True)
class CommonSupportExperimentResult:
    grid_resolution_km: float
    max_group_span_minutes: float
    memberships: tuple[CommonSupportMembership, ...]
