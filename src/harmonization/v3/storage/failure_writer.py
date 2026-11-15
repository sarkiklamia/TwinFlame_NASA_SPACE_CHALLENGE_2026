
from pathlib import Path
import re
import shutil
import uuid
from datetime import timezone
import duckdb

from ..phases.phase_07_output_generation.output_validation import (
    validate_output_rows,
)
from ..phases.phase_07_output_generation.schemas import OUTPUT_SCHEMAS


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _quote_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _normalize_metadata_row(row: dict) -> dict:
    """Convert timezone-aware UTC timestamps to DuckDB TIMESTAMP values."""
    normalized = dict(row)

    for column in OUTPUT_SCHEMAS["harm_run_metadata"]:
        if column.data_type != "TIMESTAMP":
            continue

        value = normalized[column.name]

        if value is not None:
            normalized[column.name] = (
                value.astimezone(timezone.utc).replace(tzinfo=None)
            )

    return normalized


def write_failed_run_metadata(
    *,
    metadata: dict,
    output_root: str | Path,
) -> Path:
    """
    Atomically publish one failed-run metadata Parquet file.

    Failure records are stored separately from successful run outputs.
    Existing failure records are never overwritten.
    """
    run_id = metadata.get("run_id")

    if (
        not isinstance(run_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id)
    ):
        raise ValueError("Invalid run_id for failure metadata output")

    validate_output_rows("harm_run_metadata", [metadata])

    row = _normalize_metadata_row(metadata)
    schema = OUTPUT_SCHEMAS["harm_run_metadata"]

    root = Path(output_root) / "failures"
    root.mkdir(parents=True, exist_ok=True)

    final_dir = root / run_id

    if final_dir.exists():
        raise FileExistsError(
            f"Failure metadata already exists for run '{run_id}'"
        )

    temporary_dir = root / f".{run_id}.tmp-{uuid.uuid4().hex}"
    temporary_dir.mkdir()

    connection = duckdb.connect(database=":memory:")

    try:
        columns_sql = ", ".join(
            f"{_quote_identifier(column.name)} {column.data_type}"
            + ("" if column.nullable else " NOT NULL")
            for column in schema
        )

        connection.execute(
            f"CREATE TABLE harm_run_metadata ({columns_sql})"
        )

        column_names = [column.name for column in schema]
        placeholders = ", ".join("?" for _ in column_names)

        insert_sql = (
            "INSERT INTO harm_run_metadata ("
            + ", ".join(_quote_identifier(name) for name in column_names)
            + f") VALUES ({placeholders})"
        )

        connection.execute(
            insert_sql,
            [row[name] for name in column_names],
        )

        parquet_path = temporary_dir / "harm_run_metadata.parquet"

        connection.execute(
            "COPY harm_run_metadata TO "
            + _quote_string(str(parquet_path))
            + " (FORMAT PARQUET)"
        )

        connection.close()
        connection = None

        temporary_dir.rename(final_dir)

        return final_dir / "harm_run_metadata.parquet"

    except Exception:
        if connection is not None:
            connection.close()

        if temporary_dir.exists():
            shutil.rmtree(temporary_dir, ignore_errors=True)

        raise
