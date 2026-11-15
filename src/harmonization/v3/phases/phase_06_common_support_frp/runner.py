from dataclasses import dataclass

from ...contracts.frp import (
    CalibrationResult,
    CommonSupportMembership,
    FRPComparison,
    SensorFRPAggregate,
    SpatialSupportAssignment,
    TemporalSupportMembership,
)
from ...contracts.uncertainty import Phase06UncertaintyResult
from ...config.frp_support import (
    SpatialSupportConfig,
    TemporalSupportConfig,
)
from .spatial_support import assign_spatial_support
from .temporal_support import assign_temporal_support
from .common_support import build_common_support_memberships
from .sensor_aggregation import aggregate_sensor_frp
from .frp_comparison import compare_sensor_frp
from .conditional_calibration import evaluate_conditional_calibrations
from .uncertainty import estimate_phase_06_uncertainty


SPATIAL_RESOLUTIONS_KM = (0.5, 1.0, 2.0)
TEMPORAL_WINDOWS_MINUTES = (5.0, 15.0, 30.0)


@dataclass(frozen=True)
class Phase06ExperimentResult:
    experiment_id: str
    grid_resolution_km: float
    max_group_span_minutes: float
    spatial_assignments: tuple[SpatialSupportAssignment, ...]
    temporal_memberships: tuple[TemporalSupportMembership, ...]
    common_support_memberships: tuple[CommonSupportMembership, ...]
    sensor_aggregates: tuple[SensorFRPAggregate, ...]
    comparisons: tuple[FRPComparison, ...]
    calibration_results: tuple[CalibrationResult, ...]
    uncertainty: Phase06UncertaintyResult


@dataclass(frozen=True)
class Phase06WorkflowResult:
    experiments: tuple[Phase06ExperimentResult, ...]
    warnings: tuple[str, ...]
    intermediate_results_retained: bool = True

    @property
    def experiment_count(self):
        return len(self.experiments)


def _experiment_id(grid_resolution_km, temporal_window_minutes):
    grid = str(grid_resolution_km).replace(".", "p")
    window = str(temporal_window_minutes).replace(".", "p")
    return f"G{grid}km_T{window}min"


def run_phase_06(
    phase02_result,
    n_bootstrap=1000,
    confidence_level=0.95,
    random_seed=42,
    retain_intermediate_results=True,
):
    """
    Run all nine independent common-support FRP experiments.

    Native FRP is preserved. Calibration models are evaluated but
    never automatically selected or applied.

    Set retain_intermediate_results=False to release per-detection spatial,
    temporal, and common-support memberships after each experiment. Only
    sensor aggregates used by a cross-platform comparison remain available
    for the dashboard FRP product.
    """
    if not isinstance(retain_intermediate_results, bool):
        raise ValueError("retain_intermediate_results must be a boolean")

    experiments = []

    for grid_resolution in SPATIAL_RESOLUTIONS_KM:
        spatial_config = SpatialSupportConfig(
            grid_resolution_km=grid_resolution
        )
        spatial_assignments = assign_spatial_support(
            phase02_result,
            spatial_config,
        )
        for temporal_window in TEMPORAL_WINDOWS_MINUTES:
            temporal_config = TemporalSupportConfig(
                max_group_span_minutes=temporal_window
            )

            temporal_memberships = assign_temporal_support(
                phase02_result,
                spatial_assignments,
                temporal_config,
            )

            common_memberships = build_common_support_memberships(
                spatial_assignments,
                temporal_memberships,
            )

            aggregates = aggregate_sensor_frp(
                phase02_result,
                common_memberships,
            )

            comparisons = compare_sensor_frp(aggregates)

            calibrations = evaluate_conditional_calibrations(
                aggregates
            )

            uncertainty = estimate_phase_06_uncertainty(
                aggregates,
                n_bootstrap=n_bootstrap,
                confidence_level=confidence_level,
                random_seed=random_seed,
            )

            if retain_intermediate_results:
                output_aggregates = tuple(aggregates)
            else:
                compared_support_ids = {
                    comparison.support_unit_id
                    for comparison in comparisons
                }
                output_aggregates = tuple(
                    aggregate
                    for aggregate in aggregates
                    if aggregate.support_unit_id in compared_support_ids
                )

            experiments.append(
                Phase06ExperimentResult(
                    experiment_id=_experiment_id(
                        grid_resolution,
                        temporal_window,
                    ),
                    grid_resolution_km=grid_resolution,
                    max_group_span_minutes=temporal_window,
                    spatial_assignments=(
                        tuple(spatial_assignments)
                        if retain_intermediate_results
                        else ()
                    ),
                    temporal_memberships=(
                        tuple(temporal_memberships)
                        if retain_intermediate_results
                        else ()
                    ),
                    common_support_memberships=(
                        tuple(common_memberships)
                        if retain_intermediate_results
                        else ()
                    ),
                    sensor_aggregates=output_aggregates,
                    comparisons=tuple(comparisons),
                    calibration_results=tuple(calibrations),
                    uncertainty=uncertainty,
                )
            )

            if not retain_intermediate_results:
                del temporal_memberships
                del common_memberships
                del aggregates
                del comparisons
                del calibrations
                del uncertainty

    warnings = (
        "The nine support experiments are independent sensitivity experiments; no winning configuration is selected automatically.",
        "Spatial support uses detection-centre assignment, not actual pixel-footprint overlap.",
        "Temporal support uses bounded groups anchored at the earliest observation; it is not exact simultaneous acquisition matching.",
        "FRP remains in native sensor values. Calibration results are evaluations only and are not applied.",
        "Bootstrap intervals quantify date-block sampling variability, not systematic sensor uncertainty.",
        "Real observations and independent validation data are required before drawing scientific conclusions or selecting a configuration.",
    )

    if not retain_intermediate_results:
        warnings += (
            "Per-detection support assignments and unpaired sensor aggregates were released after each experiment; aggregates required to validate cross-platform comparisons were retained.",
        )

    return Phase06WorkflowResult(
        experiments=tuple(experiments),
        warnings=warnings,
        intermediate_results_retained=retain_intermediate_results,
    )
