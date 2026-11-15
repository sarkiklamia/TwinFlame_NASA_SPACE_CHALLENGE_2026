from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    data_type: str
    nullable: bool = True


# Each tuple preserves the exact output column order.
OUTPUT_SCHEMAS: dict[str, tuple[ColumnSpec, ...]] = {

    # 1. Cross-sensor candidate-pair evaluations
    "harm_correspondence_edges": (
        ColumnSpec("correspondence_edge_id", "VARCHAR", False),
        ColumnSpec("detection_id_a", "VARCHAR", False),
        ColumnSpec("detection_id_b", "VARCHAR", False),
        ColumnSpec("platform_a", "VARCHAR", False),
        ColumnSpec("platform_b", "VARCHAR", False),
        ColumnSpec("experiment_id", "VARCHAR", False),
        ColumnSpec("time_threshold_minutes", "DOUBLE", False),
        ColumnSpec("distance_threshold_km", "DOUBLE", False),
        ColumnSpec("time_difference_minutes", "DOUBLE", False),
        ColumnSpec("centre_distance_km", "DOUBLE", False),
        ColumnSpec("intersection_area_km2", "DOUBLE"),
          ColumnSpec("union_area_km2", "DOUBLE"),
        ColumnSpec("iou", "DOUBLE"),
        ColumnSpec("containment_a", "DOUBLE"),
        ColumnSpec("containment_b", "DOUBLE"),
          ColumnSpec("minimum_boundary_distance_km", "DOUBLE"),
        ColumnSpec("normalized_centre_distance", "DOUBLE"),
          ColumnSpec("metric_method", "VARCHAR"),
        ColumnSpec("decision_class", "VARCHAR", False),
        ColumnSpec("decision_reason", "VARCHAR"),
        ColumnSpec("geometry_quality", "VARCHAR"),
        ColumnSpec("run_id", "VARCHAR", False),
    ),

    # 2. Daily spatial activity clusters
    "harm_activity_clusters": (
        ColumnSpec("activity_cluster_id", "VARCHAR", False),
        ColumnSpec("activity_date_utc", "DATE", False),
        ColumnSpec("centroid_latitude", "DOUBLE"),
        ColumnSpec("centroid_longitude", "DOUBLE"),
        ColumnSpec("member_count", "INTEGER", False),
        ColumnSpec("terra_count", "INTEGER", False),
        ColumnSpec("aqua_count", "INTEGER", False),
        ColumnSpec("noaa20_count", "INTEGER", False),
        ColumnSpec("noaa21_count", "INTEGER", False),
        ColumnSpec("sensor_count", "INTEGER", False),
        ColumnSpec("start_time_utc", "TIMESTAMP"),
        ColumnSpec("end_time_utc", "TIMESTAMP"),
        ColumnSpec("cluster_extent_km", "DOUBLE"),
        ColumnSpec("cluster_area_km2", "DOUBLE"),
        ColumnSpec("cluster_method", "VARCHAR", False),
        ColumnSpec("run_id", "VARCHAR", False),
    ),

    # 3. Detection-to-cluster membership
    "harm_cluster_members": (
        ColumnSpec("activity_cluster_id", "VARCHAR", False),
        ColumnSpec("detection_id", "VARCHAR", False),
        ColumnSpec("platform", "VARCHAR", False),
        ColumnSpec("membership_method", "VARCHAR", False),
        ColumnSpec("membership_distance_km", "DOUBLE"),
        ColumnSpec("membership_quality", "VARCHAR"),
        ColumnSpec("run_id", "VARCHAR", False),
    ),

    # 4. Daily statistics for each sensor
    "harm_sensor_activity_daily": (
        ColumnSpec("date_utc", "DATE", False),
        ColumnSpec("platform", "VARCHAR", False),
        ColumnSpec("detection_count", "INTEGER", False),
        ColumnSpec("matching_eligible_count", "INTEGER", False),
        ColumnSpec("frp_eligible_count", "INTEGER", False),
        ColumnSpec("frp_sum_mw", "DOUBLE"),
        ColumnSpec("frp_mean_mw", "DOUBLE"),
        ColumnSpec("frp_median_mw", "DOUBLE"),
        ColumnSpec("brightness_band_1_mean_k", "DOUBLE"),
        ColumnSpec("brightness_band_1_median_k", "DOUBLE"),
        ColumnSpec("brightness_band_2_mean_k", "DOUBLE"),
        ColumnSpec("brightness_band_2_median_k", "DOUBLE"),
        ColumnSpec("run_id", "VARCHAR", False),
    ),

    # 5. Correspondence statistics per date, pair, and experiment
    "harm_correspondence_summary": (
        ColumnSpec("date_utc", "DATE", False),
        ColumnSpec("platform_pair", "VARCHAR", False),
        ColumnSpec("experiment_id", "VARCHAR", False),
        ColumnSpec("time_threshold_minutes", "DOUBLE", False),
        ColumnSpec("distance_threshold_km", "DOUBLE", False),
        ColumnSpec("candidate_count", "INTEGER", False),
        ColumnSpec("strong_count", "INTEGER", False),
        ColumnSpec("possible_count", "INTEGER", False),
        ColumnSpec("rejected_count", "INTEGER", False),
        ColumnSpec("insufficient_geometry_count", "INTEGER", False),
        ColumnSpec("mean_time_difference_minutes", "DOUBLE"),
        ColumnSpec("median_time_difference_minutes", "DOUBLE"),
        ColumnSpec("mean_iou", "DOUBLE"),
        ColumnSpec("run_id", "VARCHAR", False),
    ),

    # 6. FRP comparisons on common spatial-temporal support
    "harm_frp_comparisons": (
        ColumnSpec("support_id", "VARCHAR", False),
        ColumnSpec("date_utc", "DATE", False),
        ColumnSpec("spatial_scale_km", "DOUBLE", False),
        ColumnSpec("temporal_window_minutes", "DOUBLE", False),
        ColumnSpec("platform_a", "VARCHAR", False),
        ColumnSpec("platform_b", "VARCHAR", False),
        ColumnSpec("frp_a_mw", "DOUBLE", False),
        ColumnSpec("frp_b_mw", "DOUBLE", False),
        ColumnSpec("count_a", "INTEGER", False),
        ColumnSpec("count_b", "INTEGER", False),
        ColumnSpec("time_gap_minutes", "DOUBLE"),
        ColumnSpec("brightness_summary_a", "DOUBLE"),
        ColumnSpec("brightness_summary_b", "DOUBLE"),
        ColumnSpec("comparison_eligibility", "VARCHAR", False),
        ColumnSpec("run_id", "VARCHAR", False),
    ),

    # 7. Processing-run provenance and status
    "harm_run_metadata": (
        ColumnSpec("run_id", "VARCHAR", False),
        ColumnSpec("algorithm_version", "VARCHAR", False),
        ColumnSpec("config_id", "VARCHAR", False),
        ColumnSpec("started_at_utc", "TIMESTAMP", False),
        ColumnSpec("finished_at_utc", "TIMESTAMP"),
        ColumnSpec("duration_seconds", "DOUBLE"),
        ColumnSpec("status", "VARCHAR", False),
        ColumnSpec("input_count", "BIGINT", False),
        ColumnSpec("candidate_count", "BIGINT", False),
        ColumnSpec("correspondence_edge_count", "BIGINT", False),
        ColumnSpec("activity_cluster_count", "BIGINT", False),
        ColumnSpec("failed_stage", "VARCHAR"),
        ColumnSpec("error_summary", "VARCHAR"),
    ),
}


def get_output_schema(table_name: str) -> tuple[ColumnSpec, ...]:
    """Return the ordered schema for one output table."""
    try:
        return OUTPUT_SCHEMAS[table_name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown harmonization output table: {table_name}"
        ) from exc


def get_column_names(table_name: str) -> tuple[str, ...]:
    """Return ordered column names for one output table."""
    return tuple(
        column.name for column in get_output_schema(table_name)
    )


