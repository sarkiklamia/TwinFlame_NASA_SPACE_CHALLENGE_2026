#!/bin/sh
set -eu

if [ ! -f "${DUCKDB_PATH:-/app/database/twinflame.duckdb}" ]; then
  echo "ERROR: DuckDB file not found at ${DUCKDB_PATH:-/app/database/twinflame.duckdb}." >&2
  echo "Place twinflame.duckdb in the configured host database directory and restart." >&2
  exit 1
fi

python -c 'import os, sys, duckdb; path = os.environ.get("DUCKDB_PATH", "/app/database/twinflame.duckdb"); con = duckdb.connect(path, read_only=True); con.execute("SELECT 1").fetchone(); con.close()' || {
  echo "ERROR: DuckDB file exists but cannot be opened read-only: ${DUCKDB_PATH:-/app/database/twinflame.duckdb}." >&2
  exit 1
}

exec uvicorn app.backend.main:app --host 0.0.0.0 --port 8000
