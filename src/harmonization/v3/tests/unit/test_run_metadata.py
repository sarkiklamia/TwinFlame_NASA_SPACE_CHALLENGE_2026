from datetime import datetime, timedelta, timezone

import pytest

from src.harmonization.v3.phases.phase_07_output_generation.run_metadata import (
    build_run_metadata,
)


START = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
FINISH = datetime(2026, 11, 14, 10, 2, 30, tzinfo=timezone.utc)


def make_metadata(**overrides):
    values = {
        "run_id": "run_test_001",
        "algorithm_version": "v3",
        "config_id": "config_test_001",
        "started_at_utc": START,
        "finished_at_utc": FINISH,
        "status": "success",
        "input_count": 100,
        "candidate_count": 40,
        "correspondence_edge_count": 40,
        "activity_cluster_count": 12,
    }
    values.update(overrides)
    return build_run_metadata(**values)


def test_successful_run_metadata_calculates_duration():
    row = make_metadata()

    assert row["status"] == "success"
    assert row["duration_seconds"] == 150.0
    assert row["finished_at_utc"] == FINISH
    assert row["input_count"] == 100
    assert row["candidate_count"] == 40
    assert row["correspondence_edge_count"] == 40
    assert row["activity_cluster_count"] == 12


def test_running_run_has_null_finish_time_and_duration():
    row = make_metadata(
        status="running",
        finished_at_utc=None,
    )

    assert row["status"] == "running"
    assert row["finished_at_utc"] is None
    assert row["duration_seconds"] is None


def test_failed_run_records_failure_details():
    row = make_metadata(
        status="failed",
        failed_stage="phase_04a",
        error_summary="Candidate evaluation failed.",
    )

    assert row["status"] == "failed"
    assert row["failed_stage"] == "phase_04a"
    assert row["error_summary"] == "Candidate evaluation failed."


def test_partial_run_is_supported():
    row = make_metadata(status="partial")

    assert row["status"] == "partial"
    assert row["duration_seconds"] == 150.0


def test_failed_run_requires_failed_stage():
    with pytest.raises(ValueError, match="failed_stage"):
        make_metadata(
            status="failed",
            failed_stage=None,
        )


def test_completed_run_requires_finish_time():
    with pytest.raises(ValueError, match="finished_at_utc"):
        make_metadata(
            status="success",
            finished_at_utc=None,
        )


def test_running_run_rejects_finish_time():
    with pytest.raises(ValueError, match="running run"):
        make_metadata(status="running")


def test_finish_time_cannot_precede_start_time():
    with pytest.raises(ValueError, match="cannot precede"):
        make_metadata(
            finished_at_utc=START - timedelta(seconds=1),
        )


def test_naive_start_time_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        make_metadata(
            started_at_utc=datetime(2026, 11, 14, 10, 0),
        )


def test_non_utc_timestamp_is_rejected():
    non_utc = timezone(timedelta(hours=1))

    with pytest.raises(ValueError, match="expressed in UTC"):
        make_metadata(
            started_at_utc=datetime(2026, 11, 14, 11, 0, tzinfo=non_utc),
        )


def test_negative_counts_are_rejected():
    with pytest.raises(ValueError, match="cannot be negative"):
        make_metadata(input_count=-1)


def test_boolean_counts_are_rejected():
    with pytest.raises(ValueError, match="must be an integer"):
        make_metadata(input_count=True)


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError, match="status must be one of"):
        make_metadata(status="completed")


def test_empty_run_id_is_rejected():
    with pytest.raises(ValueError, match="run_id"):
        make_metadata(run_id="  ")


def test_metadata_contains_exact_schema_columns():
    row = make_metadata()

    expected = {
        "run_id",
        "algorithm_version",
        "config_id",
        "started_at_utc",
        "finished_at_utc",
        "duration_seconds",
        "status",
        "input_count",
        "candidate_count",
        "correspondence_edge_count",
        "activity_cluster_count",
        "failed_stage",
        "error_summary",
    }

    assert set(row) == expected
