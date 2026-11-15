import math

from .output_validation import validate_output_rows


def build_frp_comparisons(phase_06_result, run_id: str) -> list[dict]:
    """
    Build dashboard FRP comparison rows from all Phase 6 experiments.

    Native FRP values and observation counts are preserved.
    Time gaps and brightness summaries remain NULL because Phase 6
    does not currently calculate those metrics.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")

    experiments = getattr(phase_06_result, "experiments", None)

    if experiments is None:
        raise TypeError("Expected a Phase06WorkflowResult with experiments")

    rows = []
    seen_rows = set()

    for experiment in experiments:
        grid_resolution = experiment.grid_resolution_km
        temporal_window = experiment.max_group_span_minutes

        if (
            not isinstance(grid_resolution, (int, float))
            or not math.isfinite(grid_resolution)
            or grid_resolution <= 0
        ):
            raise ValueError("Invalid Phase 6 spatial grid resolution")

        if (
            not isinstance(temporal_window, (int, float))
            or not math.isfinite(temporal_window)
            or temporal_window <= 0
        ):
            raise ValueError("Invalid Phase 6 temporal window")

        aggregate_index = {}
        support_metadata = {}

        for aggregate in experiment.sensor_aggregates:
            support_id = aggregate.support_unit_id
            platform = aggregate.platform
            identity = (support_id, platform)

            if identity in aggregate_index:
                raise ValueError(
                    f"Duplicate FRP aggregate for support/platform: {identity}"
                )

            if not isinstance(aggregate.observation_count, int):
                raise ValueError(
                    f"Invalid observation count for {identity}"
                )

            if aggregate.observation_count <= 0:
                raise ValueError(
                    f"Non-positive observation count for {identity}"
                )

            metadata = (
                aggregate.support_date_utc,
                aggregate.spatial_cell_id,
                aggregate.temporal_group_id,
            )

            previous = support_metadata.setdefault(support_id, metadata)

            if previous != metadata:
                raise ValueError(
                    f"Inconsistent support metadata: {support_id}"
                )

            if (
                not isinstance(aggregate.frp_mean_mw, (int, float))
                or not math.isfinite(aggregate.frp_mean_mw)
                or aggregate.frp_mean_mw < 0
            ):
                raise ValueError(
                    f"Invalid mean FRP for support/platform: {identity}"
                )

            aggregate_index[identity] = aggregate

        for comparison in experiment.comparisons:
            support_id = comparison.support_unit_id

            identity_a = (support_id, comparison.platform_a)
            identity_b = (support_id, comparison.platform_b)

            aggregate_a = aggregate_index.get(identity_a)
            aggregate_b = aggregate_index.get(identity_b)

            if aggregate_a is None or aggregate_b is None:
                raise ValueError(
                    "FRP comparison has no corresponding sensor aggregate: "
                    f"{identity_a}, {identity_b}"
                )

            if aggregate_a.support_date_utc != aggregate_b.support_date_utc:
                raise ValueError(
                    f"Date mismatch between sensor aggregates: {support_id}"
                )

            if not math.isclose(
                float(comparison.frp_a_mw),
                float(aggregate_a.frp_mean_mw),
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    f"Platform A FRP does not match its aggregate: {support_id}"
                )

            if not math.isclose(
                float(comparison.frp_b_mw),
                float(aggregate_b.frp_mean_mw),
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise ValueError(
                    f"Platform B FRP does not match its aggregate: {support_id}"
                )

            row = {
                "support_id": support_id,
                "date_utc": aggregate_a.support_date_utc,
                "spatial_scale_km": float(grid_resolution),
                "temporal_window_minutes": float(temporal_window),
                "platform_a": comparison.platform_a,
                "platform_b": comparison.platform_b,
                "frp_a_mw": float(comparison.frp_a_mw),
                "frp_b_mw": float(comparison.frp_b_mw),
                "count_a": aggregate_a.observation_count,
                "count_b": aggregate_b.observation_count,

                # These metrics are not calculated by Phase 6.
                "time_gap_minutes": None,
                "brightness_summary_a": None,
                "brightness_summary_b": None,

                # This indicates a native-FRP comparison on common support.
                # It does not mean the detections are confirmed matches.
                "comparison_eligibility": "eligible_common_support",
                "run_id": run_id,
            }

            row_identity = (
                row["support_id"],
                row["spatial_scale_km"],
                row["temporal_window_minutes"],
                row["platform_a"],
                row["platform_b"],
            )

            if row_identity in seen_rows:
                raise ValueError(
                    f"Duplicate FRP comparison output: {row_identity}"
                )

            seen_rows.add(row_identity)
            rows.append(row)

    validate_output_rows("harm_frp_comparisons", rows)

    return rows
