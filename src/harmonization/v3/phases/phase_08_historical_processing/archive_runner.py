"""Resumable Phase 08 historical processing over existing unified detections."""

from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
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
    DEFAULT_ACTIVITY_DISTANCE_THRESHOLDS_KM,
    OPERATIONAL_DISTANCE_THRESHOLD_KM,
    OPERATIONAL_TIME_THRESHOLD_MINUTES,
)
from ...phases.phase_00_input_audit.schema_validation import validate_schema
from ...phases.phase_03_candidate_generation.candidate_generator import (
    SUPPORTED_PLATFORM_PAIRS,
)
from ...phases.phase_06_common_support_frp.runner import (
    SPATIAL_RESOLUTIONS_KM,
    TEMPORAL_WINDOWS_MINUTES,
)
from ...phases.phase_07_output_generation.schemas import OUTPUT_SCHEMAS
from ...phases.phase_05_validation.reference_data import (
    load_phase05_reference_inputs,
    summarize_phase05_results,
)
from ...pipeline.orchestrator import PipelineExecutionError, run_pipeline
from ...storage.duckdb_manager import open_database
from ...storage.parquet_writer import write_phase_07_parquet
from .partition_processing import (
    HALO_MINUTES,
    build_archive_partitions,
    canonical_platform,
    count_duplicate_observation_identities,
    find_coverage_gaps,
)


DEFAULT_TABLE = "UNIFIED_DETECTIONS"
DEFAULT_N_BOOTSTRAP = 1000
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class SourceChangedError(RuntimeError):
    """Raised if the source DuckDB changes during a historical run."""


def _quote_identifier(value: str) -> str:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return f'"{value}"'


def _quote_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def database_snapshot(database: str | Path) -> dict[str, Any]:
    """Fingerprint the database and DuckDB WAL without reading or writing it."""
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"DuckDB source database not found: {path}")

    items = {}
    for label, candidate in (
        ("database", path),
        ("wal", Path(str(path) + ".wal")),
    ):
        if candidate.exists():
            stat = candidate.stat()
            items[label] = {
                "path": str(candidate),
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }
        else:
            items[label] = None
    return items


def audit_historical_source(
    database: str | Path,
    *,
    table: str = DEFAULT_TABLE,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """Audit platform/date coverage using small SQL aggregates, read-only."""
    if not _SAFE_IDENTIFIER.fullmatch(table):
        raise ValueError(f"Invalid table identifier: {table!r}")
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    table_sql = _quote_identifier(table)
    with open_database(database, read_only=True) as connection:
        description = connection.execute(
            f"DESCRIBE {table_sql}"
        ).fetchall()
        columns = [row[0] for row in description]
        types = {row[0]: row[1] for row in description}
        validation = validate_schema(columns, types)
        if not validation.valid:
            raise ValueError(validation.summary())

        where = ["acquisition_time_utc IS NOT NULL"]
        parameters: list[Any] = []
        if start_date is not None:
            where.append("CAST(acquisition_time_utc AS DATE) >= ?")
            parameters.append(start_date)
        if end_date is not None:
            where.append("CAST(acquisition_time_utc AS DATE) <= ?")
            parameters.append(end_date)

        rows = connection.execute(
            f"SELECT CAST(acquisition_time_utc AS DATE) AS date_utc, "
            "platform, COUNT(*) AS record_count "
            f"FROM {table_sql} WHERE {' AND '.join(where)} "
            "GROUP BY 1, 2 ORDER BY 1, 2",
            parameters,
        ).fetchall()
        api_watermark_row = connection.execute(
            """
            SELECT COALESCE(MAX(pr.processing_id), 0), MAX(pr.start_time)
            FROM PROCESSING_RUNS AS pr
            JOIN SOURCE_FILES AS sf ON sf.file_id = pr.input_file_id
            WHERE sf.source_type = 'API'
              AND pr.status = 'COMPLETED'
            """
        ).fetchone()

    date_platform_counts = [
        {
            "date_utc": row[0].isoformat(),
            "platform": row[1],
            "record_count": int(row[2]),
        }
        for row in rows
    ]
    partitions = build_archive_partitions(
        date_platform_counts,
        start_date=start_date,
        end_date=end_date,
    )
    if not partitions:
        raise ValueError(
            "No supported UNIFIED_DETECTIONS records were found in the "
            "requested date range."
        )
    present_dates = [item.activity_date_utc for item in partitions]

    platform_totals: dict[str, int] = {}
    unsupported_platform_totals: dict[str, int] = {}
    platform_dates: dict[str, set[date]] = {}
    for item in date_platform_counts:
        canonical = canonical_platform(item["platform"])
        bucket = platform_totals if canonical else unsupported_platform_totals
        label = canonical if canonical else str(item["platform"] or "<NULL>")
        bucket[label] = bucket.get(label, 0) + item["record_count"]
        if canonical:
            platform_dates.setdefault(canonical, set()).add(
                date.fromisoformat(item["date_utc"])
            )

    global_start = present_dates[0]
    global_end = present_dates[-1]
    platform_coverage = {}
    for platform, dates in sorted(platform_dates.items()):
        ordered = sorted(dates)
        platform_coverage[platform] = {
            "first_available_date": ordered[0].isoformat(),
            "last_available_date": ordered[-1].isoformat(),
            "active_date_count": len(ordered),
            "coverage_gaps": find_coverage_gaps(
                ordered,
                start_date=global_start,
                end_date=global_end,
            ),
        }

    return {
        "table": table,
        "date_filter": {
            "start_inclusive": start_date.isoformat() if start_date else None,
            "end_inclusive": end_date.isoformat() if end_date else None,
        },
        "first_available_date": present_dates[0].isoformat(),
        "last_available_date": present_dates[-1].isoformat(),
        "active_date_count": len(present_dates),
        "supported_record_count": sum(
            item.input_record_count for item in partitions
        ),
        "api_processing_watermark": int(api_watermark_row[0] or 0),
        "api_processing_watermark_time_utc": (
            api_watermark_row[1].replace(tzinfo=timezone.utc).isoformat()
            if api_watermark_row[1] is not None
            else None
        ),
        "platform_totals": dict(sorted(platform_totals.items())),
        "platform_coverage": platform_coverage,
        "unsupported_platform_totals": dict(
            sorted(unsupported_platform_totals.items())
        ),
        "date_platform_counts": date_platform_counts,
        "available_dates": [item.isoformat() for item in present_dates],
        "coverage_gaps": find_coverage_gaps(present_dates),
        "partitions": [
            {
                "date_utc": item.activity_date_utc.isoformat(),
                "input_record_count": item.input_record_count,
                "platform_record_counts": dict(item.platform_record_counts),
                "read_start_utc": item.read_start_utc.isoformat(),
                "read_end_utc_exclusive": (
                    item.read_end_utc_exclusive.isoformat()
                ),
            }
            for item in partitions
        ],
    }


def _write_json_atomic(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(content, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _make_config(
    *,
    database: str | Path,
    table: str,
    source_snapshot: dict[str, Any],
    audit: dict[str, Any],
    n_bootstrap: int,
    confidence_level: float,
    random_seed: int,
) -> dict[str, Any]:
    return {
        "database": str(Path(database).expanduser().resolve()),
        "table": table,
        "source_snapshot": source_snapshot,
        "selected_thresholds": {
            "temporal_minutes": OPERATIONAL_TIME_THRESHOLD_MINUTES,
            "spatial_km": OPERATIONAL_DISTANCE_THRESHOLD_KM,
        },
        "platform_pairs": [list(pair) for pair in SUPPORTED_PLATFORM_PAIRS],
        "activity_distance_thresholds_km": list(
            DEFAULT_ACTIVITY_DISTANCE_THRESHOLDS_KM
        ),
        "frp_spatial_resolutions_km": list(SPATIAL_RESOLUTIONS_KM),
        "frp_temporal_windows_minutes": list(TEMPORAL_WINDOWS_MINUTES),
        "halo_minutes": HALO_MINUTES,
        "partition_unit": "UTC day",
        "n_bootstrap": n_bootstrap,
        "confidence_level": confidence_level,
        "random_seed": random_seed,
        "date_filter": audit["date_filter"],
        "available_dates": audit["available_dates"],
    }


def _source_is_unchanged(database: str | Path, expected: dict[str, Any]) -> bool:
    return database_snapshot(database) == expected


def _run_id_for_partition(run_id: str, activity_date: date) -> str:
    return f"{run_id}_{activity_date:%Y%m%d}"


def _exception_chain_text(error: BaseException) -> str:
    messages = []
    current: BaseException | None = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return " <- ".join(messages)


def _partition_quality_summary(pipeline_result: Any, activity_date: date) -> dict[str, Any]:
    from collections import Counter

    observations = pipeline_result.phase00.observations
    qc_by_identity = {
        (item.observation.platform, str(item.observation.detection_id)): item
        for item in pipeline_result.phase01.results
    }
    mapping_issues = Counter()
    qc_issues = Counter()
    qc_warnings = Counter()
    spatial_eligible = 0
    frp_eligible = 0
    brightness_eligible = 0
    core_count = 0

    for observation in observations:
        timestamp = observation.acquisition_time_utc
        if timestamp is None or timestamp.astimezone(timezone.utc).date() != activity_date:
            continue
        core_count += 1
        mapping_issues.update(observation.mapping_issues)
        qc_result = qc_by_identity[(
            observation.platform,
            str(observation.detection_id),
        )]
        qc_issues.update(qc_result.qc_issues)
        qc_warnings.update(qc_result.qc_warnings)
        spatial_eligible += int(qc_result.eligible_for_spatial_matching)
        frp_eligible += int(qc_result.eligible_for_frp_analysis)
        brightness_eligible += int(qc_result.eligible_for_brightness_analysis)

    return {
        "input_records_assessed": core_count,
        "mapping_issue_counts": dict(sorted(mapping_issues.items())),
        "qc_issue_counts": dict(sorted(qc_issues.items())),
        "qc_warning_counts": dict(sorted(qc_warnings.items())),
        "spatial_eligible_count": spatial_eligible,
        "frp_eligible_count": frp_eligible,
        "brightness_eligible_count": brightness_eligible,
        "phase05_validation_status": pipeline_result.phase05_status,
        "phase05_skipped_validation_types": list(
            pipeline_result.skipped_validation_types
        ),
        "phase05_results": summarize_phase05_results(pipeline_result),
    }


def _partition_output_directory(
    run_directory: Path,
    partition_run_id: str,
) -> Path:
    return run_directory / "partitions" / partition_run_id


def _inspect_partition_parquet(
    output_directory: Path,
    partition_run_id: str,
    activity_date_utc: date,
    expected_platform_counts: dict[str, int],
) -> dict[str, int]:
    """Validate one atomically published set of seven partition Parquets."""
    paths = {
        table_name: output_directory / f"{table_name}.parquet"
        for table_name in OUTPUT_SCHEMAS
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Partition output is incomplete; missing: " + ", ".join(missing)
        )

    connection = duckdb.connect(database=":memory:")
    counts = {}
    try:
        for table_name, path in paths.items():
            description = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(" + _quote_string(path) + ")"
            ).fetchall()
            actual_columns = [row[0] for row in description]
            expected_columns = [
                column.name for column in OUTPUT_SCHEMAS[table_name]
            ]
            if actual_columns != expected_columns:
                raise ValueError(
                    f"Unexpected columns in {path.name}: {actual_columns}"
                )
            actual_types = [row[1].upper() for row in description]
            expected_types = [
                column.data_type for column in OUTPUT_SCHEMAS[table_name]
            ]
            if actual_types != expected_types:
                raise ValueError(
                    f"Unexpected data types in {path.name}: {actual_types}"
                )

            count, foreign_run_count = connection.execute(
                "SELECT COUNT(*), "
                "COUNT(*) FILTER (WHERE run_id <> ?) "
                "FROM read_parquet(" + _quote_string(path) + ")",
                [partition_run_id],
            ).fetchone()
            if foreign_run_count:
                raise ValueError(
                    f"{path.name} contains rows from another run_id"
                )
            counts[table_name] = int(count)

        metadata = connection.execute(
            "SELECT status, input_count, candidate_count, "
            "correspondence_edge_count, activity_cluster_count "
            "FROM read_parquet(" +
            _quote_string(paths["harm_run_metadata"]) + ")"
        ).fetchall()
        if len(metadata) != 1 or metadata[0][0] != "success":
            raise ValueError(
                f"Invalid success metadata in {paths['harm_run_metadata']}"
            )
        if metadata[0][1] != sum(expected_platform_counts.values()):
            raise ValueError("Run metadata input count does not match the source audit")
        if metadata[0][2] != counts["harm_correspondence_edges"]:
            raise ValueError("Run metadata candidate count does not match saved edges")
        if metadata[0][3] != counts["harm_correspondence_edges"]:
            raise ValueError("Run metadata edge count does not match saved edges")
        if metadata[0][4] != counts["harm_activity_clusters"]:
            raise ValueError("Run metadata cluster count does not match saved clusters")

        date_columns = {
            "harm_activity_clusters": "activity_date_utc",
            "harm_sensor_activity_daily": "date_utc",
            "harm_correspondence_summary": "date_utc",
            "harm_frp_comparisons": "date_utc",
        }
        for table_name, column_name in date_columns.items():
            date_sql = _quote_identifier(column_name)
            outside_count = connection.execute(
                "SELECT COUNT(*) FILTER (WHERE " + date_sql + " <> ?) "
                "FROM read_parquet(" + _quote_string(paths[table_name]) + ")",
                [activity_date_utc],
            ).fetchone()[0]
            if outside_count:
                raise ValueError(
                    f"{table_name} contains rows outside {activity_date_utc}"
                )

        platform_rows = connection.execute(
            "SELECT platform, SUM(detection_count) "
            "FROM read_parquet(" +
            _quote_string(paths["harm_sensor_activity_daily"]) + ") "
            "GROUP BY platform"
        ).fetchall()
        actual_platform_counts = {
            platform: int(record_count)
            for platform, record_count in platform_rows
        }
        if actual_platform_counts != expected_platform_counts:
            raise ValueError(
                "Daily detection counts do not match the source audit: "
                f"{actual_platform_counts} != {expected_platform_counts}"
            )

        orphan_members = connection.execute(
            "SELECT COUNT(*) FROM read_parquet(" +
            _quote_string(paths["harm_cluster_members"]) + ") AS members "
            "LEFT JOIN read_parquet(" +
            _quote_string(paths["harm_activity_clusters"]) + ") AS clusters "
            "USING (activity_cluster_id) "
            "WHERE clusters.activity_cluster_id IS NULL"
        ).fetchone()[0]
        if orphan_members:
            raise ValueError("Cluster membership output has orphan cluster IDs")
    finally:
        connection.close()
    return counts


def _table_names(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }


def _append_partition_to_duckdb(
    output_database: Path,
    partition_directory: Path,
    partition_run_id: str,
    expected_counts: dict[str, int],
) -> bool:
    """Append all partition tables in one transaction; return whether added."""
    output_database.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(output_database))
    try:
        names = _table_names(connection)
        metadata_exists = "harm_run_metadata" in names
        if metadata_exists:
            existing = connection.execute(
                'SELECT COUNT(*) FROM "harm_run_metadata" WHERE run_id = ?',
                [partition_run_id],
            ).fetchone()[0]
            if existing:
                actual_counts = {}
                for table_name in OUTPUT_SCHEMAS:
                    if table_name not in names:
                        raise ValueError(
                            f"Output DuckDB is missing table {table_name}"
                        )
                    actual_counts[table_name] = int(connection.execute(
                        f"SELECT COUNT(*) FROM {_quote_identifier(table_name)} "
                        "WHERE run_id = ?",
                        [partition_run_id],
                    ).fetchone()[0])
                if actual_counts != expected_counts:
                    raise ValueError(
                        "Partition rows already exist in output DuckDB but "
                        "their counts do not match the Parquet files."
                    )
                return False

        # A previous manual edit or partial non-transactional writer must not
        # be silently doubled. Our own append uses one transaction for all 7.
        for table_name in names.intersection(OUTPUT_SCHEMAS):
            present = connection.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table_name)} "
                "WHERE run_id = ?",
                [partition_run_id],
            ).fetchone()[0]
            if present:
                raise ValueError(
                    f"Found orphan rows for {partition_run_id} in {table_name}"
                )

        connection.execute("BEGIN TRANSACTION")
        try:
            for table_name, expected_count in expected_counts.items():
                parquet_path = (
                    partition_directory / f"{table_name}.parquet"
                )
                parquet_sql = _quote_string(parquet_path)
                if table_name not in names:
                    connection.execute(
                        f"CREATE TABLE {_quote_identifier(table_name)} AS "
                        f"SELECT * FROM read_parquet({parquet_sql}) WHERE FALSE"
                    )
                    names.add(table_name)

                connection.execute(
                    f"INSERT INTO {_quote_identifier(table_name)} "
                    f"SELECT * FROM read_parquet({parquet_sql})"
                )
                actual_count = int(connection.execute(
                    f"SELECT COUNT(*) FROM {_quote_identifier(table_name)} "
                    "WHERE run_id = ?",
                    [partition_run_id],
                ).fetchone()[0])
                if actual_count != expected_count:
                    raise ValueError(
                        f"{table_name} DuckDB row count {actual_count} "
                        f"does not match Parquet count {expected_count}"
                    )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return True
    finally:
        connection.close()


def _validate_output_database(
    output_database: Path,
    expected_counts: dict[str, int],
) -> dict[str, int]:
    connection = duckdb.connect(str(output_database), read_only=True)
    try:
        names = _table_names(connection)
        missing = sorted(set(OUTPUT_SCHEMAS) - names)
        if missing:
            raise ValueError(
                f"Output DuckDB is missing tables: {missing}"
            )
        actual = {
            table_name: int(connection.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}"
            ).fetchone()[0])
            for table_name in OUTPUT_SCHEMAS
        }
        if actual != expected_counts:
            raise ValueError(
                f"Output DuckDB row counts differ from manifest: {actual}"
            )
        return actual
    finally:
        connection.close()


def _make_partition_metadata(
    run_id: str,
    status: str,
    audit: dict[str, Any],
    config: dict[str, Any],
    source_snapshot: dict[str, Any],
    partitions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "phase": "08_full_historical_processing",
        "run_id": run_id,
        "status": status,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": source_snapshot,
        "configuration": config,
        "source_audit": audit,
        "partitions": partitions,
    }


def run_phase_08(
    *,
    database: str | Path,
    output_root: str | Path,
    table: str = DEFAULT_TABLE,
    run_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    retry_failed: bool = False,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    confidence_level: float = 0.95,
    random_seed: int = 42,
) -> dict[str, Any]:
    """Run/resume Phase 08. The source DuckDB is opened read-only throughout."""
    if run_id is None:
        run_id = (
            "phase08_"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "_"
            + uuid.uuid4().hex[:6]
        )
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id may contain only letters, digits, '.', '_' and '-'")
    if isinstance(n_bootstrap, bool) or not isinstance(n_bootstrap, int) or n_bootstrap < 1:
        raise ValueError("n_bootstrap must be a positive integer")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be between zero and one")

    database_path = Path(database).expanduser().resolve()
    output_root = Path(output_root).expanduser().resolve()
    print(f"Phase 08: auditing {database_path} read-only")
    source_before_audit = database_snapshot(database_path)
    audit = audit_historical_source(
        database_path,
        table=table,
        start_date=start_date,
        end_date=end_date,
    )
    source_after_audit = database_snapshot(database_path)
    if source_before_audit != source_after_audit:
        raise SourceChangedError(
            "The source DuckDB changed during the Phase 08 audit. Stop its "
            "writer and rerun the command."
        )

    reference_inputs = load_phase05_reference_inputs()
    config = _make_config(
        database=database_path,
        table=table,
        source_snapshot=source_after_audit,
        audit=audit,
        n_bootstrap=n_bootstrap,
        confidence_level=confidence_level,
        random_seed=random_seed,
    )
    config["phase05_reference_data"] = reference_inputs.manifest
    config_hash = sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    phase_config_id = f"phase08-v3-{config_hash}"

    run_directory = output_root / run_id
    manifest_path = run_directory / "phase08_manifest.json"
    output_database = run_directory / "harmonization.duckdb"
    planned_dates = audit["available_dates"]

    if run_directory.exists():
        if not manifest_path.is_file():
            raise FileExistsError(
                f"Run directory already exists without a resume manifest: "
                f"{run_directory}"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("configuration") != config:
            raise ValueError(
                "The saved Phase 08 run does not match the current source "
                "snapshot or settings. Use a new --run-id for a new backfill."
            )
        existing_dates = [
            item.get("date_utc") for item in manifest.get("partitions", [])
        ]
        if existing_dates != planned_dates:
            raise ValueError("Saved Phase 08 partition plan does not match the source audit")
    else:
        run_directory.mkdir(parents=True)
        manifest = _make_partition_metadata(
            run_id,
            "running",
            audit,
            config,
            source_after_audit,
            [
                {
                    "date_utc": item["date_utc"],
                    "input_record_count": item["input_record_count"],
                    "platform_record_counts": item["platform_record_counts"],
                    "status": "pending",
                    "table_counts": None,
                    "duplicate_input_records": None,
                    "error": None,
                }
                for item in audit["partitions"]
            ],
        )
        _write_json_atomic(manifest_path, manifest)

    manifest["status"] = "running"
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    for item in manifest["partitions"]:
        if item.get("status") == "running":
            item["status"] = "pending"
            item["error"] = "Previous execution stopped before publishing this partition."
    _write_json_atomic(manifest_path, manifest)
    print(f"Phase 08 run_id: {run_id}")
    print(f"Manifest: {manifest_path}")

    date_counts = audit["date_platform_counts"]
    archive_partitions = build_archive_partitions(
        date_counts,
        start_date=start_date,
        end_date=end_date,
    )
    partition_by_date = {
        item.activity_date_utc.isoformat(): item
        for item in archive_partitions
    }
    state_by_date = {
        item["date_utc"]: item for item in manifest["partitions"]
    }
    stop_reason = None

    for index, date_text in enumerate(planned_dates, start=1):
        state = state_by_date[date_text]
        partition = partition_by_date[date_text]
        partition_run_id = _run_id_for_partition(
            run_id,
            partition.activity_date_utc,
        )
        partition_directory = _partition_output_directory(
            run_directory,
            partition_run_id,
        )

        if state["status"] == "succeeded":
            try:
                counts = _inspect_partition_parquet(
                    partition_directory,
                    partition_run_id,
                    partition.activity_date_utc,
                    dict(partition.platform_record_counts),
                )
                _append_partition_to_duckdb(
                    output_database,
                    partition_directory,
                    partition_run_id,
                    counts,
                )
                state["table_counts"] = counts
            except Exception as exc:
                state["status"] = "failed"
                state["error"] = f"Saved output validation failed: {type(exc).__name__}: {exc}"
                state["failed_at_utc"] = datetime.now(timezone.utc).isoformat()
                _write_json_atomic(manifest_path, manifest)
                if not retry_failed:
                    print(f"[{index}/{len(planned_dates)}] {date_text}: saved output invalid; use --retry-failed")
                    continue

        if state["status"] == "failed" and not retry_failed:
            print(f"[{index}/{len(planned_dates)}] {date_text}: skipped failed partition; use --retry-failed")
            continue

        if not _source_is_unchanged(database_path, source_after_audit):
            stop_reason = (
                "Source DuckDB changed during the run; remaining partitions "
                "were not processed."
            )
            manifest["source_change_detected"] = stop_reason
            break

        # A crash after atomic Parquet publication can resume from the files
        # without repeating the expensive harmonization phases.
        if partition_directory.exists() and state["status"] != "succeeded":
            try:
                counts = _inspect_partition_parquet(
                    partition_directory,
                    partition_run_id,
                    partition.activity_date_utc,
                    dict(partition.platform_record_counts),
                )
                _append_partition_to_duckdb(
                    output_database,
                    partition_directory,
                    partition_run_id,
                    counts,
                )
                state.update({
                    "status": "succeeded",
                    "table_counts": counts,
                    "recovered_published_output": True,
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                    "error": None,
                })
                state.pop("failed_at_utc", None)
                state.pop("failed_stage", None)
                _write_json_atomic(manifest_path, manifest)
                print(f"[{index}/{len(planned_dates)}] {date_text}: recovered published outputs")
                continue
            except Exception as exc:
                state["status"] = "failed"
                state["error"] = f"Published output recovery failed: {type(exc).__name__}: {exc}"
                state["failed_at_utc"] = datetime.now(timezone.utc).isoformat()
                _write_json_atomic(manifest_path, manifest)
                print(f"[{index}/{len(planned_dates)}] {date_text}: output recovery failed")
                if not retry_failed:
                    continue
                raise RuntimeError(
                    f"Cannot safely retry {date_text}; its output directory is "
                    "incomplete or inconsistent. Preserve it for inspection."
                ) from exc

        state["status"] = "running"
        state["started_at_utc"] = datetime.now(timezone.utc).isoformat()
        state["error"] = None
        _write_json_atomic(manifest_path, manifest)
        print(
            f"[{index}/{len(planned_dates)}] {date_text}: "
            f"processing {partition.input_record_count:,} core detections"
        )

        try:
            with tempfile.TemporaryDirectory(
                prefix="phase08-work-",
                dir=run_directory,
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
                        partition.activity_date_utc,
                        (),
                    ),
                    activity_reference_labels=(
                        reference_inputs.activity_labels_by_date.get(
                            partition.activity_date_utc,
                            (),
                        )
                    ),
                    n_bootstrap=n_bootstrap,
                    confidence_level=confidence_level,
                    random_seed=random_seed,
                    algorithm_version="v3-phase08",
                    config_id=phase_config_id,
                    run_id=partition_run_id,
                    write_outputs=False,
                    retain_phase06_intermediates=False,
                    acquisition_start_utc=partition.read_start_utc,
                    acquisition_end_utc_exclusive=(
                        partition.read_end_utc_exclusive
                    ),
                )

            if not _source_is_unchanged(database_path, source_after_audit):
                raise SourceChangedError(
                    "Source DuckDB changed while this partition was running."
                )

            from .partition_processing import filter_phase07_to_partition

            metadata = pipeline_result.phase07.tables["harm_run_metadata"][0]
            filtered_phase07, counts = filter_phase07_to_partition(
                pipeline_result.phase07,
                activity_date_utc=partition.activity_date_utc,
                observations=pipeline_result.phase00.observations,
                metadata=metadata,
            )
            duplicates = count_duplicate_observation_identities(
                observation
                for observation in pipeline_result.phase00.observations
                if observation.acquisition_time_utc is not None
                and observation.acquisition_time_utc.astimezone(
                    timezone.utc
                ).date() == partition.activity_date_utc
            )
            quality_summary = _partition_quality_summary(
                pipeline_result,
                partition.activity_date_utc,
            )
            state["quality_summary"] = quality_summary
            _write_json_atomic(manifest_path, manifest)
            write_phase_07_parquet(
                phase07_result=filtered_phase07,
                output_root=run_directory / "partitions",
                run_id=partition_run_id,
            )
            published_counts = _inspect_partition_parquet(
                partition_directory,
                partition_run_id,
                partition.activity_date_utc,
                dict(partition.platform_record_counts),
            )
            if published_counts != counts:
                raise ValueError(
                    "Published Parquet row counts differ from in-memory "
                    "partition output."
                )
            _append_partition_to_duckdb(
                output_database,
                partition_directory,
                partition_run_id,
                published_counts,
            )
            state.update({
                "status": "succeeded",
                "table_counts": counts,
                "duplicate_input_records": duplicates,
                "quality_summary": quality_summary,
                "output_directory": str(partition_directory),
                "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "error": None,
            })
            state.pop("failed_at_utc", None)
            state.pop("failed_stage", None)
            _write_json_atomic(manifest_path, manifest)
            print(
                f"[{index}/{len(planned_dates)}] {date_text}: done; "
                f"edges={counts['harm_correspondence_edges']:,}, "
                f"clusters={counts['harm_activity_clusters']:,}, "
                f"duplicate_inputs={duplicates:,}"
            )
        except Exception as exc:
            state["status"] = "failed"
            failed_stage = (
                exc.failed_stage if isinstance(exc, PipelineExecutionError)
                else "phase08_partition"
            )
            state["failed_stage"] = failed_stage
            error_text = _exception_chain_text(exc)
            state["error"] = error_text[:2000]
            state["failed_at_utc"] = datetime.now(timezone.utc).isoformat()
            _write_json_atomic(manifest_path, manifest)
            print(f"[{index}/{len(planned_dates)}] {date_text}: FAILED at {failed_stage}: {error_text}")
            if isinstance(exc, SourceChangedError):
                stop_reason = str(exc)
                break
            lowered_error = error_text.lower()
            if "being used by another process" in lowered_error or "lock" in lowered_error:
                stop_reason = (
                    "DuckDB could not be read or written because another "
                    "process holds a database lock. Close DuckDB CLI and stop "
                    "API ingestion, then resume this run."
                )
                manifest["stop_reason"] = stop_reason
                break
            if "out of memory" in lowered_error or "memoryerror" in lowered_error:
                stop_reason = (
                    "The current date partition exceeded available memory. "
                    "The remaining partitions were not started."
                )
                manifest["stop_reason"] = stop_reason
                break

    for table_name in OUTPUT_SCHEMAS:
        expected_total = sum(
            int((item.get("table_counts") or {}).get(table_name, 0))
            for item in manifest["partitions"]
            if item.get("status") == "succeeded"
        )
        manifest.setdefault("output_table_counts", {})[table_name] = expected_total

    succeeded = sum(item.get("status") == "succeeded" for item in manifest["partitions"])
    failed = sum(item.get("status") == "failed" for item in manifest["partitions"])
    pending = sum(
        item.get("status") == "pending"
        for item in manifest["partitions"]
    )
    if output_database.is_file() and succeeded:
        actual_counts = _validate_output_database(
            output_database,
            manifest["output_table_counts"],
        )
        manifest["output_database_validated"] = True
        manifest["output_table_counts"] = actual_counts
    manifest["status"] = "success" if succeeded == len(manifest["partitions"]) else "partial"
    manifest["partition_summary"] = {
        "total": len(manifest["partitions"]),
        "succeeded": succeeded,
        "failed": failed,
        "pending": pending,
    }
    manifest["stop_reason"] = stop_reason
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(manifest_path, manifest)
    return manifest
