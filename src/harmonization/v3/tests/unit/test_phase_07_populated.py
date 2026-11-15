from datetime import date, datetime, timezone
from types import SimpleNamespace

from harmonization.v3.contracts.observation import ObservationQCResult
from harmonization.v3.contracts.correspondence import Phase04AResult
from harmonization.v3.phases.phase_02_footprint_construction import run_phase_02
from harmonization.v3.phases.phase_04_correspondence.phase_04b_daily_activity import (
    run_phase_04b,
)
from harmonization.v3.phases.phase_07_output_generation.orchestrator import (
    build_phase_07_outputs,
)


def make_qc(detection_id, platform, longitude, frp_mw, brightness_1, brightness_2):
    observation = SimpleNamespace(
        detection_id=detection_id,
        platform=platform,
        latitude=34.0,
        longitude=longitude,
        acquisition_time_utc=datetime(
            2025, 7, 1, 10, 0, tzinfo=timezone.utc
        ),
        scan_km=1.0,
        track_km=1.0,
        frp_mw=frp_mw,
        brightness_native=brightness_1 if platform.startswith("MODIS") else None,
        bright_t31=brightness_2 if platform.startswith("MODIS") else None,
        bright_ti4=brightness_1 if platform.startswith("VIIRS") else None,
        bright_ti5=brightness_2 if platform.startswith("VIIRS") else None,
    )

    return ObservationQCResult(
        observation=observation,
        eligible_for_spatial_matching=True,
        eligible_for_frp_analysis=True,
        qc_issues=(),
        qc_warnings=(),
    )


def make_phase06_result():
    support_date = date(2025, 7, 1)

    aggregate_a = SimpleNamespace(
        support_unit_id="FRPS-test",
        spatial_cell_id="CELL-test",
        temporal_group_id="GROUP-test",
        support_date_utc=support_date,
        platform="MODIS_TERRA",
        observation_count=1,
        frp_mean_mw=10.0,
        frp_median_mw=10.0,
        frp_min_mw=10.0,
        frp_max_mw=10.0,
    )

    aggregate_b = SimpleNamespace(
        support_unit_id="FRPS-test",
        spatial_cell_id="CELL-test",
        temporal_group_id="GROUP-test",
        support_date_utc=support_date,
        platform="VIIRS_NOAA20",
        observation_count=1,
        frp_mean_mw=20.0,
        frp_median_mw=20.0,
        frp_min_mw=20.0,
        frp_max_mw=20.0,
    )

    comparison = SimpleNamespace(
        support_unit_id="FRPS-test",
        platform_a="MODIS_TERRA",
        platform_b="VIIRS_NOAA20",
        frp_a_mw=10.0,
        frp_b_mw=20.0,
        difference_mw=10.0,
        relative_difference=1.0,
    )

    experiment = SimpleNamespace(
        experiment_id="FRP-TEST-001",
        grid_resolution_km=1.0,
        max_group_span_minutes=15.0,
        sensor_aggregates=(aggregate_a, aggregate_b),
        comparisons=(comparison,),
    )

    return SimpleNamespace(experiments=(experiment,), warnings=())


def test_orchestrator_assembles_populated_harmonization_outputs():
    qc_results = (
        make_qc(
            "TERRA-001", "MODIS_TERRA", -5.0000, 10.0, 320.0, 290.0
        ),
        make_qc(
            "NOAA20-001", "VIIRS_NOAA20", -5.0010, 20.0, 330.0, 300.0
        ),
    )

    phase02_result = run_phase_02(qc_results)

    phase04b_result = run_phase_04b(
        phase02_result,
        distance_thresholds_km=(1.0,),
    )

    result = build_phase_07_outputs(
        observations=qc_results,
        phase02_result=phase02_result,
        phase04a_result=Phase04AResult(evaluations=()),
        phase04b_result=phase04b_result,
        phase06_result=make_phase06_result(),
        run_id="run_populated_001",
        algorithm_version="3.0.0",
        config_id="integration_test",
        started_at_utc=datetime(
            2026, 11, 14, 10, 0, tzinfo=timezone.utc
        ),
        finished_at_utc=datetime(
            2026, 11, 14, 10, 1, tzinfo=timezone.utc
        ),
        status="success",
    )

    assert result.table_count == 7

    assert len(result.tables["harm_correspondence_edges"]) == 0
    assert len(result.tables["harm_correspondence_summary"]) == 0

    clusters = result.tables["harm_activity_clusters"]
    assert len(clusters) == 1
    assert clusters[0]["member_count"] == 2
    assert clusters[0]["terra_count"] == 1
    assert clusters[0]["noaa20_count"] == 1
    assert clusters[0]["sensor_count"] == 2
    assert clusters[0]["cluster_area_km2"] is None

    members = result.tables["harm_cluster_members"]
    assert len(members) == 2
    assert {row["detection_id"] for row in members} == {
        "TERRA-001",
        "NOAA20-001",
    }

    daily = result.tables["harm_sensor_activity_daily"]
    assert len(daily) == 2

    daily_by_platform = {row["platform"]: row for row in daily}
    assert daily_by_platform["MODIS_TERRA"]["detection_count"] == 1
    assert daily_by_platform["MODIS_TERRA"]["frp_sum_mw"] == 10.0
    assert daily_by_platform["VIIRS_NOAA20"]["detection_count"] == 1
    assert daily_by_platform["VIIRS_NOAA20"]["frp_sum_mw"] == 20.0

    frp = result.tables["harm_frp_comparisons"]
    assert len(frp) == 1
    assert frp[0]["frp_a_mw"] == 10.0
    assert frp[0]["frp_b_mw"] == 20.0
    assert frp[0]["comparison_eligibility"] == "eligible_common_support"

    metadata = result.tables["harm_run_metadata"][0]
    assert metadata["input_count"] == 2
    assert metadata["candidate_count"] == 0
    assert metadata["activity_cluster_count"] == 1
    assert metadata["status"] == "success"


def test_populated_outputs_write_to_parquet_and_normalize_timestamps(tmp_path):
    import duckdb
    from datetime import timedelta

    from harmonization.v3.storage.parquet_writer import (
        write_phase_07_parquet,
    )

    qc_results = (
        make_qc(
            "TERRA-001", "MODIS_TERRA", -5.0000, 10.0, 320.0, 290.0
        ),
        make_qc(
            "NOAA20-001", "VIIRS_NOAA20", -5.0010, 20.0, 330.0, 300.0
        ),
    )

    phase02_result = run_phase_02(qc_results)
    phase04b_result = run_phase_04b(
        phase02_result,
        distance_thresholds_km=(1.0,),
    )

    result = build_phase_07_outputs(
        observations=qc_results,
        phase02_result=phase02_result,
        phase04a_result=Phase04AResult(evaluations=()),
        phase04b_result=phase04b_result,
        phase06_result=make_phase06_result(),
        run_id="parquet_populated_test",
        algorithm_version="3.0.0",
        config_id="integration_test",
        started_at_utc=datetime(
            2026, 11, 14, 10, 0, tzinfo=timezone.utc
        ),
        finished_at_utc=datetime(
            2026, 11, 14, 10, 1, tzinfo=timezone.utc
        ),
        status="success",
    )

    # Equivalent instants expressed in UTC+02:00.
    metadata = result.tables["harm_run_metadata"][0]
    metadata["started_at_utc"] = datetime(
        2026, 11, 14, 12, 0,
        tzinfo=timezone(timedelta(hours=2)),
    )
    metadata["finished_at_utc"] = datetime(
        2026, 11, 14, 12, 1,
        tzinfo=timezone(timedelta(hours=2)),
    )

    paths = write_phase_07_parquet(
        result,
        tmp_path,
        "parquet_populated_test",
    )

    assert len(paths) == 7
    assert all(path.is_file() for path in paths.values())

    connection = duckdb.connect(":memory:")

    try:
        def read_count(table_name):
            path = str(paths[table_name]).replace("'", "''")
            return connection.execute(
                f"SELECT COUNT(*) FROM read_parquet('{path}')"
            ).fetchone()[0]

        assert read_count("harm_activity_clusters") == 1
        assert read_count("harm_cluster_members") == 2
        assert read_count("harm_sensor_activity_daily") == 2
        assert read_count("harm_frp_comparisons") == 1
        assert read_count("harm_correspondence_edges") == 0
        assert read_count("harm_correspondence_summary") == 0
        assert read_count("harm_run_metadata") == 1

        metadata_path = str(
            paths["harm_run_metadata"]
        ).replace("'", "''")

        stored = connection.execute(
            f"""
            SELECT started_at_utc, finished_at_utc
            FROM read_parquet('{metadata_path}')
            """
        ).fetchone()

        assert stored[0] == datetime(2026, 11, 14, 10, 0)
        assert stored[1] == datetime(2026, 11, 14, 10, 1)

        frp_path = str(
            paths["harm_frp_comparisons"]
        ).replace("'", "''")

        frp_values = connection.execute(
            f"""
            SELECT frp_a_mw, frp_b_mw, count_a, count_b
            FROM read_parquet('{frp_path}')
            """
        ).fetchone()

        assert frp_values == (10.0, 20.0, 1, 1)

    finally:
        connection.close()
