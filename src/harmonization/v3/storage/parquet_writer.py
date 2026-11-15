from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
import re
import shutil
import uuid
from typing import Any

import duckdb

from ..phases.phase_07_output_generation.output_validation import (
    validate_output_rows,
)
from ..phases.phase_07_output_generation.run_metadata import (
    build_run_metadata,
)
from ..phases.phase_07_output_generation.schemas import OUTPUT_SCHEMAS


_DUCKDB_TYPES = {
    "VARCHAR": "VARCHAR",
    "DATE": "DATE",
    "TIMESTAMP": "TIMESTAMP",
    "DOUBLE": "DOUBLE",
    "INTEGER": "INTEGER",
    "BIGINT": "BIGINT",
}


def _quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid SQL identifier: {value}")
    return f'"{value}"'


def _normalize_timestamp(value: Any, column_name: str) -> Any:
    if value is None:
        return None

    if not isinstance(value, datetime):
        raise TypeError(f"{column_name} must be a datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{column_name} must be timezone-aware; "
            "naive timestamps are not accepted"
        )

    utc_value = value.astimezone(timezone.utc)
    return utc_value.replace(tzinfo=None)


def _normalize_row(
    table_name: str,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    schema = OUTPUT_SCHEMAS[table_name]
    timestamp_columns = {
        column.name
        for column in schema
        if column.data_type == "TIMESTAMP"
    }

    item = dict(row)
    for column_name in timestamp_columns:
        item[column_name] = _normalize_timestamp(
            item[column_name],
            column_name,
        )
    return item


def _normalize_rows(
    table_name: str,
    rows: tuple[Mapping[str, Any], ...],
) -> list[dict[str, Any]]:
    """Compatibility helper for small callers and focused tests."""
    return [_normalize_row(table_name, row) for row in rows]


def _create_table(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
) -> None:
    definitions = []

    for column in OUTPUT_SCHEMAS[table_name]:
        duckdb_type = _DUCKDB_TYPES[column.data_type]
        nullable = "" if column.nullable else " NOT NULL"

        definitions.append(
            f"{_quote_identifier(column.name)} "
            f"{duckdb_type}{nullable}"
        )

    sql = (
        f"CREATE TABLE {_quote_identifier(table_name)} "
        f"({', '.join(definitions)})"
    )
    connection.execute(sql)


def _insert_rows(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    rows,
    batch_size: int = 5_000,
) -> None:
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")

    columns = [
        column.name for column in OUTPUT_SCHEMAS[table_name]
    ]

    column_sql = ", ".join(
        _quote_identifier(name) for name in columns
    )
    placeholders = ", ".join("?" for _ in columns)

    sql = (
        f"INSERT INTO {_quote_identifier(table_name)} "
        f"({column_sql}) VALUES ({placeholders})"
    )

    batch = []
    for row in rows:
        batch.append(tuple(row[name] for name in columns))
        if len(batch) >= batch_size:
            connection.executemany(sql, batch)
            batch.clear()

    if batch:
        connection.executemany(sql, batch)


def _write_table(
    table_name: str,
    rows,
    output_path: Path,
) -> None:
    """Write one table with a short-lived DuckDB connection."""
    connection = duckdb.connect(database=":memory:")
    try:
        _create_table(connection, table_name)
        _insert_rows(
            connection,
            table_name,
            (_normalize_row(table_name, row) for row in rows),
        )
        escaped_path = str(output_path).replace("'", "''")
        connection.execute(
            f"COPY {_quote_identifier(table_name)} "
            f"TO '{escaped_path}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()


def write_phase_07_parquet(
    phase07_result: Any,
    output_root: str | Path,
    run_id: str,
) -> dict[str, Path]:
    """
    Write all seven Phase 7 tables as Parquet files.

    Output:
        output_root/
            run_id/
                harm_correspondence_edges.parquet
                ...
                harm_run_metadata.parquet

    A run directory is published only after every table is written.
    Existing run directories are never overwritten.
    """
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise ValueError(
            "run_id may contain only letters, digits, '.', '_' and '-'"
        )

    tables = getattr(phase07_result, "tables", None)

    if not isinstance(tables, Mapping):
        raise TypeError("phase07_result must expose a tables mapping")

    expected = set(OUTPUT_SCHEMAS)
    actual = set(tables)

    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            f"Phase 7 table mismatch. Missing: {missing}; "
            f"unexpected: {unexpected}"
        )

    table_rows = {}

    for table_name in OUTPUT_SCHEMAS:
        rows = tuple(tables[table_name])
        validate_output_rows(table_name, rows)
        table_rows[table_name] = rows

    metadata_table = "harm_run_metadata"
    metadata_rows = table_rows[metadata_table]

    if len(metadata_rows) > 1:
        raise ValueError(
            "harm_run_metadata must contain zero or one row"
        )

    finalized_metadata = ()
    if metadata_rows:
        original_metadata = dict(metadata_rows[0])
        if original_metadata["status"] == "running":
            finalized_metadata = (build_run_metadata(
                run_id=original_metadata["run_id"],
                algorithm_version=original_metadata["algorithm_version"],
                config_id=original_metadata["config_id"],
                started_at_utc=original_metadata["started_at_utc"],
                finished_at_utc=datetime.now(timezone.utc),
                status="success",
                input_count=original_metadata["input_count"],
                candidate_count=original_metadata["candidate_count"],
                correspondence_edge_count=original_metadata[
                    "correspondence_edge_count"
                ],
                activity_cluster_count=original_metadata[
                    "activity_cluster_count"
                ],
            ),)
        else:
            finalized_metadata = (original_metadata,)
            validate_output_rows(metadata_table, finalized_metadata)

    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    final_directory = output_root / run_id

    if final_directory.exists():
        raise FileExistsError(
            f"Output run directory already exists: {final_directory}"
        )

    temporary_directory = output_root / (
        f".{run_id}.tmp-{uuid.uuid4().hex}"
    )
    temporary_directory.mkdir()

    try:
        output_paths = {}

        # Normalize, insert, and export one table at a time. Each table gets
        # a short-lived in-memory database so prior table data is released.
        for table_name in OUTPUT_SCHEMAS:
            if table_name == metadata_table:
                continue

            filename = f"{table_name}.parquet"
            temporary_file = temporary_directory / filename
            _write_table(
                table_name,
                table_rows[table_name],
                temporary_file,
            )
            output_paths[table_name] = final_directory / filename

        filename = f"{metadata_table}.parquet"
        temporary_file = temporary_directory / filename
        _write_table(
            metadata_table,
            finalized_metadata,
            temporary_file,
        )
        output_paths[metadata_table] = final_directory / filename

        # Publish only after all seven Parquet files are complete.
        temporary_directory.rename(final_directory)

        # Keep the returned in-memory result consistent with Parquet.
        if metadata_rows and metadata_rows[0]["status"] == "running":
            phase07_result.tables[metadata_table] = finalized_metadata

        return output_paths

    except BaseException:
        if temporary_directory.exists():
            shutil.rmtree(temporary_directory)

        raise
