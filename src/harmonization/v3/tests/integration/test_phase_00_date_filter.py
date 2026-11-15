from datetime import datetime, timezone, timedelta

import duckdb
import pytest

from harmonization.v3.phases.phase_00_input_audit.runner import (
    run_phase_00,
    run_phase_00_streaming,
)
from harmonization.v3.storage.input_reader import (
    iter_unified_detections,
    load_unified_detections,
)


@pytest.fixture
def current_schema_database(tmp_path):
    path = tmp_path / "current_schema.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("""
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id BIGINT,
            file_id BIGINT,
            processing_id BIGINT,
            ingested_at TIMESTAMP,
            processing_level VARCHAR,
            source VARCHAR,
            platform VARCHAR,
            sensor VARCHAR,
            latitude DOUBLE,
            longitude DOUBLE,
            acquisition_time_utc TIMESTAMP,
            confidence_native VARCHAR,
            confidence_class VARCHAR,
            frp_mw DOUBLE,
            brightness_native DOUBLE,
            bright_t31 DOUBLE,
            bright_ti4 DOUBLE,
            bright_ti5 DOUBLE,
            scan DOUBLE,
            track DOUBLE,
            daynight VARCHAR,
            product_version VARCHAR,
            quality_flags VARCHAR
        )
    """)
    connection.execute("""
        INSERT INTO UNIFIED_DETECTIONS VALUES
        (1, 1, 1, TIMESTAMP '2026-07-01 01:00:00', 'L2', 'C2_SAMPLE',
         'MODIS_TERRA', 'MODIS', 10, 20, TIMESTAMP '2026-06-30 23:59:59',
         'n', 'nominal', 1, 300, 290, NULL, NULL, 1, 1, 'D', '61.03', NULL),
        (2, 1, 1, TIMESTAMP '2026-07-01 01:00:00', 'L2', 'C2_SAMPLE',
         'MODIS_TERRA', 'MODIS', 10, 20, TIMESTAMP '2026-07-01 00:00:00',
         'n', 'nominal', 2, 301, 291, NULL, NULL, 1, 1, 'D', '61.03', NULL),
        (3, 1, 1, TIMESTAMP '2026-08-01 01:00:00', 'L2', 'C2_SAMPLE',
         'VIIRS_NOAA20', 'VIIRS', 11, 21, TIMESTAMP '2026-07-31 23:59:59',
         'n', 'nominal', 3, 302, 292, NULL, NULL, 0.4, 0.4, 'D', '2.0', NULL),
        (4, 1, 1, TIMESTAMP '2026-08-01 01:00:00', 'L2', 'C2_SAMPLE',
         'VIIRS_NOAA20', 'VIIRS', 11, 21, TIMESTAMP '2026-08-01 00:00:00',
         'n', 'nominal', 4, 303, 293, NULL, NULL, 0.4, 0.4, 'D', '2.0', NULL)
    """)
    connection.close()
    return path


def july_bounds():
    return (
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


def test_loader_uses_inclusive_start_and_exclusive_end(current_schema_database):
    start, end = july_bounds()
    rows = load_unified_detections(
        current_schema_database,
        acquisition_start_utc=start,
        acquisition_end_utc_exclusive=end,
    )
    assert {row["detection_id"] for row in rows} == {2, 3}


def test_streaming_reader_applies_date_and_platform_filters(current_schema_database):
    start, end = july_bounds()
    rows = list(iter_unified_detections(
        current_schema_database,
        platforms="NOAA20",
        batch_size=1,
        acquisition_start_utc=start,
        acquisition_end_utc_exclusive=end,
    ))
    assert [row["detection_id"] for row in rows] == [3]


def test_phase_00_streaming_audit_matches_filtered_rows(current_schema_database):
    start, end = july_bounds()
    result = run_phase_00_streaming(
        str(current_schema_database),
        batch_size=1,
        acquisition_start_utc=start,
        acquisition_end_utc_exclusive=end,
    )
    assert result.mapped_record_count == 2
    assert result.audit.row_count == 2
    assert result.audit.platform_counts == {
        "MODIS_TERRA": 1,
        "VIIRS_NOAA20": 1,
    }


def test_phase_00_materialized_sample_uses_same_date_filter(current_schema_database):
    start, end = july_bounds()
    result = run_phase_00(
        str(current_schema_database),
        acquisition_start_utc=start,
        acquisition_end_utc_exclusive=end,
    )
    assert result.audit.row_count == 2
    assert {row.detection_id for row in result.observations} == {"2", "3"}


def test_date_filter_normalizes_timezone_offsets(current_schema_database):
    start = datetime(2026, 7, 1, 1, tzinfo=timezone(timedelta(hours=1)))
    end = datetime(2026, 8, 1, tzinfo=timezone.utc)
    rows = load_unified_detections(
        current_schema_database,
        acquisition_start_utc=start,
        acquisition_end_utc_exclusive=end,
    )
    assert {row["detection_id"] for row in rows} == {2, 3}


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (datetime(2026, 7, 1), datetime(2026, 8, 1, tzinfo=timezone.utc), "timezone-aware"),
        (datetime(2026, 8, 1, tzinfo=timezone.utc), datetime(2026, 7, 1, tzinfo=timezone.utc), "earlier than"),
    ],
)
def test_invalid_date_ranges_are_rejected(current_schema_database, start, end, message):
    with pytest.raises(ValueError, match=message):
        load_unified_detections(
            current_schema_database,
            acquisition_start_utc=start,
            acquisition_end_utc_exclusive=end,
        )
