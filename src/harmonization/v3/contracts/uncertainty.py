from dataclasses import dataclass


@dataclass(frozen=True)
class BootstrapInterval:
    estimate: float
    lower: float
    upper: float
    confidence_level: float
    successful_replicates: int


@dataclass(frozen=True)
class CalibrationUncertainty:
    platform_reference: str
    platform_target: str
    method: str
    intercept_mw: BootstrapInterval | None
    slope: BootstrapInterval | None
    validation_bias_mw: BootstrapInterval | None
    validation_mae_mw: BootstrapInterval | None
    validation_rmse_mw: BootstrapInterval | None
    successful_replicates: int
    rejected_replicates: int
    training_date_count: int
    validation_date_count: int
    resampling_unit: str = "UTC_date_block"


@dataclass(frozen=True)
class FRPComparisonUncertainty:
    platform_a: str
    platform_b: str
    mean_difference_mw: BootstrapInterval
    mean_relative_difference: BootstrapInterval | None
    support_unit_count: int
    date_count: int
    resampling_unit: str = "UTC_date_block"


@dataclass(frozen=True)
class Phase06UncertaintyResult:
    calibration_uncertainties: tuple[CalibrationUncertainty, ...]
    comparison_uncertainties: tuple[FRPComparisonUncertainty, ...]
    warnings: tuple[str, ...]
