from datetime import datetime, timezone

import duckdb
import pytest

from harmonization.v3.phases.phase_07_output_generation.run_metadata import (
    build_run_metadata,
)
from harmonization.v3.phases.phase_07_output_generation.schemas import (
    OUTPUT_SCHEMAS,
)
from harmonization.v3.storage import failure_writer
from harmonization.v3.storage.failure_writer import (
    write_failed_run_metadata,
)


def make_failed_metadata(run_id="failure_run_001"):
    started_at = datetime(2026, 11, 14, 10, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 11, 14, 10, 5, tzinfo=timezone.utc)

    return build_run_metadata(
        run_id=run_id,
        algorithm_version="v3",
        config_id="test_config",
        started_at_utc=started_at,
        finished_at_utc=finished_at,
        status="failed",
        input_count=10,
        candidate_count=5,
        correspondence_edge_count=3,
        activity_cluster_count=2,
        failed_stage="phase_03_candidate_generation",
        error_summary="RuntimeError: Synthetic test failure",
    )


def test_failure_writer_creates_valid_metadata_parquet(tmp_path):
    metadata = make_failed_metadata()

    path = write_failed_run_metadata(
        metadata=metadata,
        output_root=tmp_path,
    )

    assert path.is_file()
    assert path.name == "harm_run_metadata.parquet"
    assert path.parent == (
        tmp_path / "failures" / "failure_run_001"
    )

    connection = duckdb.connect(":memory:")

    try:
        description = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)",
            [str(path)],
        ).fetchall()

        actual_columns = [
            (row[0], row[1])
            for row in description
        ]

        expected_columns = [
            (column.name, column.data_type)
            for column in OUTPUT_SCHEMAS["harm_run_metadata"]
        ]

        assert actual_columns == expected_columns

        row = connection.execute(
            """
            SELECT
                run_id,
                status,
                failed_stage,
                input_count,
                candidate_count,
                correspondence_edge_count,
                activity_cluster_count,
                error_summary
            FROM read_parquet(?)
            """,
            [str(path)],
        ).fetchone()

        assert row == (
            "failure_run_001",
            "failed",
            "phase_03_candidate_generation",
            10,
            5,
            3,
            2,
            "RuntimeError: Synthetic test failure",
        )

        row_count = connection.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            [str(path)],
        ).fetchone()[0]

        assert row_count == 1

    finally:
        connection.close()


def test_failure_writer_does_not_overwrite_existing_record(tmp_path):
    metadata = make_failed_metadata()

    original_path = write_failed_run_metadata(
        metadata=metadata,
        output_root=tmp_path,
    )

    original_bytes = original_path.read_bytes()

    with pytest.raises(FileExistsError):
        write_failed_run_metadata(
            metadata=metadata,
            output_root=tmp_path,
        )

    assert original_path.read_bytes() == original_bytes

    failure_root = tmp_path / "failures"
    assert len(list(failure_root.iterdir())) == 1


def test_failure_writer_cleans_temporary_directory_after_error(
    tmp_path,
    monkeypatch,
):
    metadata = make_failed_metadata()

    def fail_quote_string(value):
        raise RuntimeError("Synthetic Parquet write failure")

    monkeypatch.setattr(
        failure_writer,
        "_quote_string",
        fail_quote_string,
    )

    with pytest.raises(
        RuntimeError,
        match="Synthetic Parquet write failure",
    ):
        write_failed_run_metadata(
            metadata=metadata,
            output_root=tmp_path,
        )

    failure_root = tmp_path / "failures"

    assert failure_root.exists()
    assert list(failure_root.iterdir()) == []
