from dataclasses import dataclass
import math


@dataclass(frozen=True)
class SpatialSupportConfig:
    grid_resolution_km: float
    projection_crs: str = "EPSG:8857"

    def __post_init__(self):
        if not math.isfinite(self.grid_resolution_km):
            raise ValueError("Grid resolution must be finite")
        if self.grid_resolution_km <= 0:
            raise ValueError("Grid resolution must be positive")
        if self.projection_crs != "EPSG:8857":
            raise ValueError("Phase 6 currently requires global EPSG:8857")


@dataclass(frozen=True)
class TemporalSupportConfig:
    max_group_span_minutes: float

    def __post_init__(self):
        if not math.isfinite(self.max_group_span_minutes):
            raise ValueError("Temporal span must be finite")
        if self.max_group_span_minutes <= 0:
            raise ValueError("Temporal span must be positive")


DEFAULT_SPATIAL_GRID_RESOLUTIONS_KM = (0.5, 1.0, 2.0)
DEFAULT_TEMPORAL_GROUP_SPANS_MINUTES = (5.0, 15.0, 30.0)

REFERENCE_SPATIAL_SUPPORT = SpatialSupportConfig(1.0)
REFERENCE_TEMPORAL_SUPPORT = TemporalSupportConfig(15.0)


def build_spatial_support_experiments():
    return tuple(
        SpatialSupportConfig(resolution)
        for resolution in DEFAULT_SPATIAL_GRID_RESOLUTIONS_KM
    )


def build_temporal_support_experiments():
    return tuple(
        TemporalSupportConfig(span)
        for span in DEFAULT_TEMPORAL_GROUP_SPANS_MINUTES
    )
