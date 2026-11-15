"""Hourly, resumable API harmonization over a completed Phase 08 baseline."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
import uuid

import duckdb

from ...config.experiments import build_threshold_experiments
from ...config.thresholds import (
    OPERATIONAL_DISTANCE_THRESHOLD_KM,
    OPERATIONAL_TIME_THRESHOLD_MINUTES,
)
from ...phases.phase_03_candidate_generation.candidate_generator import (
    SUPPORTED_PLATFORM_PAIRS,
)
from ...phases.phase_05_validation.reference_data import (
    load_phase05_reference_inputs,
    summarize_phase05_results,
)
from ...pipeline.orchestrator import PipelineExecutionError, run_pipeline
from ...storage.duckdb_manager import open_database
from ...storage.parquet_writer import write_phase_07_parquet
from ..phase_08_historical_processing.archive_runner import (
    _inspect_partition_parquet,
    _partition_output_directory,
    _source_is_unchanged,
    _write_json_atomic,
    database_snapshot,
)
from ..phase_08_historical_processing.partition_processing import (
    canonical_platform,
    count_duplicate_observation_identities,
    filter_phase07_to_partition,
)
from .affected_partition_reprocessing import build_affected_partitions
from .watermark import load_watermark, save_watermark


PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DATABASE = PROJECT_ROOT / "database" / "twinflame.duckdb"
DEFAULT_PHASE08_ROOT = (
    PROJECT_ROOT / "data" / "processed" / "harmonization" / "phase_08"
)
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "processed" / "harmonization" / "phase_09"
)
API_PROCESSING_VERSION = "pyrosync-api-incremental-v1"
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _quote_identifier(value: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return f'"{value}"'


def _quote_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _read_phase08_manifest(
    phase08_output_root: str | Path,
    phase08_run_id: str | None = None,
) -> tuple[Path, dict[str, Any]] | None:
    root = Path(phase08_output_root).expanduser().resolve()
    candidates = []
    if phase08_run_id:
        candidates = [root / phase08_run_id / "phase08_manifest.json"]
    elif root.is_dir():
        candidates = sorted(
            root.glob("*/phase08_manifest.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )

    for path in candidates:
        if not path.is_file():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            manifest.get("phase") != "08_full_historical_processing"
            or manifest.get("status") != "success"
        ):
            continue
        date_filter = manifest.get("configuration", {}).get("date_filter", {})
        if date_filter.get("start_inclusive") or date_filter.get("end_inclusive"):
            continue
        thresholds = manifest.get("configuration", {}).get(
            "selected_thresholds", {}
        )
        if (
            thresholds.get("temporal_minutes")
            != OPERATIONAL_TIME_THRESHOLD_MINUTES
            or thresholds.get("spatial_km")
            != OPERATIONAL_DISTANCE_THRESHOLD_KM
        ):
            continue
        return path.parent, manifest
    return None


def _read_base_pipeline_config(
    output_database: Path,
    phase08_run_id: str,
    partition_dates: list[str],
) -> tuple[str, str]:
    if not output_database.is_file():
        raise FileNotFoundError(
            f"Phase 08 output database is missing: {output_database}"
        )
    connection = duckdb.connect(str(output_database), read_only=True)
    try:
        configurations = set()
        for date_text in partition_dates:
            partition_run_id = (
                f"{phase08_run_id}_{date.fromisoformat(date_text):%Y%m%d}"
            )
            rows = connection.execute(
                "SELECT algorithm_version, config_id "
                "FROM harm_run_metadata WHERE run_id = ? AND status = 'success'",
                [partition_run_id],
            ).fetchall()
            if len(rows) != 1:
                raise ValueError(
                    "The Phase 08 output database must contain exactly one "
                    f"successful metadata row for partition {partition_run_id}; "
                    f"found {len(rows)}."
                )
            configurations.add((str(rows[0][0]), str(rows[0][1])))
    finally:
        connection.close()
    if len(configurations) != 1:
        raise ValueError(
            "Phase 08 partitions do not share one algorithm/configuration."
        )
    return next(iter(configurations))


def _api_processing_progress(
    database: str | Path,
    watermark_processing_id: int,
) -> dict[str, Any]:
    """Return the safe latest API processor run and any unresolved files."""
    with open_database(database, read_only=True) as connection:
        rows = connection.execute(
            """
            WITH latest AS (
                SELECT
                    sf.file_id,
                    sf.filename,
                    pr.processing_id,
                    pr.start_time,
                    UPPER(COALESCE(pr.status, '')) AS status,
                    ROW_NUMBER() OVER (
                        PARTITION BY sf.file_id
                        ORDER BY pr.processing_id DESC
                    ) AS row_number
                FROM PROCESSING_RUNS AS pr
                JOIN SOURCE_FILES AS sf ON sf.file_id = pr.input_file_id
                WHERE sf.source_type = 'API'
                  AND pr.processing_version = ?
            )
            SELECT file_id, filename, processing_id, start_time, status
            FROM latest
            WHERE row_number = 1 AND processing_id > ?
            ORDER BY processing_id
            """,
            [API_PROCESSING_VERSION, watermark_processing_id],
        ).fetchall()

    unresolved = [
        {
            "file_id": int(row[0]),
            "filename": str(row[1]),
            "processing_id": int(row[2]),
            "status": str(row[4]),
        }
        for row in rows
        if str(row[4]).upper() != "COMPLETED"
    ]
    completed = [row for row in rows if str(row[4]).upper() == "COMPLETED"]
    safe_through = max(
        [watermark_processing_id]
        + [int(row[2]) for row in completed]
    )
    latest_start = max(
        (row[3] for row in completed if row[3] is not None),
        default=None,
    )
    return {
        "safe_through_processing_id": safe_through,
        "completed_files": len(completed),
        "unresolved_files": unresolved,
        "latest_processing_time_utc": (
            latest_start.replace(tzinfo=timezone.utc).isoformat()
            if latest_start is not None
            else None
        ),
    }


def _new_api_records(
    database: str | Path,
    *,
    after_processing_id: int,
    through_processing_id: int,
    table: str,
) -> list[dict[str, Any]]:
    if not _SAFE_IDENTIFIER.fullmatch(table):
        raise ValueError(f"Invalid table identifier: {table!r}")
    if through_processing_id <= after_processing_id:
        return []
    with open_database(database, read_only=True) as connection:
        columns = connection.execute(
            f"DESCRIBE {_quote_identifier(table)}"
        ).fetchall()
        available = {row[0] for row in columns}
        required = {
            "detection_id",
            "processing_id",
            "source",
            "platform",
            "acquisition_time_utc",
        }
        if not required.issubset(available):
            raise ValueError(
                f"{table} lacks Phase 09 columns: "
                f"{sorted(required - available)}"
            )
        rows = connection.execute(
            f"""
            SELECT d.detection_id, d.platform, d.acquisition_time_utc,
                   d.processing_id
            FROM {_quote_identifier(table)} AS d
            JOIN PROCESSING_RUNS AS pr
              ON pr.processing_id = d.processing_id
            JOIN SOURCE_FILES AS sf
              ON sf.file_id = d.file_id
            WHERE sf.source_type = 'API'
              AND pr.processing_version = ?
              AND pr.status = 'COMPLETED'
              AND d.source = 'FIRMS_API'
              AND d.processing_id > ?
              AND d.processing_id <= ?
            ORDER BY d.processing_id, d.detection_id
            """,
            [
                API_PROCESSING_VERSION,
                after_processing_id,
                through_processing_id,
            ],
        ).fetchall()
    return [
        {
            "detection_id": str(row[0]),
            "platform": row[1],
            "acquisition_time_utc": row[2],
            "processing_id": int(row[3]),
        }
        for row in rows
    ]


def _partition_run_id(batch_id: str, activity_date: date) -> str:
    return f"{batch_id}_{activity_date:%Y%m%d}"


def _run_id_counts(connection, run_id: str) -> dict[str, int]:
    return {
        table_name: int(connection.execute(
            f"SELECT COUNT(*) FROM {_quote_identifier(table_name)} "
            "WHERE run_id = ?",
            [run_id],
        ).fetchone()[0])
        for table_name in (
            "harm_correspondence_edges",
            "harm_activity_clusters",
            "harm_cluster_members",
            "harm_sensor_activity_daily",
            "harm_correspondence_summary",
            "harm_frp_comparisons",
            "harm_run_metadata",
        )
    }


def _replace_partition_in_database(
    output_database: Path,
    partition_directory: Path,
    *,
    new_run_id: str,
    previous_run_id: str | None,
    expected_counts: dict[str, int],
) -> bool:
    """Replace one date's seven tables transactionally; safe to replay."""
    connection = duckdb.connect(str(output_database))
    table_names = tuple(expected_counts)
    try:
        # A process can stop after the DuckDB transaction but before writing
        # its checkpoint. Detect that commit and do not insert it twice.
        existing_new = int(connection.execute(
            "SELECT COUNT(*) FROM harm_run_metadata WHERE run_id = ?",
            [new_run_id],
        ).fetchone()[0])
        if existing_new:
            actual = _run_id_counts(connection, new_run_id)
            if actual != expected_counts:
                raise ValueError(
                    "Phase 09 run_id already exists with different row counts."
                )
            return False

        connection.execute("BEGIN TRANSACTION")
        try:
            if previous_run_id and previous_run_id != new_run_id:
                old_metadata = int(connection.execute(
                    "SELECT COUNT(*) FROM harm_run_metadata WHERE run_id = ?",
                    [previous_run_id],
                ).fetchone()[0])
                if old_metadata > 1:
                    raise ValueError(
                        f"Multiple output metadata rows for {previous_run_id}"
                    )
                if old_metadata == 0:
                    raise ValueError(
                        f"Expected previous output partition {previous_run_id} "
                        "is missing from the Phase 08 DuckDB."
                    )
                if old_metadata:
                    for table_name in table_names:
                        connection.execute(
                            f"DELETE FROM {_quote_identifier(table_name)} "
                            "WHERE run_id = ?",
                            [previous_run_id],
                        )

            for table_name in table_names:
                parquet_path = partition_directory / f"{table_name}.parquet"
                connection.execute(
                    f"INSERT INTO {_quote_identifier(table_name)} "
                    "SELECT * FROM read_parquet(" + _quote_string(parquet_path) + ")"
                )

            actual = _run_id_counts(connection, new_run_id)
            if actual != expected_counts:
                raise ValueError(
                    f"Updated output counts differ from Parquet: {actual}"
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return True
    finally:
        connection.close()


def _batch_manifest_path(phase09_run_directory: Path) -> Path:
    return phase09_run_directory / "phase09_manifest.json"


def _save_batch_manifest(
    phase09_run_directory: Path,
    batch: dict[str, Any],
    phase08_run_id: str,
) -> None:
    _write_json_atomic(
        _batch_manifest_path(phase09_run_directory),
        {
            "manifest_version": 1,
            "phase": "09_incremental_api_processing",
            "phase08_run_id": phase08_run_id,
            "batch": batch,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )


def run_phase_09(
    *,
    database: str | Path = DEFAULT_DATABASE,
    phase08_output_root: str | Path = DEFAULT_PHASE08_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    phase08_run_id: str | None = None,
    table: str = "UNIFIED_DETECTIONS",
) -> dict[str, Any]:
    """Process new API processing runs and atomically replace affected dates.

    Phase 08 must have completed successfully. The source database is only
    queried in read-only mode; incremental results update the separate Phase
    08 harmonization database and are also preserved as Phase 09 Parquet.
    """
    baseline = _read_phase08_manifest(
        phase08_output_root,
        phase08_run_id,
    )
    if baseline is None:
        return {
            "status": "not_ready",
            "message": (
                "No successful, full-coverage Phase 08 run was found. "
                "Complete Phase 08 before starting incremental harmonization."
            ),
        }

    base_run_directory, base_manifest = baseline
    base_run_id = str(base_manifest["run_id"])
    base_database = base_run_directory / "harmonization.duckdb"
    database_path = Path(database).expanduser().resolve()
    output_root = Path(output_root).expanduser().resolve()
    base_configuration = base_manifest.get("configuration", {})
    baseline_database = base_configuration.get("database")
    if not baseline_database or Path(baseline_database).expanduser().resolve() != database_path:
        raise ValueError(
            "The selected Phase 08 baseline was built from a different source "
            "database. Phase 09 must use the same UNIFIED_DETECTIONS database."
        )
    if base_configuration.get("table") != table:
        raise ValueError(
            "The selected Phase 08 baseline used a different source table."
        )
    reference_inputs = load_phase05_reference_inputs()
    phase09_run_directory = output_root / base_run_id
    phase09_run_directory.mkdir(parents=True, exist_ok=True)
    checkpoint_path = phase09_run_directory / "watermark.json"

    base_dates = [
        item["date_utc"]
        for item in base_manifest.get("partitions", [])
        if item.get("status") == "succeeded"
    ]
    _base_algorithm_version, base_config_id = _read_base_pipeline_config(
        base_database,
        base_run_id,
        base_dates,
    )
    phase09_config_id = base_config_id
    n_bootstrap = int(base_configuration.get("n_bootstrap", 1000))
    confidence_level = float(base_configuration.get("confidence_level", 0.95))
    random_seed = int(base_configuration.get("random_seed", 42))

    checkpoint = load_watermark(checkpoint_path)
    if checkpoint is None:
        source_audit = base_manifest.get("source_audit", {})
        baseline_watermark = source_audit.get("api_processing_watermark")
        if baseline_watermark is None:
            # Older Phase 08 manifests are safe to seed only if the source
            # file has not changed since the historical backfill.
            saved_snapshot = base_manifest.get("source_snapshot")
            if saved_snapshot != database_snapshot(database_path):
                raise ValueError(
                    "This Phase 08 manifest has no API processing watermark, "
                    "and the source changed since it ran. Rebuild Phase 08 "
                    "with the current runner before enabling Phase 09."
                )
            with open_database(database_path, read_only=True) as connection:
                baseline_watermark = connection.execute(
                    """
                    SELECT COALESCE(MAX(pr.processing_id), 0)
                    FROM PROCESSING_RUNS AS pr
                    JOIN SOURCE_FILES AS sf ON sf.file_id = pr.input_file_id
                    WHERE sf.source_type = 'API' AND pr.status = 'COMPLETED'
                    """
                ).fetchone()[0]

        checkpoint = {
            "watermark_version": 1,
            "phase08_run_id": base_run_id,
            "watermark_processing_id": int(baseline_watermark or 0),
            "watermark_time_utc": source_audit.get(
                "api_processing_watermark_time_utc"
            ),
            "current_run_by_date": {
                date_text: f"{base_run_id}_{date.fromisoformat(date_text):%Y%m%d}"
                for date_text in base_dates
            },
            "pending_batch": None,
            "initialized_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        save_watermark(checkpoint_path, checkpoint)
    elif checkpoint.get("phase08_run_id") != base_run_id:
        raise ValueError(
            "The Phase 09 watermark belongs to a different Phase 08 baseline."
        )

    pending_batch = checkpoint.get("pending_batch")
    if pending_batch is None:
        current_watermark = int(checkpoint["watermark_processing_id"])
        progress = _api_processing_progress(
            database_path,
            current_watermark,
        )
        if progress["unresolved_files"]:
            return {
                "status": "blocked",
                "watermark_processing_id": current_watermark,
                "unresolved_files": progress["unresolved_files"],
                "message": (
                    "Phase 09 did not advance its watermark because one or "
                    "more recent API files have not completed processing."
                ),
            }

        safe_through = int(progress["safe_through_processing_id"])
        if safe_through <= current_watermark:
            return {
                "status": "no_data",
                "watermark_processing_id": current_watermark,
                "message": "No completed API processing runs are newer than the watermark.",
            }

        source_before = database_snapshot(database_path)
        new_records = _new_api_records(
            database_path,
            after_processing_id=current_watermark,
            through_processing_id=safe_through,
            table=table,
        )
        source_after = database_snapshot(database_path)
        if source_before != source_after:
            return {
                "status": "blocked",
                "watermark_processing_id": current_watermark,
                "message": (
                    "The source DuckDB changed while new API rows were being "
                    "selected. Retry Phase 09 after the writer closes."
                ),
            }

        invalid_records = [
            item for item in new_records
            if (
                item["acquisition_time_utc"] is None
                or canonical_platform(item["platform"]) is None
            )
        ]
        if invalid_records:
            return {
                "status": "blocked",
                "watermark_processing_id": current_watermark,
                "invalid_api_record_count": len(invalid_records),
                "message": (
                    "New API detections have an unsupported platform or no "
                    "acquisition timestamp; the watermark was not advanced."
                ),
            }

        affected = build_affected_partitions(
            str(database_path),
            new_records,
            table=table,
        )
        batch_id = (
            f"p09_{current_watermark}_{safe_through}_"
            f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_"
            f"{uuid.uuid4().hex[:6]}"
        )
        if not _SAFE_RUN_ID.fullmatch(batch_id):
            raise ValueError("Could not create a valid Phase 09 batch ID")
        pending_batch = {
            "batch_id": batch_id,
            "status": "running",
            "from_processing_id_exclusive": current_watermark,
            "through_processing_id_inclusive": safe_through,
            "new_api_detection_count": len(new_records),
            "affected_date_count": len(affected),
            "affected_dates": [
                {
                    "date_utc": partition.activity_date_utc.isoformat(),
                    "input_record_count": partition.input_record_count,
                    "platform_record_counts": dict(
                        partition.platform_record_counts
                    ),
                    "status": "pending",
                    "table_counts": None,
                    "error": None,
                }
                for partition in affected
            ],
            "source_snapshot_at_discovery": source_after,
            "phase05_reference_data": reference_inputs.manifest,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "error": None,
        }
        checkpoint["pending_batch"] = pending_batch
        save_watermark(checkpoint_path, checkpoint)
        _save_batch_manifest(
            phase09_run_directory / "runs" / batch_id,
            pending_batch,
            base_run_id,
        )

    batch_id = pending_batch["batch_id"]
    saved_reference_snapshot = pending_batch.get("phase05_reference_data")
    if saved_reference_snapshot is None:
        # Upgrade an older pending batch created before Phase 05 snapshots
        # were recorded, so existing work can still resume safely.
        pending_batch["phase05_reference_data"] = reference_inputs.manifest
        save_watermark(checkpoint_path, checkpoint)
    elif saved_reference_snapshot != reference_inputs.manifest:
        return {
            "status": "blocked",
            "batch_id": pending_batch.get("batch_id"),
            "watermark_processing_id": checkpoint[
                "watermark_processing_id"
            ],
            "message": (
                "Phase 05 reference labels changed while this Phase 09 batch "
                "was pending. Restore the recorded label files to resume the "
                "batch, or resolve the pending batch before changing labels."
            ),
        }
    if not _SAFE_RUN_ID.fullmatch(batch_id):
        raise ValueError("Invalid batch ID in Phase 09 checkpoint")
    batch_directory = phase09_run_directory / "runs" / batch_id
    batch_directory.mkdir(parents=True, exist_ok=True)
    if saved_reference_snapshot is None:
        _save_batch_manifest(batch_directory, pending_batch, base_run_id)
    partition_root = batch_directory / "partitions"
    current_run_by_date = checkpoint["current_run_by_date"]

    for date_record in pending_batch["affected_dates"]:
        date_text = date_record["date_utc"]
        activity_date = date.fromisoformat(date_text)
        new_run_id = _partition_run_id(batch_id, activity_date)
        partition_directory = _partition_output_directory(
            batch_directory,
            new_run_id,
        )
        expected_platform_counts = dict(
            date_record["platform_record_counts"]
        )

        if date_record.get("status") == "succeeded":
            counts = _inspect_partition_parquet(
                partition_directory,
                new_run_id,
                activity_date,
                expected_platform_counts,
            )
            _replace_partition_in_database(
                base_database,
                partition_directory,
                new_run_id=new_run_id,
                previous_run_id=current_run_by_date.get(date_text),
                expected_counts=counts,
            )
            current_run_by_date[date_text] = new_run_id
            continue

        # A writer publishes all seven files atomically. Recover that output
        # if a process stopped after publication but before the checkpoint.
        if partition_directory.exists():
            try:
                counts = _inspect_partition_parquet(
                    partition_directory,
                    new_run_id,
                    activity_date,
                    expected_platform_counts,
                )
                previous = current_run_by_date.get(date_text)
                _replace_partition_in_database(
                    base_database,
                    partition_directory,
                    new_run_id=new_run_id,
                    previous_run_id=previous,
                    expected_counts=counts,
                )
                date_record.update({
                    "status": "succeeded",
                    "table_counts": counts,
                    "recovered_published_output": True,
                    "error": None,
                })
                current_run_by_date[date_text] = new_run_id
                save_watermark(checkpoint_path, checkpoint)
                _save_batch_manifest(
                    batch_directory,
                    pending_batch,
                    base_run_id,
                )
                continue
            except Exception as exc:
                date_record["status"] = "failed"
                date_record["error"] = f"Output recovery failed: {type(exc).__name__}: {exc}"
                pending_batch["error"] = date_record["error"]
                save_watermark(checkpoint_path, checkpoint)
                _save_batch_manifest(
                    batch_directory,
                    pending_batch,
                    base_run_id,
                )
                return {
                    "status": "partial",
                    "batch_id": batch_id,
                    "date_utc": date_text,
                    "error": date_record["error"],
                    "watermark_processing_id": checkpoint[
                        "watermark_processing_id"
                    ],
                }

        date_record["status"] = "running"
        date_record["started_at_utc"] = datetime.now(timezone.utc).isoformat()
        date_record["error"] = None
        pending_batch["status"] = "running"
        save_watermark(checkpoint_path, checkpoint)
        _save_batch_manifest(batch_directory, pending_batch, base_run_id)

        from .affected_partition_reprocessing import fetch_affected_date_counts
        source_counts = fetch_affected_date_counts(
            str(database_path),
            [activity_date],
            table=table,
        )
        from ..phase_08_historical_processing.partition_processing import (
            build_archive_partitions,
        )
        owned_source_partitions = build_archive_partitions(
            source_counts,
            start_date=activity_date,
            end_date=activity_date,
        )
        if not owned_source_partitions:
            date_record["status"] = "failed"
            date_record["error"] = (
                "The affected source date disappeared after batch discovery; "
                "the source changed and the watermark was not advanced."
            )
            pending_batch["status"] = "partial"
            pending_batch["error"] = date_record["error"]
            save_watermark(checkpoint_path, checkpoint)
            _save_batch_manifest(batch_directory, pending_batch, base_run_id)
            return {
                "status": "partial",
                "batch_id": batch_id,
                "date_utc": date_text,
                "error": date_record["error"],
                "watermark_processing_id": checkpoint[
                    "watermark_processing_id"
                ],
            }
        partition = owned_source_partitions[0]
        if dict(partition.platform_record_counts) != expected_platform_counts:
            # New API cycles may have completed while an earlier Phase 09
            # batch was waiting to retry. Rebuild this date from the latest
            # stable UNIFIED_DETECTIONS snapshot; the next batch still starts
            # from the saved watermark and will be idempotent.
            expected_platform_counts = dict(partition.platform_record_counts)
            date_record["input_record_count"] = partition.input_record_count
            date_record["platform_record_counts"] = expected_platform_counts
            date_record["source_count_refreshed_at_utc"] = datetime.now(
                timezone.utc
            ).isoformat()
            save_watermark(checkpoint_path, checkpoint)
            _save_batch_manifest(batch_directory, pending_batch, base_run_id)

        snapshot_before_partition = database_snapshot(database_path)
        print(
            f"Phase 09 [{date_text}]: harmonizing "
            f"{partition.input_record_count:,} detections"
        )
        try:
            with tempfile.TemporaryDirectory(
                prefix="phase09-work-",
                dir=batch_directory,
            ) as scratch:
                pipeline_result = run_pipeline(
                    database=str(database_path),
                    output_root=scratch,
                    table=table,
                    experiments=build_threshold_experiments(
                        time_thresholds_minutes=(
                            OPERATIONAL_TIME_THRESHOLD_MINUTES,
                        ),
                        distance_thresholds_km=(
                            OPERATIONAL_DISTANCE_THRESHOLD_KM,
                        ),
                    ),
                    platform_pairs=SUPPORTED_PLATFORM_PAIRS,
                    reference_pairs=reference_inputs.candidate_recall_pairs_by_date.get(
                        activity_date,
                        (),
                    ),
                    activity_reference_labels=(
                        reference_inputs.activity_labels_by_date.get(
                            activity_date,
                            (),
                        )
                    ),
                    algorithm_version="v3-phase09",
                    config_id=phase09_config_id,
                    run_id=new_run_id,
                    n_bootstrap=n_bootstrap,
                    confidence_level=confidence_level,
                    random_seed=random_seed,
                    write_outputs=False,
                    retain_phase06_intermediates=False,
                    acquisition_start_utc=partition.read_start_utc,
                    acquisition_end_utc_exclusive=(
                        partition.read_end_utc_exclusive
                    ),
                )

            if not _source_is_unchanged(
                database_path,
                snapshot_before_partition,
            ):
                raise RuntimeError(
                    "The source database changed during partition processing."
                )

            metadata = pipeline_result.phase07.tables[
                "harm_run_metadata"
            ][0]
            filtered, table_counts = filter_phase07_to_partition(
                pipeline_result.phase07,
                activity_date_utc=activity_date,
                observations=pipeline_result.phase00.observations,
                metadata=metadata,
            )
            duplicates = count_duplicate_observation_identities(
                observation
                for observation in pipeline_result.phase00.observations
                if observation.acquisition_time_utc is not None
                and observation.acquisition_time_utc.astimezone(
                    timezone.utc
                ).date() == activity_date
            )
            phase05_summary = summarize_phase05_results(pipeline_result)
            date_record["phase05_validation"] = phase05_summary
            save_watermark(checkpoint_path, checkpoint)
            _save_batch_manifest(batch_directory, pending_batch, base_run_id)
            write_phase_07_parquet(
                phase07_result=filtered,
                output_root=partition_root,
                run_id=new_run_id,
            )
            published_counts = _inspect_partition_parquet(
                partition_directory,
                new_run_id,
                activity_date,
                expected_platform_counts,
            )
            if published_counts != table_counts:
                raise ValueError(
                    "Published Parquet counts differ from partition results."
                )

            previous_run_id = current_run_by_date.get(date_text)
            _replace_partition_in_database(
                base_database,
                partition_directory,
                new_run_id=new_run_id,
                previous_run_id=previous_run_id,
                expected_counts=published_counts,
            )
            date_record.update({
                "status": "succeeded",
                "table_counts": published_counts,
                "duplicate_input_records": duplicates,
                "phase05_validation": phase05_summary,
                "previous_run_id": previous_run_id,
                "run_id": new_run_id,
                "output_directory": str(partition_directory),
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "error": None,
            })
            current_run_by_date[date_text] = new_run_id
            save_watermark(checkpoint_path, checkpoint)
            _save_batch_manifest(batch_directory, pending_batch, base_run_id)
            print(
                f"Phase 09 [{date_text}]: replaced outputs; "
                f"edges={published_counts['harm_correspondence_edges']:,}, "
                f"clusters={published_counts['harm_activity_clusters']:,}, "
                f"duplicate_inputs={duplicates:,}"
            )
        except Exception as exc:
            cause = exc.__cause__
            error = f"{type(exc).__name__}: {exc}"
            while cause is not None:
                error += f" <- {type(cause).__name__}: {cause}"
                cause = cause.__cause__
            date_record["status"] = "failed"
            date_record["error"] = error[:2000]
            date_record["failed_at_utc"] = datetime.now(timezone.utc).isoformat()
            pending_batch["status"] = "partial"
            pending_batch["error"] = date_record["error"]
            save_watermark(checkpoint_path, checkpoint)
            _save_batch_manifest(batch_directory, pending_batch, base_run_id)
            return {
                "status": "partial",
                "batch_id": batch_id,
                "date_utc": date_text,
                "error": date_record["error"],
                "failed_stage": (
                    exc.failed_stage
                    if isinstance(exc, PipelineExecutionError)
                    else "phase09_partition"
                ),
                "watermark_processing_id": checkpoint[
                    "watermark_processing_id"
                ],
            }

    pending_batch["status"] = "success"
    pending_batch["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    pending_batch["error"] = None
    _save_batch_manifest(batch_directory, pending_batch, base_run_id)

    checkpoint["watermark_processing_id"] = int(
        pending_batch["through_processing_id_inclusive"]
    )
    checkpoint["watermark_time_utc"] = datetime.now(timezone.utc).isoformat()
    checkpoint["last_completed_batch_id"] = batch_id
    checkpoint["last_completed_batch_at_utc"] = datetime.now(
        timezone.utc
    ).isoformat()
    checkpoint["pending_batch"] = None
    save_watermark(checkpoint_path, checkpoint)

    return {
        "status": "success",
        "phase08_run_id": base_run_id,
        "batch_id": batch_id,
        "watermark_processing_id": checkpoint["watermark_processing_id"],
        "new_api_detection_count": pending_batch["new_api_detection_count"],
        "affected_date_count": pending_batch["affected_date_count"],
        "checkpoint": str(checkpoint_path),
        "harmonization_database": str(base_database),
    }
