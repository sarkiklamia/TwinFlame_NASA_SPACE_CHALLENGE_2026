from dataclasses import dataclass
from datetime import datetime
from collections.abc import Iterable
from typing import Any

from .schemas import OUTPUT_SCHEMAS
from .output_validation import validate_output_rows
from .correspondence_outputs import (
    build_correspondence_edges,
    build_correspondence_summary,
)
from .activity_outputs import (
    build_activity_clusters,
    build_cluster_members,
)
from .daily_metrics import build_sensor_activity_daily
from .frp_outputs import build_frp_comparisons
from .run_metadata import build_run_metadata


@dataclass(frozen=True)
class Phase07OutputResult:
    tables: dict[str, tuple[dict[str, Any], ...]]

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def total_row_count(self) -> int:
        return sum(len(rows) for rows in self.tables.values())


def build_phase_07_outputs(
    *,
    observations: Iterable[Any],
    phase02_result: Any,
    phase04a_result: Any,
    phase04b_result: Any,
    phase06_result: Any,
    run_id: str,
    algorithm_version: str,
    config_id: str,
    started_at_utc: datetime,
    status: str,
    finished_at_utc: datetime | None = None,
    failed_stage: str | None = None,
    error_summary: str | None = None,
) -> Phase07OutputResult:
    """
    Assemble and validate the seven dashboard-facing Phase 7 outputs.

    This function does not rerun earlier phases, write files, or export
    the raw unified detection dataset.
    """
    observation_records = tuple(observations)

    # Correspondence outputs
    correspondence_edges = build_correspondence_edges(
        phase04a_result,
        run_id,
    )
    correspondence_summary = build_correspondence_summary(
        phase04a_result,
        observation_records,
        run_id,
    )

    # Daily activity-cluster outputs
    activity_clusters = build_activity_clusters(
        phase04b_result,
        phase02_result,
        run_id,
    )
    cluster_members = build_cluster_members(
        phase04b_result,
        run_id,
    )

    # Daily sensor metrics
    sensor_activity_daily = build_sensor_activity_daily(
        observation_records,
        run_id,
    )

    # Common-support FRP comparisons
    frp_comparisons = build_frp_comparisons(
        phase06_result,
        run_id,
    )

    # Run metadata
    run_metadata = build_run_metadata(
        run_id=run_id,
        algorithm_version=algorithm_version,
        config_id=config_id,
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        status=status,
        input_count=len(observation_records),
        candidate_count=len(phase04a_result.evaluations),
        correspondence_edge_count=len(correspondence_edges),
        activity_cluster_count=len(activity_clusters),
        failed_stage=failed_stage,
        error_summary=error_summary,
    )

    tables = {
        "harm_correspondence_edges": tuple(correspondence_edges),
        "harm_activity_clusters": tuple(activity_clusters),
        "harm_cluster_members": tuple(cluster_members),
        "harm_sensor_activity_daily": tuple(sensor_activity_daily),
        "harm_correspondence_summary": tuple(correspondence_summary),
        "harm_frp_comparisons": tuple(frp_comparisons),
        "harm_run_metadata": (run_metadata,),
    }

    # Ensure the orchestrator produces exactly the agreed seven tables.
    expected_tables = set(OUTPUT_SCHEMAS)
    actual_tables = set(tables)

    if actual_tables != expected_tables:
        missing = sorted(expected_tables - actual_tables)
        unexpected = sorted(actual_tables - expected_tables)
        raise ValueError(
            f"Phase 7 table set mismatch. "
            f"Missing: {missing}; unexpected: {unexpected}"
        )

    # Validate every table at the orchestration boundary.
    for table_name, rows in tables.items():
        validate_output_rows(table_name, rows)

    return Phase07OutputResult(tables=tables)
