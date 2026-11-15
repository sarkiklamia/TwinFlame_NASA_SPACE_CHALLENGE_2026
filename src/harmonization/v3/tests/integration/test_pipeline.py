from pathlib import Path

import duckdb
import pytest

from harmonization.v3.config.experiments import build_threshold_experiments
from harmonization.v3.pipeline.orchestrator import (
    PipelineExecutionError,
    run_pipeline,
)


@pytest.fixture
def synthetic_database(tmp_path):
    database = tmp_path / "synthetic_unified.duckdb"
    con = duckdb.connect(str(database))

    con.execute("""
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR,
            id BIGINT,
            source VARCHAR,
            platform VARCHAR,
            latitude FLOAT,
            longitude FLOAT,
            acq_date DATE,
            acq_time VARCHAR,
            confidence_native VARCHAR,
            frp_mw FLOAT,
            brightness FLOAT,
            bright_t31 FLOAT,
            bright_ti4 FLOAT,
            bright_ti5 FLOAT,
            scan_km FLOAT,
            track_km FLOAT,
            daynight VARCHAR
        )
    """)

    con.execute("""
        INSERT INTO UNIFIED_DETECTIONS VALUES
        ('terra-001', 1, 'archive', 'MODIS_TERRA',
         34.1000, -5.2000, DATE '2025-07-01', '1035',
         'nominal', 12.5, 320.0, 295.0,
         NULL, NULL, 1.0, 1.2, 'D'),

        ('terra-002', 2, 'archive', 'MODIS_TERRA',
         34.1000, -5.2000, DATE '2025-07-01', '1036',
         'nominal', 14.0, 322.0, 296.0,
         NULL, NULL, 1.0, 1.2, 'D'),

        ('noaa20-001', 3, 'api', 'VIIRS_NOAA20',
         34.1000, -5.2000, DATE '2025-07-01', '1040',
         'high', 8.0, NULL, NULL,
         340.0, 300.0, 0.4, 0.4, 'D'),

        ('noaa20-002', 4, 'api', 'VIIRS_NOAA20',
         34.1000, -5.2000, DATE '2025-07-01', '1041',
         'high', 9.0, NULL, NULL,
         342.0, 301.0, 0.4, 0.4, 'D')
    """)

    con.close()
    return database


def test_pipeline_runs_all_phases_and_writes_seven_outputs(
    synthetic_database, tmp_path
):
    output_root = tmp_path / "harmonization_outputs"

    experiments = build_threshold_experiments(
        time_thresholds_minutes=(15.0,),
        distance_thresholds_km=(1.0,),
    )

    result = run_pipeline(
        database=str(synthetic_database),
        output_root=output_root,
        experiments=experiments,
        platform_pairs=(("MODIS_TERRA", "VIIRS_NOAA20"),),
        n_bootstrap=20,
        run_id="integration-test-run",
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

    assert result.phase00.audit.row_count == 4
    assert result.phase01.input_count == 4
    assert result.phase02.input_count == 4

    assert len(result.phase03.experiments) == 1
    assert len(result.phase03.candidates) > 0

    assert len(result.phase04a.evaluations) > 0
    assert result.phase04b is not None

    assert result.phase05_status == "skipped_no_reference_data"
    assert set(result.skipped_validation_types) == {
        "candidate_recall",
        "daily_activity",
    }

    assert result.phase06.experiment_count == 9

    assert set(result.phase07.tables) == expected_tables
    assert set(result.parquet_paths) == expected_tables

    for table_name, parquet_path in result.parquet_paths.items():
        assert parquet_path.is_file(), table_name

    con = duckdb.connect(":memory:")

    try:
        row_counts = {}

        for table_name, parquet_path in result.parquet_paths.items():
            row_counts[table_name] = con.execute(
                "SELECT COUNT(*) FROM read_parquet(?)",
                [str(parquet_path)],
            ).fetchone()[0]

        assert row_counts["harm_run_metadata"] == 1
        assert row_counts["harm_sensor_activity_daily"] == 2
        assert row_counts["harm_activity_clusters"] > 0
        assert row_counts["harm_cluster_members"] == 16
        assert row_counts["harm_correspondence_edges"] > 0
        assert row_counts["harm_correspondence_summary"] > 0
        assert row_counts["harm_frp_comparisons"] > 0

        metadata = con.execute(
            """
            SELECT
                status,
                run_id,
                started_at_utc,
                finished_at_utc,
                duration_seconds
            FROM read_parquet(?)
            """,
            [str(result.parquet_paths["harm_run_metadata"])],
        ).fetchone()

        assert metadata[0:2] == ("success", "integration-test-run")
        assert metadata[2] is not None
        assert metadata[3] is not None
        assert metadata[3] >= metadata[2]
        assert metadata[4] is not None
        assert metadata[4] >= 0

        # The in-memory Phase 7 metadata must match the exported metadata.
        in_memory_metadata = result.phase07.tables[
            "harm_run_metadata"
        ][0]

        assert in_memory_metadata["status"] == metadata[0]
        assert in_memory_metadata["run_id"] == metadata[1]
        assert in_memory_metadata["finished_at_utc"] is not None
        assert in_memory_metadata["duration_seconds"] >= 0

    finally:
        con.close()


def test_pipeline_reports_input_failure_stage(tmp_path):
    with pytest.raises(PipelineExecutionError) as error:
        run_pipeline(
            database=str(tmp_path / "missing.duckdb"),
            output_root=tmp_path / "outputs",
            run_id="integration-failure-test",
        )

    assert error.value.run_id == "integration-failure-test"
    assert error.value.failed_stage == "phase_00_input_audit"
    assert isinstance(error.value.__cause__, FileNotFoundError)

