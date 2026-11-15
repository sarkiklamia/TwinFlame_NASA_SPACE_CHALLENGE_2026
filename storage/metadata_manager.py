
from __future__ import annotations

from pathlib import Path
import hashlib
import duckdb

from config.settings import get_settings


class MetadataManager:
    """Manage ingestion, source-file and processing metadata."""

    def __init__(self, database_path: str | Path | None = None):
        settings = get_settings()
        self.database_path = Path(
            database_path or settings.duckdb_path
        )
        self.database_path.parent.mkdir(
            parents=True, exist_ok=True
        )

    def connect(self):
        return duckdb.connect(str(self.database_path))

    @staticmethod
    def checksum(file_path: str | Path) -> str:
        digest = hashlib.sha256()
        with open(file_path, "rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024), b""
            ):
                digest.update(chunk)
        return digest.hexdigest()

    def register_ingestion(
        self,
        ingestion_id: int,
        source_type: str,
        start_time=None,
        end_time=None,
        status: str = "RUNNING",
    ):
        source_type = source_type.upper()
        if source_type not in {"API", "ARCHIVE"}:
            raise ValueError("source_type must be API or ARCHIVE")

        with self.connect() as con:
            con.execute("""
                INSERT INTO INGESTION_RUNS
                (ingestion_id, source_type, start_time, end_time, status)
                VALUES (?, ?, ?, ?, ?)
            """, [
                ingestion_id, source_type,
                start_time, end_time, status
            ])

    def register_file(
        self,
        file_id: int,
        filename: str | Path,
        source_type: str,
        platform: str | None,
        product_version: str | None,
        retrieval_time=None,
        ingestion_id: int | None = None,
    ) -> int:
        source_type = source_type.upper()
        if source_type not in {"API", "ARCHIVE"}:
            raise ValueError("source_type must be API or ARCHIVE")

        path = Path(filename)
        if not path.is_file():
            raise FileNotFoundError(path)

        checksum = self.checksum(path)

        with self.connect() as con:
            existing = con.execute("""
                SELECT file_id
                FROM SOURCE_FILES
                WHERE checksum = ? AND source_type = ?
            """, [checksum, source_type]).fetchone()

            if existing:
                return existing[0]

            con.execute("""
                INSERT INTO SOURCE_FILES (
                    file_id, filename, source_type, platform,
                    product_version, retrieval_time, checksum,
                    ingestion_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                file_id, path.name, source_type, platform,
                product_version, retrieval_time, checksum,
                ingestion_id
            ])

        return file_id

    def register_processing(
        self,
        processing_id: int,
        input_file_id: int | None,
        processing_version: str,
        start_time=None,
        status: str = "RUNNING",
    ):
        with self.connect() as con:
            con.execute("""
                INSERT INTO PROCESSING_RUNS (
                    processing_id, input_file_id,
                    processing_version, start_time, status
                )
                VALUES (?, ?, ?, ?, ?)
            """, [
                processing_id, input_file_id,
                processing_version, start_time, status
            ])

    def get_file_id(
        self,
        filename: str,
        source_type: str,
    ) -> int | None:
        with self.connect() as con:
            result = con.execute("""
                SELECT file_id
                FROM SOURCE_FILES
                WHERE filename = ? AND source_type = ?
                ORDER BY file_id
                LIMIT 1
            """, [Path(filename).name, source_type.upper()]).fetchone()

        return result[0] if result else None
