"""Import pending FIRMS API Parquet files into the TwinFlame DuckDB."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.api_incremental_processor import APIIncrementalProcessor


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Process unimported NASA FIRMS API Parquet files."
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry files whose latest processing run failed; skip new pending files.",
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "raw" / "api",
        help="Root folder containing API Parquet files (searched recursively).",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=PROJECT_ROOT / "database" / "twinflame.duckdb",
        help="DuckDB database path.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    processor = APIIncrementalProcessor(
        raw_api_dir=args.raw_dir,
        database_path=args.database,
    )
    summary = processor.process_pending(retry_failed=args.retry_failed)

    mode = "failed retries" if args.retry_failed else "pending imports"
    logging.getLogger("process_pending_api_files").info(
        "%s: discovered=%d succeeded=%d failed=%d skipped=%d inserted_rows=%d",
        mode,
        summary.discovered_files,
        summary.succeeded,
        summary.failed,
        summary.skipped_files,
        summary.inserted_rows,
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
