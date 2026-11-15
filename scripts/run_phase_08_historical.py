"""CLI for the resumable Phase 08 historical harmonization backfill."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from harmonization.v3.phases.phase_08_historical_processing.archive_runner import (
    DEFAULT_N_BOOTSTRAP,
    audit_historical_source,
    run_phase_08,
)


DEFAULT_DATABASE = PROJECT_ROOT / "database" / "twinflame.duckdb"
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "processed" / "harmonization" / "phase_08"
)


def _date_argument(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run Phase 08 against UNIFIED_DETECTIONS. The source DuckDB is "
            "read-only; outputs are partitioned Parquet plus a separate "
            "harmonization.duckdb."
        ),
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--table", default="UNIFIED_DETECTIONS")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--run-id",
        help="Stable run ID to resume; reuse the same ID after an interruption.",
    )
    parser.add_argument("--start-date", type=_date_argument)
    parser.add_argument("--end-date", type=_date_argument)
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry failed date partitions while retaining successful outputs.",
    )
    parser.add_argument(
        "--n-bootstrap",
        type=int,
        default=DEFAULT_N_BOOTSTRAP,
        help="Phase 06 uncertainty bootstrap iterations (default: 1000).",
    )
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="Report available dates/platforms and gaps without harmonizing.",
    )
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if (
        args.start_date is not None
        and args.end_date is not None
        and args.start_date > args.end_date
    ):
        parser.error("--start-date must be on or before --end-date")

    try:
        if args.audit_only:
            audit = audit_historical_source(
                args.database,
                table=args.table,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            print(json.dumps({
                "table": audit["table"],
                "first_available_date": audit["first_available_date"],
                "last_available_date": audit["last_available_date"],
                "active_date_count": audit["active_date_count"],
                "supported_record_count": audit["supported_record_count"],
                "api_processing_watermark": audit[
                    "api_processing_watermark"
                ],
                "platform_totals": audit["platform_totals"],
                "platform_coverage": audit["platform_coverage"],
                "unsupported_platform_totals": audit[
                    "unsupported_platform_totals"
                ],
                "coverage_gaps": audit["coverage_gaps"],
            }, indent=2))
            return 0

        result = run_phase_08(
            database=args.database,
            output_root=args.output_root,
            table=args.table,
            run_id=args.run_id,
            start_date=args.start_date,
            end_date=args.end_date,
            retry_failed=args.retry_failed,
            n_bootstrap=args.n_bootstrap,
            confidence_level=args.confidence_level,
            random_seed=args.random_seed,
        )
    except Exception as exc:
        message = f"Phase 08 failed: {type(exc).__name__}: {exc}"
        lowered = str(exc).lower()
        if "being used by another process" in lowered or "lock" in lowered:
            message += (
                "\nClose the DuckDB terminal and stop API ingestion while "
                "Phase 08 is reading the source database."
            )
        parser.exit(2, message + "\n")

    summary = {
        "run_id": result["run_id"],
        "status": result["status"],
        "partition_summary": result["partition_summary"],
        "coverage_gaps": result["source_audit"]["coverage_gaps"],
        "manifest": str(
            Path(args.output_root).resolve()
            / result["run_id"]
            / "phase08_manifest.json"
        ),
        "parquet_partitions": str(
            Path(args.output_root).resolve()
            / result["run_id"]
            / "partitions"
        ),
        "output_database": str(
            Path(args.output_root).resolve()
            / result["run_id"]
            / "harmonization.duckdb"
        ),
        "stop_reason": result.get("stop_reason"),
    }
    print(json.dumps(summary, indent=2))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
