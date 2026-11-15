"""Process pending NASA FIRMS API Parquet files through shared SQL stages."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSING_VERSION = "pyrosync-api-incremental-v1"

SQL_CLEANING = PROJECT_ROOT / "sql" / "cleaning" / "01_clean_sources.sql"
SQL_STANDARDIZATION = (
    PROJECT_ROOT / "sql" / "standardization" / "01_standardize_cleaned.sql"
)
SQL_DETECTION_IDS = (
    PROJECT_ROOT / "sql" / "preprocessing" / "01_generate_detection_ids.sql"
)
SQL_INITIALIZE_DB = PROJECT_ROOT / "sql" / "database" / "01_initialize_database.sql"

API_RAW_COLUMNS = {
    "latitude": "DOUBLE",
    "longitude": "DOUBLE",
    "brightness": "DOUBLE",
    "bright_t31": "DOUBLE",
    "bright_ti4": "DOUBLE",
    "bright_ti5": "DOUBLE",
    "frp": "DOUBLE",
    "scan": "DOUBLE",
    "track": "DOUBLE",
    "acq_date": "VARCHAR",
    "acq_time": "BIGINT",
    "satellite": "VARCHAR",
    "instrument": "VARCHAR",
    "confidence": "VARCHAR",
    "version": "VARCHAR",
    "daynight": "VARCHAR",
    "filename": "VARCHAR",
}


@dataclass(frozen=True)
class FileProcessingResult:
    path: Path
    status: str
    input_rows: int = 0
    cleaned_rows: int = 0
    quarantined_rows: int = 0
    inserted_rows: int = 0
    error: str | None = None


@dataclass(frozen=True)
class ProcessingSummary:
    discovered_files: int
    skipped_files: int
    results: tuple[FileProcessingResult, ...]

    @property
    def succeeded(self) -> int:
        return sum(result.status == "COMPLETED" for result in self.results)

    @property
    def failed(self) -> int:
        return sum(result.status == "FAILED" for result in self.results)

    @property
    def inserted_rows(self) -> int:
        return sum(result.inserted_rows for result in self.results)


class APIIncrementalProcessor:
    """Import API Parquet files once, with per-file cleaning and run metadata."""

    def __init__(
        self,
        raw_api_dir: str | Path | None = None,
        database_path: str | Path | None = None,
        quarantine_dir: str | Path | None = None,
        report_dir: str | Path | None = None,
        temp_dir: str | Path | None = None,
    ) -> None:
        self.raw_api_dir = Path(raw_api_dir or PROJECT_ROOT / "data" / "raw" / "api")
        self.database_path = Path(
            database_path or PROJECT_ROOT / "database" / "twinflame.duckdb"
        )
        self.duckdb_temp_dir = self.database_path.parent / "tmp_spill"
        self.quarantine_dir = Path(
            quarantine_dir or PROJECT_ROOT / "data" / "processed" / "quarantine" / "api"
        )
        self.report_dir = Path(
            report_dir or PROJECT_ROOT / "data" / "processed" / "reports" / "api"
        )
        self.temp_dir = Path(
            temp_dir or PROJECT_ROOT / "data" / "processed" / "api_incremental" / "tmp"
        )

    def process_pending(
        self,
        retry_failed: bool = False,
        files: list[str | Path] | None = None,
    ) -> ProcessingSummary:
        """Process new files, or only failed files when retry_failed is true."""
        discovered = self._discover_files(files)
        if not discovered:
            return ProcessingSummary(0, 0, ())

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.duckdb_temp_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        conn = duckdb.connect(str(self.database_path))
        memory_limit = os.environ.get("DUCKDB_MEMORY_LIMIT", "4GB").strip().upper()
        if not re.fullmatch(r"\d+(KB|MB|GB|TB)", memory_limit):
            conn.close()
            raise ValueError(
                "DUCKDB_MEMORY_LIMIT must be a size such as 2GB, 4096MB, or 1TB."
            )
        try:
            threads = int(os.environ.get("DUCKDB_THREADS", "2"))
        except ValueError as exc:
            conn.close()
            raise ValueError("DUCKDB_THREADS must be a positive integer.") from exc
        if threads <= 0:
            conn.close()
            raise ValueError("DUCKDB_THREADS must be a positive integer.")
        conn.execute(f"SET temp_directory = {sql_literal(self.duckdb_temp_dir)}")
        conn.execute(f"SET memory_limit = {sql_literal(memory_limit)}")
        conn.execute(f"SET threads = {threads}")
        results: list[FileProcessingResult] = []
        skipped = 0
        ingestion_id: int | None = None
        started_at = utc_now()

        try:
            self._initialize_database(conn)

            eligible: list[tuple[Path, str, int | None]] = []
            for path in discovered:
                try:
                    checksum = sha256_file(path)
                    file_id = self._find_file_id(conn, path, checksum)
                    state = self._file_state(conn, checksum)

                    if state == "COMPLETED":
                        skipped += 1
                        continue
                    if retry_failed and state != "FAILED":
                        skipped += 1
                        continue
                    eligible.append((path, checksum, file_id))
                except Exception as exc:
                    logger.exception("Could not inspect API file %s", path)
                    results.append(FileProcessingResult(path, "FAILED", error=str(exc)))

            if not eligible and not results:
                return ProcessingSummary(len(discovered), skipped, tuple(results))

            ingestion_id = self._start_ingestion(conn, started_at)
            # Keep failures found during discovery visible in PROCESSING_RUNS too.
            for failure in results:
                file_id = self._find_file_id_by_name(conn, failure.path.name)
                processing_id = self._start_processing(conn, file_id)
                conn.execute(
                    "UPDATE PROCESSING_RUNS SET status = 'FAILED' WHERE processing_id = ?",
                    [processing_id],
                )

            for path, checksum, file_id in eligible:
                try:
                    file_id = self._register_source_file(
                        conn, path, checksum, ingestion_id, file_id
                    )
                    processing_id = self._start_processing(conn, file_id)
                except Exception as exc:
                    logger.exception("Could not register API file %s", path)
                    failed_file_id = self._find_file_id_by_name(conn, path.name)
                    processing_id = self._start_processing(conn, failed_file_id)
                    conn.execute(
                        "UPDATE PROCESSING_RUNS SET status = 'FAILED' WHERE processing_id = ?",
                        [processing_id],
                    )
                    results.append(FileProcessingResult(path, "FAILED", error=str(exc)))
                    continue

                result = self._process_file(
                    conn, path, file_id, processing_id
                )
                results.append(result)

            failed = sum(result.status == "FAILED" for result in results)
            succeeded = sum(result.status == "COMPLETED" for result in results)
            status = "COMPLETED" if failed == 0 else "PARTIAL" if succeeded else "FAILED"
            conn.execute(
                "UPDATE INGESTION_RUNS SET end_time = ?, status = ? WHERE ingestion_id = ?",
                [utc_now(), status, ingestion_id],
            )
        finally:
            conn.close()

        summary = ProcessingSummary(len(discovered), skipped, tuple(results))
        logger.info(
            "API file processing finished: succeeded=%d failed=%d skipped=%d inserted=%d",
            summary.succeeded,
            summary.failed,
            summary.skipped_files,
            summary.inserted_rows,
        )
        return summary

    def _discover_files(self, files: list[str | Path] | None) -> list[Path]:
        candidates = (
            [Path(path) for path in files]
            if files is not None
            else sorted(self.raw_api_dir.rglob("*.parquet"))
            if self.raw_api_dir.exists()
            else []
        )
        return sorted(
            {path.resolve() for path in candidates if path.is_file() and path.suffix.lower() == ".parquet"},
            key=lambda path: str(path).casefold(),
        )

    def _initialize_database(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute(SQL_INITIALIZE_DB.read_text(encoding="utf-8"))
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS CLEANING_THRESHOLD_BASELINES (
                source VARCHAR NOT NULL,
                satellite VARCHAR NOT NULL,
                metric VARCHAR NOT NULL,
                observation_count BIGINT,
                lower_percentile DOUBLE,
                q1 DOUBLE,
                q3 DOUBLE,
                updated_at TIMESTAMP,
                PRIMARY KEY (source, satellite, metric)
            )
            """
        )

    @staticmethod
    def _find_file_id(
        conn: duckdb.DuckDBPyConnection,
        path: Path,
        checksum: str,
    ) -> int | None:
        row = conn.execute(
            """
            SELECT file_id FROM SOURCE_FILES
            WHERE source_type = 'API' AND lower(filename) = lower(?)
            ORDER BY file_id DESC LIMIT 1
            """,
            [path.name],
        ).fetchone()
        if row:
            existing = conn.execute(
                "SELECT checksum FROM SOURCE_FILES WHERE file_id = ?", [row[0]]
            ).fetchone()[0]
            if existing and existing != checksum:
                raise RuntimeError(
                    f"API source file changed after registration: {path.name}"
                )
            return int(row[0])
        return None

    @staticmethod
    def _file_state(conn: duckdb.DuckDBPyConnection, checksum: str) -> str | None:
        row = conn.execute(
            """
            SELECT pr.status
            FROM PROCESSING_RUNS AS pr
            JOIN SOURCE_FILES AS sf ON sf.file_id = pr.input_file_id
            WHERE sf.source_type = 'API' AND sf.checksum = ?
            ORDER BY pr.processing_id DESC LIMIT 1
            """,
            [checksum],
        ).fetchone()
        return str(row[0]).upper() if row and row[0] else None

    @staticmethod
    def _find_file_id_by_name(
        conn: duckdb.DuckDBPyConnection,
        filename: str,
    ) -> int | None:
        row = conn.execute(
            """
            SELECT file_id FROM SOURCE_FILES
            WHERE source_type = 'API' AND lower(filename) = lower(?)
            ORDER BY file_id DESC LIMIT 1
            """,
            [filename],
        ).fetchone()
        return int(row[0]) if row else None

    @staticmethod
    def _start_ingestion(conn: duckdb.DuckDBPyConnection, started_at: datetime) -> int:
        ingestion_id = int(
            conn.execute("SELECT COALESCE(MAX(ingestion_id), 0) + 1 FROM INGESTION_RUNS").fetchone()[0]
        )
        conn.execute(
            "INSERT INTO INGESTION_RUNS (ingestion_id, source_type, start_time, status) VALUES (?, 'API', ?, 'RUNNING')",
            [ingestion_id, started_at],
        )
        return ingestion_id

    def _register_source_file(
        self,
        conn: duckdb.DuckDBPyConnection,
        path: Path,
        checksum: str,
        ingestion_id: int,
        file_id: int | None,
    ) -> int:
        if file_id is not None:
            return file_id
        file_id = int(
            conn.execute("SELECT COALESCE(MAX(file_id), 0) + 1 FROM SOURCE_FILES").fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO SOURCE_FILES (
                file_id, filename, source_type, platform, product_version,
                retrieval_time, checksum, ingestion_id
            ) VALUES (?, ?, 'API', ?, NULL, ?, ?, ?)
            """,
            [file_id, path.name, infer_platform(path), file_mtime_utc(path), checksum, ingestion_id],
        )
        return file_id

    @staticmethod
    def _start_processing(
        conn: duckdb.DuckDBPyConnection,
        file_id: int | None,
    ) -> int:
        processing_id = int(
            conn.execute("SELECT COALESCE(MAX(processing_id), 0) + 1 FROM PROCESSING_RUNS").fetchone()[0]
        )
        conn.execute(
            """
            INSERT INTO PROCESSING_RUNS (
                processing_id, input_file_id, processing_version, start_time, status
            ) VALUES (?, ?, ?, ?, 'RUNNING')
            """,
            [processing_id, file_id, PROCESSING_VERSION, utc_now()],
        )
        return processing_id

    def _process_file(
        self,
        conn: duckdb.DuckDBPyConnection,
        path: Path,
        file_id: int,
        processing_id: int,
    ) -> FileProcessingResult:
        stem = safe_stem(path.stem)
        quarantine_path = self.quarantine_dir / f"{stem}.quarantine.parquet"
        report_path = self.report_dir / f"{stem}.cleaning.csv"
        try:
            with tempfile.TemporaryDirectory(prefix=f"{stem}_", dir=self.temp_dir) as temp_name:
                temp = Path(temp_name)
                cleaned_path = temp / "cleaned.parquet"
                standardized_path = temp / "standardized.parquet"
                identified_path = temp / "identified.parquet"

                conn.execute("BEGIN TRANSACTION")
                try:
                    self._create_input_tables(conn, path)
                    self._load_threshold_overrides(conn)
                    execute_sql_template(
                        conn,
                        SQL_CLEANING,
                        {
                            "CLEANED_OUTPUT": cleaned_path,
                            "QUARANTINE_OUTPUT": quarantine_path,
                            "CLEANING_REPORT_OUTPUT": report_path,
                        },
                    )
                    execute_sql_template(
                        conn,
                        SQL_STANDARDIZATION,
                        {
                            "CLEANED_INPUT": cleaned_path,
                            "STANDARDIZED_OUTPUT": standardized_path,
                        },
                    )
                    execute_sql_template(
                        conn,
                        SQL_DETECTION_IDS,
                        {
                            "STANDARDIZED_INPUT": standardized_path,
                            "IDENTIFIED_OUTPUT": identified_path,
                        },
                    )

                    input_rows = int(
                        conn.execute("SELECT COUNT(*) FROM api_raw").fetchone()[0]
                    )
                    cleaned_rows = int(
                        conn.execute("SELECT COUNT(*) FROM cleaned_records").fetchone()[0]
                    )
                    quarantined_rows = int(
                        conn.execute("SELECT COUNT(*) FROM quarantined_records").fetchone()[0]
                    )
                    inserted_rows = self._insert_detections(
                        conn, identified_path, file_id, processing_id
                    )
                    conn.execute(
                        "UPDATE PROCESSING_RUNS SET status = 'COMPLETED' WHERE processing_id = ?",
                        [processing_id],
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            logger.info(
                "Processed %s: input=%d cleaned=%d quarantined=%d new=%d",
                path.name,
                input_rows,
                cleaned_rows,
                quarantined_rows,
                inserted_rows,
            )
            return FileProcessingResult(
                path, "COMPLETED", input_rows, cleaned_rows, quarantined_rows, inserted_rows
            )
        except Exception as exc:
            logger.exception("API file processing failed for %s", path)
            conn.execute(
                "UPDATE PROCESSING_RUNS SET status = 'FAILED' WHERE processing_id = ?",
                [processing_id],
            )
            return FileProcessingResult(path, "FAILED", error=str(exc))

    @staticmethod
    def _create_input_tables(conn: duckdb.DuckDBPyConnection, path: Path) -> None:
        c2_empty = """
            CREATE OR REPLACE TEMP TABLE c2_raw AS
            SELECT
                CAST(NULL AS DOUBLE) AS latitude,
                CAST(NULL AS DOUBLE) AS longitude,
                CAST(NULL AS DOUBLE) AS brightness,
                CAST(NULL AS DOUBLE) AS bright_t31,
                CAST(NULL AS DOUBLE) AS frp,
                CAST(NULL AS DOUBLE) AS scan,
                CAST(NULL AS DOUBLE) AS track,
                CAST(NULL AS VARCHAR) AS acq_date,
                CAST(NULL AS BIGINT) AS acq_time,
                CAST(NULL AS VARCHAR) AS satellite,
                CAST(NULL AS VARCHAR) AS instrument,
                CAST(NULL AS VARCHAR) AS confidence,
                CAST(NULL AS VARCHAR) AS version,
                CAST(NULL AS VARCHAR) AS daynight,
                CAST(NULL AS VARCHAR) AS type,
                CAST(NULL AS VARCHAR) AS filename
            WHERE FALSE
        """
        conn.execute(c2_empty)
        raw_path = sql_literal(path)
        available_columns = {
            row[0].casefold(): row[0]
            for row in conn.execute(
                "DESCRIBE SELECT * FROM read_parquet("
                f"{raw_path}, union_by_name = true, filename = true)"
            ).fetchall()
        }
        projection = []
        for column, sql_type in API_RAW_COLUMNS.items():
            actual_name = available_columns.get(column.casefold())
            if actual_name is None:
                expression = f"CAST(NULL AS {sql_type})"
            else:
                expression = quote_identifier(actual_name)
            projection.append(f"{expression} AS {quote_identifier(column)}")

        conn.execute(
            "CREATE OR REPLACE TEMP TABLE api_raw AS SELECT "
            + ", ".join(projection)
            + f" FROM read_parquet({raw_path}, union_by_name = true, filename = true)"
        )

    @staticmethod
    def _load_threshold_overrides(conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute(
            """
            CREATE OR REPLACE TEMP TABLE cleaning_threshold_overrides AS
            SELECT source, satellite, metric, observation_count,
                   lower_percentile, q1, q3
            FROM CLEANING_THRESHOLD_BASELINES
            """
        )

    @staticmethod
    def _insert_detections(
        conn: duckdb.DuckDBPyConnection,
        identified_path: Path,
        file_id: int,
        processing_id: int,
    ) -> int:
        path_sql = sql_literal(identified_path)
        new_rows = int(
            conn.execute(
                f"""
                SELECT COUNT(DISTINCT d.detection_id)
                FROM read_parquet({path_sql}) AS d
                WHERE NOT EXISTS (
                    SELECT 1 FROM UNIFIED_DETECTIONS AS existing
                    WHERE existing.detection_id = d.detection_id
                )
                """
            ).fetchone()[0]
        )
        conn.execute(
            f"""
            INSERT INTO UNIFIED_DETECTIONS (
                detection_id, file_id, processing_id, ingested_at,
                processing_level, source, platform, sensor, latitude, longitude,
                acquisition_time_utc, confidence_native, confidence_class, frp_mw,
                brightness_native, bright_t31, bright_ti4, bright_ti5, scan, track,
                daynight, product_version, quality_flags
            )
            SELECT
                d.detection_id, ?, ?, ?, 'STANDARDIZED', d.source, d.platform,
                d.sensor, d.latitude, d.longitude, d.acquisition_time_utc,
                d.confidence_native, d.confidence_class, d.frp_mw, d.brightness,
                d.bright_t31, d.bright_ti4, d.bright_ti5, d.scan_km, d.track_km,
                d.daynight, d.product_version, d.quality_flags
            FROM read_parquet({path_sql}) AS d
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY d.detection_id ORDER BY d.source_file
            ) = 1
            ON CONFLICT (detection_id) DO NOTHING
            """,
            [file_id, processing_id, utc_now()],
        )
        return new_rows


def execute_sql_template(
    conn: duckdb.DuckDBPyConnection,
    sql_path: Path,
    replacements: dict[str, str | Path],
) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    for name, value in replacements.items():
        escaped = str(value).replace("\\", "/").replace("'", "''")
        sql = sql.replace("{{" + name + "}}", escaped)
    unresolved = re.findall(r"\{\{([A-Z_]+)\}\}", sql)
    if unresolved:
        raise ValueError(f"Unresolved SQL template values in {sql_path.name}: {unresolved}")
    conn.execute(sql)


def sql_literal(value: str | Path) -> str:
    normalized = str(value).replace("\\", "/")
    return "'" + normalized.replace("'", "''") + "'"


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def file_mtime_utc(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(tzinfo=None)


def infer_platform(path: Path) -> str | None:
    name = f"{path.parent.name} {path.name}".upper()
    if "NOAA20" in name or "J1V" in name:
        return "VIIRS_NOAA20"
    if "NOAA21" in name or "J2V" in name:
        return "VIIRS_NOAA21"
    if "MODIS" in name:
        return "MODIS"
    return None


def safe_stem(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "api_file"
