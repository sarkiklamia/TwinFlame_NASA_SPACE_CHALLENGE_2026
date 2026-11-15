from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from harmonization.v3.phases.phase_07_output_generation.schemas import (
    OUTPUT_SCHEMAS,
)
from harmonization.v3.storage.parquet_writer import (
    write_phase_07_parquet,
)
from harmonization.v3.storage import parquet_writer


def make_empty_result():
    return SimpleNamespace(
        tables={
            table_name: ()
            for table_name in OUTPUT_SCHEMAS
        }
    )


def test_writer_creates_all_seven_empty_parquet_files(tmp_path):
    result = make_empty_result()

    paths = write_phase_07_parquet(
        result,
        tmp_path,
        "empty_run_001",
    )

    assert set(paths) == set(OUTPUT_SCHEMAS)
    assert len(paths) == 7

    for table_name, path in paths.items():
        assert path.is_file()
        assert path.name == f"{table_name}.parquet"

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
                for column in OUTPUT_SCHEMAS[table_name]
            ]

            assert actual_columns == expected_columns

            row_count = connection.execute(
                "SELECT COUNT(*) FROM read_parquet(?)",
                [str(path)],
            ).fetchone()[0]

            assert row_count == 0
        finally:
            connection.close()


def test_writer_does_not_overwrite_existing_run_directory(tmp_path):
    result = make_empty_result()

    write_phase_07_parquet(
        result,
        tmp_path,
        "duplicate_run",
    )

    with pytest.raises(FileExistsError):
        write_phase_07_parquet(
            result,
            tmp_path,
            "duplicate_run",
        )


def test_writer_rejects_missing_output_table(tmp_path):
    result = make_empty_result()
    result.tables.pop("harm_run_metadata")

    with pytest.raises(ValueError, match="table mismatch"):
        write_phase_07_parquet(
            result,
            tmp_path,
            "invalid_run",
        )


def test_writer_rejects_invalid_run_id(tmp_path):
    with pytest.raises(ValueError, match="run_id"):
        write_phase_07_parquet(
            make_empty_result(),
            tmp_path,
            "../unsafe",
        )


def test_writer_does_not_leave_temporary_directory_after_failure(tmp_path):
    result = make_empty_result()
    result.tables["harm_run_metadata"] = (
        {"invalid": "row"},
    )

    with pytest.raises(ValueError):
        write_phase_07_parquet(
            result,
            tmp_path,
            "failed_run",
        )

    assert not (tmp_path / "failed_run").exists()
    assert list(tmp_path.iterdir()) == []


def test_writer_cleans_temporary_directory_when_interrupted(tmp_path, monkeypatch):
    def interrupt_write(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(parquet_writer, "_write_table", interrupt_write)

    with pytest.raises(KeyboardInterrupt):
        write_phase_07_parquet(
            make_empty_result(),
            tmp_path,
            "interrupted_run",
        )

    assert not (tmp_path / "interrupted_run").exists()
    assert list(tmp_path.iterdir()) == []
