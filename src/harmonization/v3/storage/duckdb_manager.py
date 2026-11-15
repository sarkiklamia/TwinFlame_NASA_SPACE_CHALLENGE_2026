"""Small, explicit DuckDB connection helpers for pipeline storage."""

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import duckdb


@contextmanager
def open_database(
    database: str | Path,
    *,
    read_only: bool = True,
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open a database connection and always close it on exit.

    File-backed databases are read-only by default. In-memory databases are
    allowed for tests and temporary work, but DuckDB requires them to be
    writable connections.
    """
    database_name = str(database)

    if database_name == ":memory:":
        if read_only:
            raise ValueError("An in-memory DuckDB connection cannot be read-only")
    elif read_only and not Path(database_name).is_file():
        raise FileNotFoundError(f"DuckDB database not found: {database_name}")

    connection = duckdb.connect(
        database=database_name,
        read_only=read_only,
    )
    try:
        yield connection
    finally:
        connection.close()
