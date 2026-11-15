from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CandidateThresholdExperiment:
    experiment_id: str
    time_threshold_minutes: float
    distance_threshold_km: float

    def __post_init__(self):
        if not self.experiment_id:
            raise ValueError("experiment_id must not be empty")
        if not math.isfinite(self.time_threshold_minutes) or self.time_threshold_minutes <= 0:
            raise ValueError("Time threshold must be finite and positive")
        if not math.isfinite(self.distance_threshold_km) or self.distance_threshold_km <= 0:
            raise ValueError("Distance threshold must be finite and positive")


# User-selected operational candidate threshold. The July sensitivity study
# selected this setting for subsequent harmonization runs.
OPERATIONAL_TIME_THRESHOLD_MINUTES = 240.0
OPERATIONAL_DISTANCE_THRESHOLD_KM = 1.0

# Production defaults are intentionally a single fixed candidate threshold.
DEFAULT_TIME_THRESHOLDS_MINUTES = (OPERATIONAL_TIME_THRESHOLD_MINUTES,)
DEFAULT_DISTANCE_THRESHOLDS_KM = (OPERATIONAL_DISTANCE_THRESHOLD_KM,)

# Retained only for reproducing the July threshold sensitivity study.
CALIBRATION_TIME_THRESHOLDS_MINUTES = (
    5.0, 10.0, 15.0, 30.0, 60.0, 180.0, 240.0,
)

CALIBRATION_DISTANCE_THRESHOLDS_KM = (0.5, 0.85, 1.0, 1.5, 2.0)

# Phase 4B is a separate daily-activity clustering branch. Its production
# default uses the selected 1 km spatial threshold; the sensitivity values
# remain available for reproducing the July calibration run.
DEFAULT_ACTIVITY_DISTANCE_THRESHOLDS_KM = (OPERATIONAL_DISTANCE_THRESHOLD_KM,)
CALIBRATION_ACTIVITY_DISTANCE_THRESHOLDS_KM = (0.5, 0.85, 1.0, 1.5)
