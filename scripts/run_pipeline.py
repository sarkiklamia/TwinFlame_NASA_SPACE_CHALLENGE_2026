
"""
TwinFlame / PyroSync â€” reproducible pipeline orchestrator.

Pipeline:
    1. Discover immutable raw inputs.
    2. Register ingestion runs and source files.
    3. Register processing runs.
    4. Execute cleaning SQL.
    5. Execute standardization SQL.
    6. Generate deterministic detection IDs.
    7. Attach file_id and processing_id to the canonical Parquet.
    8. Rebuild UNIFIED_DETECTIONS.
    9. Validate the final Parquet and database.

Rerun strategy:
    Full refresh from raw inputs.
    Metadata registration is checksum-based and idempotent.
    Detection IDs are deterministic.
    Temporary outputs are validated before promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb


# ---------------------------------------------------------------------------
# PROJECT CONFIGURATION
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]

DB_PATH = ROOT / "database" / "twinflame.duckdb"

RAW_SAMPLE_DIR = ROOT / "data" / "raw" / "sample"
RAW_ARCHIVE_DIR = ROOT / "data" / "raw" / "archive"
RAW_API_DIR = ROOT / "data" / "raw" / "api"

CLEANED_DIR = ROOT / "data" / "processed" / "cleaned"
QUARANTINE_DIR = ROOT / "data" / "processed" / "quarantine"
REPORT_DIR = ROOT / "data" / "processed" / "reports"

CLEANED_PARQUET = CLEANED_DIR / "cleaned_detections.parquet"
STANDARDIZED_TMP = CLEANED_DIR / "cleaned_detections.standardizing.tmp.parquet"
IDS_TMP = CLEANED_DIR / "detections_with_ids.tmp.parquet"
FINAL_TMP = CLEANED_DIR / "cleaned_detections.final.tmp.parquet"

SQL_CLEANING = ROOT / "sql" / "cleaning" / "01_clean_sources.sql"
SQL_STANDARDIZATION = (
    ROOT / "sql" / "standardization" / "01_standardize_cleaned.sql"
)
SQL_DETECTION_IDS = (
    ROOT / "sql" / "preprocessing" / "01_generate_detection_ids.sql"
)
SQL_INITIALIZE_DB = ROOT / "sql" / "database" / "01_initialize_database.sql"

PROCESSING_VERSION = "pyrosync-pipeline-v1"

EXPECTED_DETECTION_COLUMNS = {
    "detection_id",
    "source_file",
    "source_type",
    "file_id",
    "processing_id",
    "ingested_at",
    "processing_level",
    "source",
    "platform",
    "sensor",
    "latitude",
    "longitude",
    "acquisition_time_utc",
    "confidence_native",
    "confidence_class",
    "frp_mw",
    "brightness",
    "bright_t31",
    "bright_ti4",
    "bright_ti5",
    "scan_km",
    "track_km",
    "daynight",
    "product_version",
    "quality_flags",
}

DB_INSERT_COLUMNS = [
    "detection_id",
    "file_id",
    "processing_id",
    "ingested_at",
    "processing_level",
    "source",
    "platform",
    "sensor",
    "latitude",
    "longitude",
    "acquisition_time_utc",
    "confidence_native",
    "confidence_class",
    "frp_mw",
    "brightness_native",
    "bright_t31",
    "bright_ti4",
    "bright_ti5",
    "scan",
    "track",
    "daynight",
    "product_version",
    "quality_flags",
]


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger("pyrosync.pipeline")


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InputFile:
    path: Path
    filename: str
    source_type: str
    platform: str | None
    checksum: str


# ---------------------------------------------------------------------------
# GENERAL HELPERS
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Required file not found: {path}")


def ensure_directories() -> None:
    for directory in (
        DB_PATH.parent,
        CLEANED_DIR,
        QUARANTINE_DIR,
        REPORT_DIR,
        LOG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def normalize_filename(value: str) -> str:
    return Path(str(value).replace("\\", "/")).name


def infer_platform(path: Path) -> str | None:
    """
    Infer platform from the filename or parent directory.

    Supported examples:
        J1V-C2_2026_July.csv -> VIIRS_NOAA20
        J2V-C2_2026_July.csv -> VIIRS_NOAA21
        SV-C2_2026_July.csv  -> VIIRS_SNPP
        M-C61_2026_July.csv  -> MODIS
    """
    name = path.name.upper()
    parent = path.parent.name.upper()

    combined = f"{parent} {name}"

    if "J1V" in combined or "NOAA20" in combined:
        return "VIIRS_NOAA20"

    if "J2V" in combined or "NOAA21" in combined:
        return "VIIRS_NOAA21"

    if re.search(r"\bSV\b", combined) or "SNPP" in combined:
        return "VIIRS_SNPP"

    if "MODIS" in combined or re.search(r"\bM-C", combined):
        return "MODIS"

    return None


def discover_inputs() -> list[InputFile]:
    """
    Discover archive/sample CSV files and API Parquet files.

    Raw files are never modified by this orchestrator.
    """
    candidates: list[tuple[Path, str]] = []

    for directory in (RAW_SAMPLE_DIR, RAW_ARCHIVE_DIR):
        if directory.exists():
            candidates.extend(
                (path, "ARCHIVE")
                for path in directory.rglob("*.csv")
                if path.is_file()
            )

    if RAW_API_DIR.exists():
        candidates.extend(
            (path, "API")
            for path in RAW_API_DIR.rglob("*.parquet")
            if path.is_file()
        )

    candidates.sort(key=lambda item: str(item[0]).lower())

    if not candidates:
        raise RuntimeError(
            "No input files found. Expected CSV files in "
            "data/raw/sample or data/raw/archive, and API Parquet "
            "files in data/raw/api."
        )

    # SOURCE_FILES currently identifies files by filename.
    # Reject basename collisions instead of associating detections
    # with the wrong source file.
    seen_names: dict[str, Path] = {}
    inputs: list[InputFile] = []

    for path, source_type in candidates:
        filename = path.name
        key = filename.casefold()

        if key in seen_names and seen_names[key] != path:
            raise RuntimeError(
                "Two raw files have the same filename. The current "
                "SOURCE_FILES schema identifies files by filename, so "
                "this would make provenance ambiguous:\n"
                f"  {seen_names[key]}\n"
                f"  {path}"
            )

        seen_names[key] = path

        inputs.append(
            InputFile(
                path=path,
                filename=filename,
                source_type=source_type,
                platform=infer_platform(path),
                checksum=sha256_file(path),
            )
        )

    logger.info("Discovered %s raw input files.", len(inputs))
    logger.info(
        "Archive files: %s | API files: %s",
        sum(f.source_type == "ARCHIVE" for f in inputs),
        sum(f.source_type == "API" for f in inputs),
    )

    return inputs


# ---------------------------------------------------------------------------
# DATABASE INITIALIZATION AND METADATA
# ---------------------------------------------------------------------------

def open_database() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH))


def initialize_database(conn: duckdb.DuckDBPyConnection) -> None:
    require_file(SQL_INITIALIZE_DB)

    logger.info("Initializing database schema.")
    conn.execute(SQL_INITIALIZE_DB.read_text(encoding="utf-8"))


def next_id(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    column: str,
) -> int:
    allowed = {
        ("INGESTION_RUNS", "ingestion_id"),
        ("SOURCE_FILES", "file_id"),
        ("PROCESSING_RUNS", "processing_id"),
    }

    if (table, column) not in allowed:
        raise ValueError("Invalid metadata ID request.")

    value = conn.execute(
        f"SELECT COALESCE(MAX({column}), 0) + 1 FROM {table}"
    ).fetchone()[0]

    return int(value)


def create_ingestion_runs(
    conn: duckdb.DuckDBPyConnection,
    inputs: list[InputFile],
) -> dict[str, int]:
    """
    One ingestion run per source type.

    The database CHECK constraint only permits API or ARCHIVE.
    """
    ingestion_ids: dict[str, int] = {}

    for source_type in ("ARCHIVE", "API"):
        if not any(f.source_type == source_type for f in inputs):
            continue

        ingestion_id = next_id(
            conn, "INGESTION_RUNS", "ingestion_id"
        )

        conn.execute(
            """
            INSERT INTO INGESTION_RUNS (
                ingestion_id,
                source_type,
                start_time,
                end_time,
                status
            )
            VALUES (?, ?, ?, NULL, ?)
            """,
            [ingestion_id, source_type, utc_now(), "RUNNING"],
        )

        ingestion_ids[source_type] = ingestion_id

    return ingestion_ids


def register_source_files(
    conn: duckdb.DuckDBPyConnection,
    inputs: list[InputFile],
    ingestion_ids: dict[str, int],
) -> dict[str, int]:
    """
    Register source files idempotently using SHA-256 + source_type.

    If a filename already exists with a different checksum, stop.
    Raw inputs are expected to be immutable.
    """
    file_ids: dict[str, int] = {}

    for item in inputs:
        existing = conn.execute(
            """
            SELECT file_id, checksum
            FROM SOURCE_FILES
            WHERE lower(filename) = lower(?)
              AND source_type = ?
            """,
            [item.filename, item.source_type],
        ).fetchall()

        if existing:
            if len(existing) != 1:
                raise RuntimeError(
                    f"Multiple metadata records exist for {item.filename}."
                )

            existing_id, existing_checksum = existing[0]

            if existing_checksum != item.checksum:
                raise RuntimeError(
                    f"Raw file changed after registration: {item.filename}\n"
                    "The raw-data immutability rule was violated. "
                    "Do not silently reuse its old file_id."
                )

            file_id = int(existing_id)

        else:
            file_id = next_id(conn, "SOURCE_FILES", "file_id")

            conn.execute(
                """
                INSERT INTO SOURCE_FILES (
                    file_id,
                    filename,
                    source_type,
                    platform,
                    product_version,
                    retrieval_time,
                    checksum,
                    ingestion_id
                )
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                [
                    file_id,
                    item.filename,
                    item.source_type,
                    item.platform,
                    utc_now(),
                    item.checksum,
                    ingestion_ids[item.source_type],
                ],
            )

        file_ids[f"{item.source_type}:{item.filename}"] = file_id

    logger.info("Registered/resolved %s source files.", len(file_ids))
    return file_ids


def register_processing_runs(
    conn: duckdb.DuckDBPyConnection,
    inputs: list[InputFile],
    file_ids: dict[str, int],
) -> dict[str, int]:
    """
    Create a new processing run for each input file on each pipeline run.

    This means the final Parquet records the processing run that produced it.
    """
    processing_ids: dict[str, int] = {}

    for item in inputs:
        key = f"{item.source_type}:{item.filename}"
        file_id = file_ids[key]

        processing_id = next_id(
            conn, "PROCESSING_RUNS", "processing_id"
        )

        conn.execute(
            """
            INSERT INTO PROCESSING_RUNS (
                processing_id,
                input_file_id,
                processing_version,
                start_time,
                status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                processing_id,
                file_id,
                PROCESSING_VERSION,
                utc_now(),
                "RUNNING",
            ],
        )

        processing_ids[key] = processing_id

    return processing_ids


def update_run_status(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    id_column: str,
    record_id: int,
    status: str,
) -> None:
    allowed = {
        ("INGESTION_RUNS", "ingestion_id"),
        ("PROCESSING_RUNS", "processing_id"),
    }

    if (table, id_column) not in allowed:
        raise ValueError("Invalid metadata status update.")

    if table == "INGESTION_RUNS":
        conn.execute(
            """
            UPDATE INGESTION_RUNS
            SET status = ?, end_time = ?
            WHERE ingestion_id = ?
            """,
            [status, utc_now(), record_id],
        )
    else:
        conn.execute(
            """
            UPDATE PROCESSING_RUNS
            SET status = ?
            WHERE processing_id = ?
            """,
            [status, record_id],
        )


# ---------------------------------------------------------------------------
# SAFE OUTPUT MANAGEMENT
# ---------------------------------------------------------------------------

def backup_existing_outputs() -> dict[Path, Path]:
    """
    Back up existing canonical outputs before SQL stages run.

    Backups are restored if a stage fails.
    """
    outputs = [
        CLEANED_PARQUET,
        ROOT / "data" / "processed" / "quarantine"
        / "quarantined_detections.parquet",
        REPORT_DIR / "cleaning_report.csv",
    ]

    backups: dict[Path, Path] = {}

    for output in outputs:
        if output.exists():
            backup = output.with_suffix(output.suffix + ".pipeline_backup")
            shutil.copy2(output, backup)
            backups[output] = backup

    return backups


def restore_outputs(backups: dict[Path, Path]) -> None:
    for original, backup in backups.items():
        if backup.exists():
            shutil.copy2(backup, original)

    for temporary in (STANDARDIZED_TMP, IDS_TMP, FINAL_TMP):
        if temporary.exists():
            temporary.unlink()


def remove_backups(backups: dict[Path, Path]) -> None:
    for backup in backups.values():
        backup.unlink(missing_ok=True)


def promote_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(
            f"Expected SQL output was not created: {source}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)


# ---------------------------------------------------------------------------
# SQL STAGES
# ---------------------------------------------------------------------------

def execute_sql_stage(
    conn: duckdb.DuckDBPyConnection,
    sql_path: Path,
    description: str,
) -> None:
    require_file(sql_path)

    logger.info("Running stage: %s", description)
    conn.execute(sql_path.read_text(encoding="utf-8"))


def parquet_columns(
    conn: duckdb.DuckDBPyConnection,
    path: Path,
) -> set[str]:
    if not path.is_file():
        raise FileNotFoundError(path)

    rows = conn.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)",
        [str(path)],
    ).fetchall()

    return {row[0] for row in rows}



def validate_sql_output_contract(
    conn: duckdb.DuckDBPyConnection,
    path: Path,
    require_ids: bool = False,
    standardized: bool = False,
) -> None:
    columns = parquet_columns(conn, path)

    # Columns that must survive every processing stage.
    required = {
        "source_file",
        "source_type",
    }

    # These names exist only after standardization.
    if standardized:
        required.update({
            "detection_id" if require_ids else "source",
            "satellite",
            "instrument",
            "platform",
            "sensor",
            "latitude",
            "longitude",
            "acq_date",
            "acq_time",
            "acquisition_time_utc",
            "confidence_native",
            "confidence_class",
            "brightness",
            "bright_t31",
            "bright_ti4",
            "bright_ti5",
            "frp_mw",
            "scan_km",
            "track_km",
            "daynight",
            "product_version",
            "quality_flags",
        })

    if require_ids:
        required.add("detection_id")

    missing = required - columns

    if missing:
        raise RuntimeError(
            f"{path.name} is missing required columns: {sorted(missing)}"
        )

    invalid_source_types = conn.execute(
        """
        SELECT COUNT(*)
        FROM read_parquet(?)
        WHERE source_type NOT IN ('API', 'ARCHIVE')
           OR source_type IS NULL
        """,
        [str(path)],
    ).fetchone()[0]

    if invalid_source_types:
        raise RuntimeError(
            f"{invalid_source_types} rows have invalid source_type values."
        )





def run_sql_pipeline(conn: duckdb.DuckDBPyConnection) -> None:
    execute_sql_stage(conn, SQL_CLEANING, "Cleaning")

    # Cleaning still uses the original/raw column names.
    validate_sql_output_contract(
        conn,
        CLEANED_PARQUET,
        standardized=False,
    )

    execute_sql_stage(
        conn,
        SQL_STANDARDIZATION,
        "Standardization",
    )

    # Standardization introduces scan_km, track_km, frp_mw, etc.
    validate_sql_output_contract(
        conn,
        STANDARDIZED_TMP,
        standardized=True,
    )

    promote_file(STANDARDIZED_TMP, CLEANED_PARQUET)

    execute_sql_stage(
        conn,
        SQL_DETECTION_IDS,
        "Deterministic detection IDs",
    )

    validate_sql_output_contract(
        conn,
        IDS_TMP,
        require_ids=True,
        standardized=True,
    )

    promote_file(IDS_TMP, CLEANED_PARQUET)

# ---------------------------------------------------------------------------
# ADD FILE AND PROCESSING IDS TO THE CANONICAL PARQUET
# ---------------------------------------------------------------------------

def attach_metadata_ids(
    conn: duckdb.DuckDBPyConnection,
    file_ids: dict[str, int],
    processing_ids: dict[str, int],
) -> None:
    """
    Attach file_id and processing_id to every standardized detection.

    Matches:
        source_file + source_type -> SOURCE_FILES.filename + source_type
        SOURCE_FILES.file_id -> latest PROCESSING_RUNS.processing_id

    Produces the final canonical cleaned Parquet with:
        detection_id, file_id, processing_id,
        source_file, source_type,
        and all standardized detection fields.
    """

    logger.info("Attaching file_id and processing_id to Parquet.")

    if not CLEANED_PARQUET.exists():
        raise FileNotFoundError(
            f"ID-enriched Parquet not found: {CLEANED_PARQUET}"
        )

    if FINAL_TMP.exists():
        FINAL_TMP.unlink()

    # Safely convert paths and values into SQL string literals.
    # DuckDB COPY and DDL statements do not support prepared
    # parameters in the same way as ordinary SELECT statements.
    def sql_literal(value: str | Path) -> str:
        escaped = str(value).replace("\\", "/").replace("'", "''")
        return f"'{escaped}'"

    input_path_sql = sql_literal(CLEANED_PARQUET)
    output_path_sql = sql_literal(FINAL_TMP)
    processing_version_sql = sql_literal(PROCESSING_VERSION)

    # Build the final Parquet.
    # The subquery selects the latest processing run per source file.
    conn.execute(
        f"""
        COPY (
            SELECT
                p.detection_id,
                sf.file_id,
                cp.processing_id,
                ir.start_time AS ingested_at,
                'STANDARDIZED' AS processing_level,

                p.source_file,
                p.source_type,

                p.source,
                p.satellite,
                p.instrument,
                p.platform,
                p.sensor,

                p.latitude,
                p.longitude,
                p.acq_date,
                p.acq_time,
                p.acquisition_time_utc,

                p.confidence_native,
                p.confidence_class,

                p.brightness,
                p.bright_t31,
                p.bright_ti4,
                p.bright_ti5,

                p.frp_mw,
                p.scan_km,
                p.track_km,

                p.daynight,
                p.product_version,
                p.quality_flags

            FROM read_parquet({input_path_sql}) AS p

            LEFT JOIN SOURCE_FILES AS sf
                ON lower(sf.filename) = lower(
                    regexp_extract(
                        replace(p.source_file, chr(92), '/'),
                        '[^/]+$'
                    )
                )
                AND sf.source_type = p.source_type

            LEFT JOIN INGESTION_RUNS AS ir
                ON ir.ingestion_id = sf.ingestion_id

            LEFT JOIN (
                SELECT
                    input_file_id,
                    processing_id
                FROM PROCESSING_RUNS
                WHERE processing_version = {processing_version_sql}
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY input_file_id
                    ORDER BY processing_id DESC
                ) = 1
            ) AS cp
                ON cp.input_file_id = sf.file_id

        )
        TO {output_path_sql}
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )

    logger.info("Validating final Parquet schema.")

    final_columns = parquet_columns(conn, FINAL_TMP)

    missing = EXPECTED_DETECTION_COLUMNS - final_columns

    if missing:
        raise RuntimeError(
            f"Final Parquet is missing columns: {sorted(missing)}"
        )

    # Verify that every detection has both metadata references.
    orphan_count = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet({output_path_sql})
        WHERE file_id IS NULL
           OR processing_id IS NULL
        """
    ).fetchone()[0]

    if orphan_count:
        raise RuntimeError(
            f"{orphan_count} detections could not be linked to "
            "a registered source file and processing run. "
            "The canonical Parquet was not promoted."
        )

    # Verify deterministic detection IDs are unique.
    duplicate_ids = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM (
            SELECT detection_id
            FROM read_parquet({output_path_sql})
            GROUP BY detection_id
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]

    if duplicate_ids:
        raise RuntimeError(
            f"{duplicate_ids} duplicate detection IDs found. "
            "The canonical Parquet was not promoted."
        )

    # Verify that the final dataset contains rows.
    final_count = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet({output_path_sql})
        """
    ).fetchone()[0]

    if final_count == 0:
        raise RuntimeError(
            "Final Parquet contains zero detections. "
            "The canonical Parquet was not promoted."
        )

    # Promote only after all validations pass.
    promote_file(FINAL_TMP, CLEANED_PARQUET)

    logger.info(
        "Final Parquet validated and promoted successfully. "
        "Rows: %s | Columns: %s",
        f"{final_count:,}",
        len(final_columns),
    )


# ---------------------------------------------------------------------------
# REBUILD UNIFIED_DETECTIONS
# ---------------------------------------------------------------------------

def rebuild_unified_detections(
    conn: duckdb.DuckDBPyConnection,
) -> int:
    """
    Rebuild the unified table from the final canonical Parquet.

    This is a full refresh, not an append. Repeated runs cannot duplicate
    detections.
    """
    logger.info("Rebuilding UNIFIED_DETECTIONS.")

    conn.execute("BEGIN TRANSACTION")

    try:
        conn.execute("DELETE FROM UNIFIED_DETECTIONS")

        conn.execute(
            """
            INSERT INTO UNIFIED_DETECTIONS (
                detection_id,
                file_id,
                processing_id,
                ingested_at,
                processing_level,
                source,
                platform,
                sensor,
                latitude,
                longitude,
                acquisition_time_utc,
                confidence_native,
                confidence_class,
                frp_mw,
                brightness_native,
                bright_t31,
                bright_ti4,
                bright_ti5,
                scan,
                track,
                daynight,
                product_version,
                quality_flags
            )
            SELECT
                detection_id,
                file_id,
                processing_id,
                ingested_at,
                processing_level,
                source,
                platform,
                sensor,
                latitude,
                longitude,
                acquisition_time_utc,
                confidence_native,
                confidence_class,
                frp_mw,
                brightness AS brightness_native,
                bright_t31,
                bright_ti4,
                bright_ti5,
                scan_km AS scan,
                track_km AS track,
                daynight,
                product_version,
                quality_flags
            FROM read_parquet(?)
            """,
            [str(CLEANED_PARQUET)],
        )

        conn.execute("COMMIT")

    except Exception:
        conn.execute("ROLLBACK")
        raise

    count = conn.execute(
        "SELECT COUNT(*) FROM UNIFIED_DETECTIONS"
    ).fetchone()[0]

    return int(count)


# ---------------------------------------------------------------------------
# FINAL VALIDATION
# ---------------------------------------------------------------------------

def validate_final_database(
    conn: duckdb.DuckDBPyConnection,
    parquet_count: int,
) -> None:
    logger.info("Running final database validation.")

    db_count = conn.execute(
        "SELECT COUNT(*) FROM UNIFIED_DETECTIONS"
    ).fetchone()[0]

    distinct_ids = conn.execute(
        "SELECT COUNT(DISTINCT detection_id) FROM UNIFIED_DETECTIONS"
    ).fetchone()[0]

    null_ids = conn.execute(
        """
        SELECT COUNT(*)
        FROM UNIFIED_DETECTIONS
        WHERE detection_id IS NULL
        """
    ).fetchone()[0]

    null_file_ids = conn.execute(
        """
        SELECT COUNT(*)
        FROM UNIFIED_DETECTIONS
        WHERE file_id IS NULL
        """
    ).fetchone()[0]

    null_processing_ids = conn.execute(
        """
        SELECT COUNT(*)
        FROM UNIFIED_DETECTIONS
        WHERE processing_id IS NULL
        """
    ).fetchone()[0]

    null_ingested_at = conn.execute(
        """
        SELECT COUNT(*)
        FROM UNIFIED_DETECTIONS
        WHERE ingested_at IS NULL
        """
    ).fetchone()[0]

    invalid_processing_levels = conn.execute(
        """
        SELECT COUNT(*)
        FROM UNIFIED_DETECTIONS
        WHERE processing_level IS NULL
           OR processing_level NOT IN (
               'CLEANED', 'STANDARDIZED', 'HARMONIZED'
           )
        """
    ).fetchone()[0]

    if db_count != parquet_count:
        raise RuntimeError(
            f"Row count mismatch: Parquet={parquet_count}, "
            f"Database={db_count}"
        )

    if distinct_ids != db_count or null_ids:
        raise RuntimeError(
            "Detection IDs are not unique or contain NULL values."
        )

    if null_file_ids or null_processing_ids:
        raise RuntimeError(
            "Database contains detections without file-level provenance."
        )

    if null_ingested_at:
        raise RuntimeError(
            f"{null_ingested_at} detections have no ingestion timestamp."
        )

    if invalid_processing_levels:
        raise RuntimeError(
            f"{invalid_processing_levels} detections have invalid processing levels."
        )

    logger.info("Final validation passed.")
    logger.info("Detection rows: %s", db_count)
    logger.info("Distinct detection IDs: %s", distinct_ids)
    logger.info("NULL detection IDs: %s", null_ids)
    logger.info("NULL file IDs: %s", null_file_ids)
    logger.info("NULL processing IDs: %s", null_processing_ids)
    logger.info("NULL ingestion timestamps: %s", null_ingested_at)
    logger.info("Invalid processing levels: %s", invalid_processing_levels)

    logger.info("Database tables:")
    for row in conn.execute("SHOW TABLES").fetchall():
        logger.info("  %s", row[0])


# ---------------------------------------------------------------------------
# MAIN ORCHESTRATION
# ---------------------------------------------------------------------------

def run_pipeline() -> None:
    ensure_directories()

    for required in (
        SQL_CLEANING,
        SQL_STANDARDIZATION,
        SQL_DETECTION_IDS,
        SQL_INITIALIZE_DB,
    ):
        require_file(required)

    inputs = discover_inputs()

    backups = backup_existing_outputs()
    conn = open_database()

    ingestion_ids: dict[str, int] = {}
    processing_ids: dict[str, int] = {}

    try:
        initialize_database(conn)

        conn.execute("BEGIN TRANSACTION")

        try:
            ingestion_ids = create_ingestion_runs(conn, inputs)

            file_ids = register_source_files(
                conn, inputs, ingestion_ids
            )

            processing_ids = register_processing_runs(
                conn, inputs, file_ids
            )

            conn.execute("COMMIT")

        except Exception:
            conn.execute("ROLLBACK")
            raise

        run_sql_pipeline(conn)

        attach_metadata_ids(
            conn,
            file_ids,
            processing_ids,
        )

        parquet_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM read_parquet(?)",
                [str(CLEANED_PARQUET)],
            ).fetchone()[0]
        )

        if parquet_count == 0:
            raise RuntimeError("The final cleaned dataset is empty.")

        database_count = rebuild_unified_detections(conn)

        if database_count != parquet_count:
            raise RuntimeError(
                "The database and canonical Parquet have different "
                "row counts."
            )

        validate_final_database(conn, parquet_count)

        for ingestion_id in ingestion_ids.values():
            update_run_status(
                conn,
                "INGESTION_RUNS",
                "ingestion_id",
                ingestion_id,
                "COMPLETED",
            )

        for processing_id in processing_ids.values():
            update_run_status(
                conn,
                "PROCESSING_RUNS",
                "processing_id",
                processing_id,
                "COMPLETED",
            )

        remove_backups(backups)

        logger.info("=" * 65)
        logger.info("PYROSYNC PIPELINE COMPLETED SUCCESSFULLY")
        logger.info("Canonical Parquet: %s", CLEANED_PARQUET)
        logger.info("DuckDB database:   %s", DB_PATH)
        logger.info("Total detections:  %s", parquet_count)
        logger.info("=" * 65)

    except Exception:
        logger.exception("Pipeline failed.")

        # Restore previous canonical Parquet outputs.
        restore_outputs(backups)

        # Mark this run as failed where possible.
        for ingestion_id in ingestion_ids.values():
            try:
                update_run_status(
                    conn,
                    "INGESTION_RUNS",
                    "ingestion_id",
                    ingestion_id,
                    "FAILED",
                )
            except Exception:
                logger.exception(
                    "Could not mark ingestion %s as FAILED.",
                    ingestion_id,
                )

        for processing_id in processing_ids.values():
            try:
                update_run_status(
                    conn,
                    "PROCESSING_RUNS",
                    "processing_id",
                    processing_id,
                    "FAILED",
                )
            except Exception:
                logger.exception(
                    "Could not mark processing %s as FAILED.",
                    processing_id,
                )

        raise

    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the TwinFlame / PyroSync data pipeline."
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Discover inputs and verify required SQL files without processing.",
    )

    args = parser.parse_args()

    if args.check_only:
        ensure_directories()
        inputs = discover_inputs()

        for path in (
            SQL_CLEANING,
            SQL_STANDARDIZATION,
            SQL_DETECTION_IDS,
            SQL_INITIALIZE_DB,
        ):
            require_file(path)

        logger.info("Preflight passed. %s inputs discovered.", len(inputs))
        return

    run_pipeline()


if __name__ == "__main__":
    main()
