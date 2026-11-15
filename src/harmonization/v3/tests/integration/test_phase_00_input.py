from datetime import date

import duckdb
import pytest

from harmonization.v3.storage.input_reader import load_unified_detections
from harmonization.v3.phases.phase_00_input_audit.runner import run_phase_00


@pytest.fixture
def sample_database(tmp_path):
    path = tmp_path / "unified_test.duckdb"
    con = duckdb.connect(str(path))

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
         34.1, -5.2, DATE '2025-07-01', '1035',
         'nominal', 12.5, 320.0, 295.0,
         NULL, NULL, 1.0, 1.2, 'D'),

        ('noaa20-001', 2, 'api', 'VIIRS_NOAA20',
         34.2, -5.3, DATE '2025-07-01', '1040',
         'high', 8.0, NULL, NULL,
         340.0, 300.0, 0.4, 0.4, 'D')
    """)

    con.close()
    return path


def test_loader_reads_rows(sample_database):
    rows = load_unified_detections(sample_database)
    assert len(rows) == 2
    assert rows[0]["detection_id"] == "terra-001"
    assert rows[0]["acq_date"] == date(2025, 7, 1)
    assert rows[0]["frp_mw"] == pytest.approx(12.5)


def test_platform_filter_alias(sample_database):
    rows = load_unified_detections(
        sample_database, platforms="NOAA20"
    )
    assert len(rows) == 1
    assert rows[0]["platform"] == "VIIRS_NOAA20"


def test_invalid_table_identifier(sample_database):
    with pytest.raises(ValueError, match="Invalid table identifier"):
        load_unified_detections(
            sample_database,
            table="UNIFIED_DETECTIONS; DROP TABLE x"
        )


def test_phase_00_end_to_end(sample_database):
    result = run_phase_00(str(sample_database))

    assert result.audit.row_count == 2
    assert len(result.observations) == 2
    assert result.observations[0].platform == "MODIS_TERRA"
    assert result.observations[0].frp_mw == pytest.approx(12.5)
    assert result.observations[0].acquisition_time_utc.isoformat() == (
        "2025-07-01T10:35:00+00:00"
    )


def test_missing_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_unified_detections(tmp_path / "missing.duckdb")
