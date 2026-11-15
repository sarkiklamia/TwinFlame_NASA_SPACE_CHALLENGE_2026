from datetime import datetime, timezone
from types import SimpleNamespace

from src.harmonization.v3.phases.phase_02_footprint_construction.runner import (
    Phase02Result,
)
from src.harmonization.v3.contracts.correspondence import Phase04AResult
from src.harmonization.v3.contracts.activity import Phase04BResult
from src.harmonization.v3.phases.phase_07_output_generation.orchestrator import (
    build_phase_07_outputs,
)


def test_orchestrator_assembles_all_seven_empty_tables():
    result = build_phase_07_outputs(
        observations=(),
        phase02_result=Phase02Result(results=()),
        phase04a_result=Phase04AResult(evaluations=()),
        phase04b_result=Phase04BResult(
            experiments=(),
            clusters=(),
            memberships=(),
            summaries=(),
        ),
        phase06_result=SimpleNamespace(experiments=()),
        run_id="run_integration_001",
        algorithm_version="3.0.0",
        config_id="test_config",
        started_at_utc=datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc),
        finished_at_utc=datetime(2026, 11, 14, 10, 1, tzinfo=timezone.utc),
        status="success",
    )

    expected_tables = {
        "harm_correspondence_edges",
        "harm_activity_clusters",
        "harm_cluster_members",
        "harm_sensor_activity_daily",
        "harm_correspondence_summary",
        "harm_frp_comparisons",
        "harm_run_metadata",
    }

    assert set(result.tables) == expected_tables
    assert result.table_count == 7
    assert result.total_row_count == 1

    for table_name in expected_tables - {"harm_run_metadata"}:
        assert result.tables[table_name] == ()

    metadata = result.tables["harm_run_metadata"][0]
    assert metadata["run_id"] == "run_integration_001"
    assert metadata["status"] == "success"
    assert metadata["input_count"] == 0
    assert metadata["candidate_count"] == 0
    assert metadata["correspondence_edge_count"] == 0
    assert metadata["activity_cluster_count"] == 0
