from dataclasses import dataclass
from datetime import datetime
from typing import Any
from itertools import islice

from ...storage.input_reader import (
    load_unified_detections,
    iter_unified_detections,
)
from .column_mapping import CanonicalInputRecord, map_input_record
from .input_audit import (
    InputAuditReport,
    InputAuditAccumulator,
    audit_records,
)


@dataclass(frozen=True)
class Phase00Result:
    audit: InputAuditReport
    observations: tuple[CanonicalInputRecord, ...]


def run_phase_00(
    database: str,
    table: str = "UNIFIED_DETECTIONS",
    platforms: str | list[str] | None = None,
    *,
    acquisition_start_utc: datetime | None = None,
    acquisition_end_utc_exclusive: datetime | None = None,
) -> Phase00Result:

    rows: list[dict[str, Any]] = load_unified_detections(
        database=database,
        table=table,
        platforms=platforms,
        acquisition_start_utc=acquisition_start_utc,
        acquisition_end_utc_exclusive=acquisition_end_utc_exclusive,
    )

    audit = audit_records(rows)
    observations = tuple(map_input_record(row) for row in rows)

    return Phase00Result(
        audit=audit,
        observations=observations,
    )

@dataclass(frozen=True)
class Phase00StreamingResult:
    audit: InputAuditReport
    mapped_record_count: int
    batch_size: int


def run_phase_00_streaming(
    database: str,
    table: str = "UNIFIED_DETECTIONS",
    platforms: str | list[str] | None = None,
    batch_size: int = 50_000,
    *,
    acquisition_start_utc: datetime | None = None,
    acquisition_end_utc_exclusive: datetime | None = None,
) -> Phase00StreamingResult:
    """
    Audit and map the real dataset in bounded batches.

    Does not retain all canonical observations in memory.
    """

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    accumulator = InputAuditAccumulator()
    rows = iter_unified_detections(
        database=database,
        table=table,
        platforms=platforms,
        batch_size=batch_size,
        acquisition_start_utc=acquisition_start_utc,
        acquisition_end_utc_exclusive=acquisition_end_utc_exclusive,
    )

    mapped_count = 0

    while True:
        batch = list(islice(rows, batch_size))

        if not batch:
            break

        mapped_records = [
            map_input_record(row)
            for row in batch
        ]

        accumulator.update(batch, mapped_records)
        mapped_count += len(mapped_records)

        print(
            f"Phase 00 processed: {mapped_count:,} records",
            end="\r",
            flush=True,
        )

    print()

    return Phase00StreamingResult(
        audit=accumulator.report(),
        mapped_record_count=mapped_count,
        batch_size=batch_size,
    )
