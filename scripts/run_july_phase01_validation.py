"""Run a bounded-memory Phase 01 QC audit for a UTC date interval."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import date, datetime, time, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from harmonization.v3.phases.phase_00_input_audit.column_mapping import (
    map_input_record,
)
from harmonization.v3.storage.input_reader import (
    iter_unified_detections,
)
from harmonization.v3.phases.phase_01_quality_control import (
    run_phase_01_streaming,
)


DEFAULT_DATABASE = PROJECT_ROOT / "database" / "twinflame.duckdb"
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "processed" / "harmonization" / "validation"
)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD") from exc


def _utc_midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _canonical_observations(
    database: Path,
    table: str,
    start_utc: datetime,
    end_utc_exclusive: datetime,
    batch_size: int,
) -> Iterable:
    rows = iter_unified_detections(
        database=database,
        table=table,
        batch_size=batch_size,
        acquisition_start_utc=start_utc,
        acquisition_end_utc_exclusive=end_utc_exclusive,
    )
    for count, row in enumerate(rows, start=1):
        if count % batch_size == 0:
            print(f"Phase 01 processed: {count:,} records", flush=True)
        yield map_input_record(row)


def _write_outputs(output_root: Path, summary, metadata: dict) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    start_day = metadata["acquisition_start_utc_inclusive"][:10]
    end_day = metadata["acquisition_end_utc_exclusive"][:10]
    run_id = (
        f"phase01-{start_day}-to-{end_day}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}"
    )
    temporary = output_root / f".{run_id}.tmp"
    final = output_root / run_id
    temporary.mkdir(exist_ok=False)

    try:
        groups_path = temporary / "phase01_platform_day.csv"
        with groups_path.open("w", encoding="utf-8", newline="") as handle:
            fields = list(asdict(summary.groups[0]).keys()) if summary.groups else [
                "platform",
                "utc_date",
                "input_count",
                "spatial_eligible_count",
                "frp_eligible_count",
                "brightness_eligible_count",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(asdict(group) for group in summary.groups)

        counts = {
            "input_count": summary.input_count,
            "spatial_eligible_count": summary.spatial_eligible_count,
            "frp_eligible_count": summary.frp_eligible_count,
            "brightness_eligible_count": summary.brightness_eligible_count,
            "issue_counts": summary.issue_counts,
            "warning_counts": summary.warning_counts,
        }
        (temporary / "phase01_qc_counts.json").write_text(
            json.dumps(counts, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        metadata["run_id"] = run_id
        metadata["status"] = "completed"
        metadata["group_count"] = len(summary.groups)
        (temporary / "phase01_run_metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.rename(final)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return final


def run_validation(
    *,
    database: Path,
    output_root: Path,
    table: str,
    start_date: date,
    end_date_exclusive: date,
    batch_size: int,
) -> Path:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")
    if start_date >= end_date_exclusive:
        raise ValueError("start_date must be earlier than end_date_exclusive")

    start_utc = _utc_midnight(start_date)
    end_utc = _utc_midnight(end_date_exclusive)
    observations = _canonical_observations(
        database,
        table,
        start_utc,
        end_utc,
        batch_size,
    )
    summary = run_phase_01_streaming(observations)
    metadata = {
        "source_database": str(database.resolve()),
        "source_table": table,
        "read_only": True,
        "acquisition_start_utc_inclusive": start_utc.isoformat(),
        "acquisition_end_utc_exclusive": end_utc.isoformat(),
        "batch_size": batch_size,
        "input_count": summary.input_count,
        "spatial_eligible_count": summary.spatial_eligible_count,
        "frp_eligible_count": summary.frp_eligible_count,
        "brightness_eligible_count": summary.brightness_eligible_count,
    }
    return _write_outputs(output_root, summary, metadata)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--table", default="UNIFIED_DETECTIONS")
    parser.add_argument("--start-date", type=_parse_date, default=date(2026, 7, 1))
    parser.add_argument(
        "--end-date-exclusive",
        type=_parse_date,
        default=date(2026, 8, 1),
    )
    parser.add_argument("--batch-size", type=int, default=100_000)
    args = parser.parse_args()

    output = run_validation(
        database=args.database,
        output_root=args.output_root,
        table=args.table,
        start_date=args.start_date,
        end_date_exclusive=args.end_date_exclusive,
        batch_size=args.batch_size,
    )
    report = json.loads(
        (output / "phase01_qc_counts.json").read_text(encoding="utf-8")
    )
    print(f"Phase 01 input rows: {report['input_count']:,}")
    print(f"Phase 01 report: {output}")


if __name__ == "__main__":
    main()
