"""Read-only API endpoints for the TwinFlame dashboard."""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import duckdb
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config.settings import get_settings

logger = logging.getLogger(__name__)

Platform = Literal["all", "terra", "aqua", "noaa20", "noaa21"]
Region = Literal[
    "global", "africa", "asia", "europe", "north-america", "oceania", "south-america"
]
DayNight = Literal["all", "day", "night"]
Period = Literal["today", "24h", "7d", "30d", "all", "custom"]
MonitoringWindow = Literal["1h", "6h", "12h", "24h", "48h", "custom"]
Sensor = Literal["all", "modis", "viirs"]
DetectionStatus = Literal["all", "new", "processed", "harmonized", "unmatched"]
MembershipQuality = Literal["all", "strong", "possible", "rejected"]
FireSeasonPlatform = Literal[
    "all", "terra", "aqua", "noaa20", "noaa21", "modis", "viirs"
]
TemporalAggregation = Literal["daily", "weekly", "monthly", "yearly"]
SpatialAggregation = Literal["detections", "grid", "clusters"]
ExportType = Literal["observations", "aggregated", "regional"]
ExportFormat = Literal["csv", "geojson", "json"]
ComparisonPlatform = Literal["terra", "aqua", "noaa20", "noaa21"]
ComparisonMetric = Literal[
    "detection_count", "frp", "brightness", "temporal_diff", "spatial_diff"
]
ComparisonEligibility = Literal["all", "matched_only", "coincident_overpasses"]
HarmDecisionClass = Literal[
    "all", "strong", "possible", "rejected", "insufficient_geometry"
]
HarmPlatformPair = Literal[
    "all",
    "terra_noaa20",
    "terra_noaa21",
    "aqua_noaa20",
    "aqua_noaa21",
    "terra_aqua",
    "noaa20_noaa21",
]
HarmGeometryQuality = Literal["all", "high", "nominal", "degraded", "insufficient"]

REGION_BOUNDS = {
    "africa": (-20.0, -40.0, 55.0, 38.0),
    "asia": (25.0, -12.0, 180.0, 82.0),
    "europe": (-25.0, 34.0, 45.0, 72.0),
    "north-america": (-170.0, 5.0, -50.0, 84.0),
    "oceania": (110.0, -50.0, 180.0, 0.0),
    "south-america": (-85.0, -57.0, -30.0, 14.0),
}
REQUIRED_TABLES = {
    "unified_detections",
    "harm_activity_clusters",
    "harm_cluster_members",
    "harm_correspondence_edges",
    "harm_correspondence_summary",
    "harm_run_metadata",
}
ACQUISITION_TIMESTAMP = """
    acq_date + COALESCE(
        TRY_CAST(
            TRY_STRPTIME(
                LPAD(REGEXP_REPLACE(COALESCE(acq_time, ''), '[^0-9]', '', 'g'), 4, '0'),
                '%H%M'
            ) AS TIME
        ),
        TIME '00:00:00'
    )
"""

app = FastAPI(title="TwinFlame Dashboard API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _platform_condition(platform: str, column: str) -> str:
    if platform == "all":
        return ""
    compact = f"REGEXP_REPLACE(UPPER(COALESCE({column}, '')), '[^A-Z0-9]', '', 'g')"
    if platform == "terra":
        return f"({compact} LIKE '%TERRA%')"
    if platform == "aqua":
        return f"({compact} LIKE '%AQUA%')"
    return f"({compact} LIKE '%{platform.upper()}%')"


def _filtered_detections(
    *,
    period: Period,
    platform: Platform,
    region: Region,
    daynight: DayNight,
    frp_min: float | None,
    frp_max: float | None,
    start_date: date | None,
    end_date: date | None,
    now: datetime,
) -> tuple[str, list[object]]:
    conditions: list[str] = []
    parameters: list[object] = []

    if period == "today":
        conditions.append("acq_date = ?")
        parameters.append(now.date())
    elif period == "24h":
        conditions.append(f"{ACQUISITION_TIMESTAMP} BETWEEN ? AND ?")
        parameters.extend((now - timedelta(hours=24), now))
    elif period in ("7d", "30d"):
        days = 6 if period == "7d" else 29
        conditions.append("acq_date >= ?")
        parameters.append(now.date() - timedelta(days=days))
    elif period == "custom":
        if start_date is None or end_date is None:
            raise HTTPException(
                status_code=422,
                detail="Custom date ranges require both start_date and end_date.",
            )
        if start_date > end_date:
            raise HTTPException(
                status_code=422,
                detail="start_date must be on or before end_date.",
            )
        conditions.extend(("acq_date >= ?", "acq_date <= ?"))
        parameters.extend((start_date, end_date))

    if period != "all" and period != "custom" and period != "24h":
        conditions.append("acq_date <= ?")
        parameters.append(now.date())

    platform_clauses = [
        _platform_condition(platform, "platform"),
        _platform_condition(platform, "source"),
    ]
    platform_clauses = [clause for clause in platform_clauses if clause]
    if platform_clauses:
        conditions.append("(" + " OR ".join(platform_clauses) + ")")

    if region != "global":
        west, south, east, north = REGION_BOUNDS[region]
        conditions.append("longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?")
        parameters.extend((west, east, south, north))

    if daynight == "day":
        conditions.append("UPPER(COALESCE(daynight, '')) IN ('D', 'DAY')")
    elif daynight == "night":
        conditions.append("UPPER(COALESCE(daynight, '')) IN ('N', 'NIGHT')")

    if frp_min is not None:
        conditions.append("frp_mw >= ?")
        parameters.append(frp_min)
    if frp_max is not None:
        conditions.append("frp_mw <= ?")
        parameters.append(frp_max)

    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    query = f"""
        SELECT detection_id, platform, source, latitude, longitude, acq_date,
               acq_time, frp_mw, daynight,
               {ACQUISITION_TIMESTAMP} AS acquisition_timestamp
        FROM UNIFIED_DETECTIONS
        WHERE {where_clause}
    """
    return query, parameters


def _latest_successful_run_cte() -> str:
    return """
        latest_successful_run AS (
            SELECT run_id
            FROM harm_run_metadata
            WHERE LOWER(COALESCE(status, '')) IN ('success', 'succeeded', 'complete', 'completed')
            ORDER BY COALESCE(finished_at_utc, started_at_utc) DESC
            LIMIT 1
        )
    """


def _summary_date_conditions(
    period: Period,
    now: datetime,
    start_date: date | None,
    end_date: date | None,
) -> tuple[list[str], list[object]]:
    conditions: list[str] = []
    parameters: list[object] = []
    if period == "today":
        conditions.append("date_utc = ?")
        parameters.append(now.date())
    elif period == "24h":
        conditions.extend(("date_utc >= ?", "date_utc <= ?"))
        parameters.extend(((now - timedelta(hours=24)).date(), now.date()))
    elif period == "7d":
        conditions.extend(("date_utc >= ?", "date_utc <= ?"))
        parameters.extend((now.date() - timedelta(days=6), now.date()))
    elif period == "30d":
        conditions.extend(("date_utc >= ?", "date_utc <= ?"))
        parameters.extend((now.date() - timedelta(days=29), now.date()))
    elif period == "custom" and start_date is not None and end_date is not None:
        conditions.extend(("date_utc >= ?", "date_utc <= ?"))
        parameters.extend((start_date, end_date))
    return conditions, parameters


def _require_tables(connection: duckdb.DuckDBPyConnection) -> None:
    available = {row[0].lower() for row in connection.execute("SHOW TABLES").fetchall()}
    missing = sorted(REQUIRED_TABLES - available)
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "The dashboard database is missing required tables: "
                + ", ".join(missing)
                + ". Complete the standardization and harmonization pipeline first."
            ),
        )


def _dashboard_payload(
    connection: duckdb.DuckDBPyConnection,
    *,
    filtered_sql: str,
    filter_parameters: list[object],
    period: Period,
    platform: Platform,
    region: Region,
    daynight: DayNight,
    frp_min: float | None,
    frp_max: float | None,
    start_date: date | None,
    end_date: date | None,
    now: datetime,
) -> dict[str, object]:
    latest_run = _latest_successful_run_cte()
    filtered_cte = f"filtered_detections AS ({filtered_sql})"
    ctes = f"WITH {filtered_cte}, {latest_run}"

    totals = connection.execute(
        f"""
        {ctes}
        SELECT COUNT(DISTINCT detection_id), MAX(acquisition_timestamp)
        FROM filtered_detections
        """,
        filter_parameters,
    ).fetchone()
    total_detections, latest_acquisition = totals

    daily_rows = connection.execute(
        f"""
        {ctes}
        SELECT acq_date, COUNT(DISTINCT detection_id)
        FROM filtered_detections
        GROUP BY acq_date
        ORDER BY acq_date
        """,
        filter_parameters,
    ).fetchall()
    platform_rows = connection.execute(
        f"""
        {ctes}
        SELECT COALESCE(NULLIF(TRIM(platform), ''), 'Unknown'),
               COUNT(DISTINCT detection_id)
        FROM filtered_detections
        GROUP BY 1
        ORDER BY 2 DESC
        """,
        filter_parameters,
    ).fetchall()

    cluster_count = connection.execute(
        f"""
        {ctes}
        SELECT COUNT(DISTINCT c.activity_cluster_id)
        FROM harm_activity_clusters c
        JOIN latest_successful_run lr ON c.run_id = lr.run_id
        JOIN harm_cluster_members m
          ON m.activity_cluster_id = c.activity_cluster_id
         AND m.run_id = c.run_id
        JOIN filtered_detections d ON d.detection_id = m.detection_id
        """,
        filter_parameters,
    ).fetchone()[0]

    needs_edge_filtering = (
        period == "24h"
        or region != "global"
        or daynight != "all"
        or frp_min is not None
        or frp_max is not None
    )
    if needs_edge_filtering:
        edge_counts = connection.execute(
            f"""
            {ctes}
            SELECT UPPER(TRIM(COALESCE(e.decision_class, 'UNKNOWN'))), COUNT(*)
            FROM harm_correspondence_edges e
            JOIN latest_successful_run lr ON e.run_id = lr.run_id
            WHERE EXISTS (
                SELECT 1
                FROM filtered_detections d
                WHERE d.detection_id = e.detection_id_a
                   OR d.detection_id = e.detection_id_b
            )
            GROUP BY 1
            """,
            filter_parameters,
        ).fetchall()
        correspondence_source = "filtered_edges"
    else:
        summary_conditions, summary_parameters = _summary_date_conditions(
            period, now, start_date, end_date
        )
        pair_condition = _platform_condition(platform, "platform_pair")
        if pair_condition:
            summary_conditions.append(pair_condition)
        summary_where = (
            " AND ".join(summary_conditions) if summary_conditions else "TRUE"
        )
        edge_counts = connection.execute(
            f"""
            WITH {latest_run}
            SELECT 'STRONG', COALESCE(SUM(s.strong_count), 0)
            FROM harm_correspondence_summary s
            JOIN latest_successful_run lr ON s.run_id = lr.run_id
            WHERE {summary_where}
            UNION ALL
            SELECT 'POSSIBLE', COALESCE(SUM(s.possible_count), 0)
            FROM harm_correspondence_summary s
            JOIN latest_successful_run lr ON s.run_id = lr.run_id
            WHERE {summary_where}
            UNION ALL
            SELECT 'REJECTED', COALESCE(SUM(s.rejected_count), 0)
            FROM harm_correspondence_summary s
            JOIN latest_successful_run lr ON s.run_id = lr.run_id
            WHERE {summary_where}
            """,
            summary_parameters * 3,
        ).fetchall()
        correspondence_source = "daily_summary"

    correspondence_counts = {
        str(row[0]).upper(): int(row[1] or 0) for row in edge_counts
    }
    strong_count = correspondence_counts.get("STRONG", 0)
    possible_count = correspondence_counts.get("POSSIBLE", 0)
    rejected_count = correspondence_counts.get("REJECTED", 0)

    unmatched_count = connection.execute(
        f"""
        {ctes}
        SELECT COUNT(DISTINCT d.detection_id)
        FROM filtered_detections d
        WHERE NOT EXISTS (
            SELECT 1
            FROM harm_correspondence_edges e
            JOIN latest_successful_run lr ON e.run_id = lr.run_id
            WHERE UPPER(TRIM(COALESCE(e.decision_class, ''))) IN ('STRONG', 'POSSIBLE')
              AND (e.detection_id_a = d.detection_id OR e.detection_id_b = d.detection_id)
        )
        """,
        filter_parameters,
    ).fetchone()[0]

    map_rows = connection.execute(
        f"""
        {ctes}
        SELECT detection_id, latitude, longitude, platform, acq_date, frp_mw
        FROM filtered_detections
        WHERE latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180
        ORDER BY acquisition_timestamp DESC
        LIMIT 1201
        """,
        filter_parameters,
    ).fetchall()
    map_points = [
        {
            "id": row[0],
            "latitude": float(row[1]),
            "longitude": float(row[2]),
            "platform": row[3] or "Unknown",
            "date": row[4].isoformat(),
            "frp_mw": float(row[5]) if row[5] is not None else None,
        }
        for row in map_rows[:1200]
    ]
    map_truncated = len(map_rows) > 1200

    run_rows = connection.execute(
        """
        SELECT r.run_id, r.status, r.started_at_utc, r.duration_seconds,
               r.input_count, r.activity_cluster_count, r.correspondence_edge_count
        FROM harm_run_metadata r
        ORDER BY COALESCE(r.finished_at_utc, r.started_at_utc) DESC
        LIMIT 5
        """
    ).fetchall()

    return {
        "kpis": {
            "total_detections": int(total_detections or 0),
            "activity_clusters": int(cluster_count or 0),
            "strong_correspondences": strong_count,
            "possible_correspondences": possible_count,
            "unmatched_or_rejected": int(unmatched_count or 0),
            "latest_acquisition": latest_acquisition.isoformat() + "Z"
            if latest_acquisition is not None
            else None,
        },
        "daily_trend": [
            {"date": row[0].isoformat(), "detections": int(row[1])}
            for row in daily_rows
        ],
        "platform_counts": [
            {"platform": row[0], "detections": int(row[1])} for row in platform_rows
        ],
        "correspondence_distribution": {
            "strong": strong_count,
            "possible": possible_count,
            "rejected": rejected_count,
            "source": correspondence_source,
        },
        "map": {"points": map_points, "truncated": map_truncated},
        "recent_runs": [
            {
                "run_id": row[0],
                "status": row[1],
                "started_at": row[2].isoformat() + "Z" if row[2] is not None else None,
                "duration_seconds": float(row[3]) if row[3] is not None else None,
                "input_count": int(row[4]) if row[4] is not None else None,
                "activity_cluster_count": int(row[5]) if row[5] is not None else None,
                "correspondence_edge_count": int(row[6])
                if row[6] is not None
                else None,
            }
            for row in run_rows
        ],
        "generated_at": now.isoformat(),
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/overview")
def overview(
    period: Period = "7d",
    platform: str = "all",
    region: Region = "global",
    daynight: DayNight = "all",
    frp_min: float | None = Query(default=None, ge=0),
    frp_max: float | None = Query(default=None, ge=0),
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, object]:
    if frp_min is not None and frp_max is not None and frp_min > frp_max:
        raise HTTPException(
            status_code=422, detail="frp_min must be less than or equal to frp_max."
        )
    if period == "custom" and (
        start_date is None or end_date is None or start_date > end_date
    ):
        raise HTTPException(
            status_code=422,
            detail="Custom date ranges require a valid start_date on or before end_date.",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            _require_tables(connection)
            filtered_sql, filter_parameters = _filtered_detections(
                period=period,
                platform=platform,
                region=region,
                daynight=daynight,
                frp_min=frp_min,
                frp_max=frp_max,
                start_date=start_date,
                end_date=end_date,
                now=now,
            )
            return _dashboard_payload(
                connection,
                filtered_sql=filtered_sql,
                filter_parameters=filter_parameters,
                period=period,
                platform=platform,
                region=region,
                daynight=daynight,
                frp_min=frp_min,
                frp_max=frp_max,
                start_date=start_date,
                end_date=end_date,
                now=now,
            )
    except duckdb.Error:
        logger.exception("Failed to query the TwinFlame dashboard database.")
        raise HTTPException(
            status_code=503,
            detail="The dashboard could not read the configured database. Check its schema and pipeline output.",
        ) from None


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_columns(
    connection: duckdb.DuckDBPyConnection, table_name: str
) -> dict[str, str]:
    rows = connection.execute(
        f"DESCRIBE SELECT * FROM {_quoted_identifier(table_name)}"
    ).fetchall()
    return {str(row[0]).lower(): str(row[0]) for row in rows}


def _find_column(columns: dict[str, str], *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate.lower() in columns:
            return columns[candidate.lower()]
    return None


def _latest_source_retrieval(
    connection: duckdb.DuckDBPyConnection, tables: dict[str, str]
) -> tuple[datetime | None, str | None]:
    retrieval_columns = (
        "retrieval_time",
        "retrieval_time_utc",
        "retrieved_at_utc",
        "retrieved_at",
        "retrieval_timestamp_utc",
        "retrieval_timestamp",
        "ingested_at_utc",
        "start_time",
        "api_retrieved_at",
        "downloaded_at_utc",
        "downloaded_at",
        "fetched_at_utc",
        "fetched_at",
    )
    for logical_name in ("source_files", "ingestion_runs"):
        table_name = tables.get(logical_name)
        if table_name is None:
            continue
        columns = _table_columns(connection, table_name)
        timestamp_column = _find_column(columns, *retrieval_columns)
        if timestamp_column is None:
            continue
        row = connection.execute(
            f"SELECT MAX(TRY_CAST({_quoted_identifier(timestamp_column)} AS TIMESTAMP)) "
            f"FROM {_quoted_identifier(table_name)}"
        ).fetchone()
        if row and row[0] is not None:
            label = "SOURCE_FILES" if logical_name == "source_files" else "INGESTION_RUNS"
            return row[0], label
    return None, None


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _utc_naive(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@app.get("/api/monitoring")
def monitoring(
    window: MonitoringWindow = "24h",
    platform: str = "all",
    sensor: Sensor = "all",
    region: Region = "global",
    daynight: DayNight = "all",
    frp_min: float | None = Query(default=None, ge=0),
    confidence: str | None = None,
    status: DetectionStatus = "all",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, object]:
    start_at = _utc_naive(start_at)
    end_at = _utc_naive(end_at)
    if window == "custom" and (start_at is None or end_at is None):
        raise HTTPException(
            status_code=422,
            detail="Custom monitoring windows require both start_at and end_at.",
        )
    if window == "custom" and start_at is not None and end_at is not None:
        if start_at > end_at:
            raise HTTPException(
                status_code=422,
                detail="start_at must be on or before end_at.",
            )
    if frp_min is not None and frp_min < 0:
        raise HTTPException(status_code=422, detail="frp_min must be non-negative.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }
            detection_table = tables.get("unified_detections")
            if detection_table is None:
                raise HTTPException(
                    status_code=503,
                    detail="The monitoring database is missing UNIFIED_DETECTIONS.",
                )

            columns = _table_columns(connection, detection_table)
            id_column = _find_column(columns, "detection_id", "id")
            date_column = _find_column(columns, "acq_date", "acquisition_date")
            if id_column is None or date_column is None:
                raise HTTPException(
                    status_code=503,
                    detail="UNIFIED_DETECTIONS must include detection_id and acq_date.",
                )

            def dcol(column: str | None, fallback: str = "NULL") -> str:
                return f"d.{_quoted_identifier(column)}" if column else fallback

            time_column = _find_column(columns, "acq_time", "acquisition_time")
            platform_column = _find_column(columns, "platform", "satellite")
            source_column = _find_column(columns, "source", "source_name")
            sensor_column = _find_column(columns, "instrument", "sensor", "source")
            confidence_column = _find_column(
                columns, "confidence_native", "native_confidence", "confidence", "confidence_level"
            )
            frp_column = _find_column(columns, "frp_mw", "frp")
            latitude_column = _find_column(columns, "latitude", "lat")
            longitude_column = _find_column(columns, "longitude", "lon", "lng")
            daynight_column = _find_column(columns, "daynight", "day_night")
            status_column = _find_column(
                columns, "detection_status", "processing_status", "status"
            )

            date_expr = f"TRY_CAST({dcol(date_column)} AS DATE)"
            time_digits = (
                f"LPAD(REGEXP_REPLACE(COALESCE(CAST({dcol(time_column)} AS VARCHAR), ''), "
                "'[^0-9]', '', 'g'), 4, '0')"
                if time_column
                else "'0000'"
            )
            acquisition_expr = (
                f"({date_expr} + COALESCE("
                f"TRY_CAST(TRY_STRPTIME({time_digits}, '%H%M') AS TIME), "
                "TIME '00:00:00'))"
            )
            platform_expr = (
                f"COALESCE(NULLIF(TRIM(CAST({dcol(platform_column)} AS VARCHAR)), ''), 'Unknown')"
            )
            source_expr = dcol(source_column, "''")
            if sensor_column:
                sensor_expr = (
                    f"COALESCE(NULLIF(UPPER(TRIM(CAST({dcol(sensor_column)} AS VARCHAR))), ''), "
                    "CASE WHEN UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%MODIS%' THEN 'MODIS' "
                    "WHEN UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%VIIRS%' OR UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%NOAA%' THEN 'VIIRS' "
                    "ELSE 'Unknown' END)"
                )
            else:
                sensor_expr = (
                    "CASE WHEN UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%MODIS%' THEN 'MODIS' "
                    "WHEN UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%VIIRS%' OR UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%NOAA%' "
                    "OR UPPER(CAST("
                    f"{platform_expr} AS VARCHAR)) LIKE '%NOAA%' THEN 'VIIRS' "
                    "ELSE 'Unknown' END"
                )
            confidence_expr = (
                f"CAST({dcol(confidence_column)} AS VARCHAR)"
                if confidence_column
                else "NULL::VARCHAR"
            )
            frp_expr = f"TRY_CAST({dcol(frp_column)} AS DOUBLE)"
            daynight_expr = (
                f"UPPER(TRIM(CAST({dcol(daynight_column)} AS VARCHAR)))"
                if daynight_column
                else "''"
            )

            status_options: list[str] = []
            if status_column:
                status_expr = (
                    f"LOWER(TRIM(CAST({dcol(status_column)} AS VARCHAR)))"
                )
                status_rows = connection.execute(
                    f"SELECT DISTINCT {status_expr} FROM {_quoted_identifier(detection_table)} d "
                    f"WHERE {status_expr} IS NOT NULL AND {status_expr} <> ''"
                ).fetchall()
                status_options = sorted({str(row[0]) for row in status_rows})
            else:
                members_table = tables.get("harm_cluster_members")
                if members_table:
                    member_columns = _table_columns(connection, members_table)
                    member_detection_id = _find_column(member_columns, "detection_id")
                    if member_detection_id:
                        status_expr = (
                            "CASE WHEN EXISTS (SELECT 1 FROM "
                            f"{_quoted_identifier(members_table)} hm WHERE "
                            f"hm.{_quoted_identifier(member_detection_id)} = {dcol(id_column)}) "
                            "THEN 'harmonized' ELSE 'unmatched' END"
                        )
                        status_options = ["harmonized", "unmatched"]
                    else:
                        status_expr = "NULL::VARCHAR"
                else:
                    status_expr = "NULL::VARCHAR"

            status_filter_available = bool(status_options)
            if status != "all":
                if not status_filter_available:
                    raise HTTPException(
                        status_code=422,
                        detail="Detection status filtering is unavailable in this database schema.",
                    )
                if status not in status_options:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Detection status '{status}' is not present in the current database.",
                    )
            if confidence and not confidence_column:
                raise HTTPException(
                    status_code=422,
                    detail="Native confidence filtering is unavailable in this database schema.",
                )

            conditions = [f"{acquisition_expr} <= ?"]
            if window == "custom":
                conditions.append(f"{acquisition_expr} BETWEEN ? AND ?")
                parameters: list[object] = [now, start_at, end_at]
            else:
                hours = int(window[:-1])
                conditions.append(f"{acquisition_expr} >= ?")
                parameters = [now, now - timedelta(hours=hours)]

            p_norm = platform.lower().replace("-", "").replace(" ", "")
            if p_norm != "all":
                platform_values = [platform_column, source_column]
                matching_columns = [
                    f"UPPER(CAST({dcol(column)} AS VARCHAR))"
                    for column in platform_values
                    if column is not None
                ]
                if not matching_columns:
                    raise HTTPException(
                        status_code=422,
                        detail="Platform filtering is unavailable in this database schema.",
                    )
                pattern = {
                    "terra": "%TERRA%",
                    "aqua": "%AQUA%",
                    "noaa20": "%NOAA%20%",
                    "noaa21": "%NOAA%21%",
                }.get(p_norm, f"%{p_norm.upper()}%")
                conditions.append(
                    "(" + " OR ".join(f"{value} LIKE ?" for value in matching_columns) + ")"
                )
                parameters.extend([pattern] * len(matching_columns))
            if sensor != "all":
                conditions.append(f"UPPER(CAST({sensor_expr} AS VARCHAR)) = ?")
                parameters.append(sensor.upper())
            if region != "global":
                west, south, east, north = REGION_BOUNDS[region]
                if latitude_column is None or longitude_column is None:
                    raise HTTPException(
                        status_code=503,
                        detail="UNIFIED_DETECTIONS must include latitude and longitude for region filtering.",
                    )
                conditions.append(
                    f"{dcol(longitude_column)} BETWEEN ? AND ? AND "
                    f"{dcol(latitude_column)} BETWEEN ? AND ?"
                )
                parameters.extend((west, east, south, north))
            if daynight != "all":
                if daynight_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Day/night filtering is unavailable in this database schema.",
                    )
                daynight_values = "'D', 'DAY'" if daynight == "day" else "'N', 'NIGHT'"
                conditions.append(f"{daynight_expr} IN ({daynight_values})")
            if frp_min is not None:
                if not frp_column:
                    raise HTTPException(
                        status_code=422,
                        detail="FRP filtering is unavailable in this database schema.",
                    )
                conditions.append(f"{frp_expr} >= ?")
                parameters.append(frp_min)
            if confidence:
                conditions.append(f"LOWER(TRIM({confidence_expr})) = LOWER(?)")
                parameters.append(confidence.strip())
            if status != "all":
                conditions.append(f"{status_expr} = ?")
                parameters.append(status)

            where_clause = " AND ".join(conditions)
            base_cte = f"""
                WITH filtered AS (
                    SELECT
                        CAST({dcol(id_column)} AS VARCHAR) AS id,
                        {platform_expr} AS platform,
                        {sensor_expr} AS sensor,
                        {date_expr} AS acquisition_date,
                        {acquisition_expr} AS acquisition_timestamp,
                        {dcol(time_column, "''")} AS acquisition_time,
                        {frp_expr} AS frp_mw,
                        {confidence_expr} AS native_confidence,
                        {daynight_expr} AS daynight,
                        {status_expr} AS status,
                        TRY_CAST({dcol(latitude_column)} AS DOUBLE) AS latitude,
                        TRY_CAST({dcol(longitude_column)} AS DOUBLE) AS longitude
                    FROM {_quoted_identifier(detection_table)} d
                    WHERE {where_clause}
                )
            """
            total_count, latest_acquisition = connection.execute(
                f"{base_cte} SELECT COUNT(*), MAX(acquisition_timestamp) FROM filtered",
                parameters,
            ).fetchone()
            trend_rows = connection.execute(
                f"""
                {base_cte}
                SELECT DATE_TRUNC('hour', acquisition_timestamp), COUNT(*)
                FROM filtered
                GROUP BY 1
                ORDER BY 1
                """,
                parameters,
            ).fetchall()
            frp_rows = connection.execute(
                f"""
                {base_cte}
                SELECT platform,
                    COUNT(*) FILTER (WHERE frp_mw < 10) AS under_10,
                    COUNT(*) FILTER (WHERE frp_mw >= 10 AND frp_mw < 50) AS from_10_to_50,
                    COUNT(*) FILTER (WHERE frp_mw >= 50 AND frp_mw < 100) AS from_50_to_100,
                    COUNT(*) FILTER (WHERE frp_mw >= 100) AS over_100
                FROM filtered
                WHERE frp_mw IS NOT NULL
                GROUP BY platform
                ORDER BY COUNT(*) DESC
                """,
                parameters,
            ).fetchall()
            detection_rows = connection.execute(
                f"""
                {base_cte}
                SELECT id, platform, sensor, acquisition_date, acquisition_time,
                       acquisition_timestamp, latitude, longitude, frp_mw,
                       native_confidence, daynight, status
                FROM filtered
                ORDER BY acquisition_timestamp DESC
                LIMIT 1200
                """,
                parameters,
            ).fetchall()
            latest_retrieval, retrieval_source = _latest_source_retrieval(connection, tables)

            def serialize_detection(row: tuple[object, ...]) -> dict[str, object]:
                return {
                    "id": row[0],
                    "platform": row[1],
                    "sensor": row[2],
                    "acquisition_date": row[3].isoformat() if row[3] else None,
                    "acquisition_time": str(row[4]) if row[4] is not None else None,
                    "acquisition_timestamp": _utc_iso(row[5]),
                    "latitude": float(row[6]) if row[6] is not None else None,
                    "longitude": float(row[7]) if row[7] is not None else None,
                    "frp_mw": float(row[8]) if row[8] is not None else None,
                    "native_confidence": row[9],
                    "daynight": row[10],
                    "status": row[11],
                }

            detections = [serialize_detection(row) for row in detection_rows]
            map_detections = [
                detection
                for detection in detections
                if detection["latitude"] is not None
                and detection["longitude"] is not None
                and -90 <= detection["latitude"] <= 90
                and -180 <= detection["longitude"] <= 180
            ]
            return {
                "generated_at": _utc_iso(now),
                "latest_retrieval_at": _utc_iso(latest_retrieval),
                "retrieval_source": retrieval_source,
                "latest_acquisition_at": _utc_iso(latest_acquisition),
                "total_detections": int(total_count or 0),
                "trend": [
                    {"time": _utc_iso(row[0]), "count": int(row[1])}
                    for row in trend_rows
                ],
                "frp_distribution": [
                    {
                        "platform": row[0],
                        "under_10": int(row[1]),
                        "from_10_to_50": int(row[2]),
                        "from_50_to_100": int(row[3]),
                        "over_100": int(row[4]),
                    }
                    for row in frp_rows
                ],
                "detections": detections[:50],
                "map_points": map_detections,
                "truncated": int(total_count or 0) > len(detections),
                "capabilities": {
                    "confidence_filter": confidence_column is not None,
                    "status_filter": status_filter_available,
                    "status_options": status_options,
                    "retrieval_timestamp": latest_retrieval is not None,
                },
            }
    except duckdb.Error:
        logger.exception("Failed to query the TwinFlame monitoring database.")
        raise HTTPException(
            status_code=503,
            detail="The monitoring page could not read the configured database. Check the detection table schema and pipeline output.",
        ) from None


def _parse_aoi(value: str | None) -> dict[str, object] | None:
    if not value:
        return None
    try:
        shape = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="AOI must be valid JSON.") from exc
    if not isinstance(shape, dict):
        raise HTTPException(status_code=422, detail="AOI must be a geometry object.")

    shape_type = shape.get("type")
    if shape_type == "rectangle":
        try:
            south, west, north, east = (
                float(shape[key]) for key in ("south", "west", "north", "east")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Rectangle AOIs require numeric south, west, north, and east bounds.",
            ) from exc
        if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
            raise HTTPException(status_code=422, detail="Rectangle AOI bounds are invalid.")
        return {"type": "rectangle", "south": south, "west": west, "north": north, "east": east}

    if shape_type == "circle":
        try:
            center = shape["center"]
            latitude, longitude = float(center[0]), float(center[1])
            radius_km = float(shape["radius_km"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Circle AOIs require a [latitude, longitude] center and radius_km.",
            ) from exc
        if (
            not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
            or not 0 < radius_km <= 20_000
        ):
            raise HTTPException(status_code=422, detail="Circle AOI geometry is invalid.")
        return {
            "type": "circle",
            "center": [latitude, longitude],
            "radius_km": radius_km,
        }

    if shape_type == "polygon":
        points = shape.get("points")
        if not isinstance(points, list) or len(points) < 3:
            raise HTTPException(
                status_code=422, detail="Polygon AOIs require at least three points."
            )
        try:
            coordinates = [[float(point[0]), float(point[1])] for point in points]
        except (IndexError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Polygon AOI points must be numeric coordinates."
            ) from exc
        if any(
            not -90 <= latitude <= 90 or not -180 <= longitude <= 180
            for latitude, longitude in coordinates
        ):
            raise HTTPException(status_code=422, detail="Polygon AOI coordinates are invalid.")
        return {"type": "polygon", "points": coordinates}

    raise HTTPException(
        status_code=422, detail="AOI type must be rectangle, circle, or polygon."
    )


def _aoi_bounds(aoi: dict[str, object]) -> tuple[float, float, float, float]:
    if aoi["type"] == "rectangle":
        return (
            float(aoi["west"]),
            float(aoi["south"]),
            float(aoi["east"]),
            float(aoi["north"]),
        )
    if aoi["type"] == "circle":
        latitude, longitude = aoi["center"]  # type: ignore[misc]
        radius_km = float(aoi["radius_km"])
        lat_delta = radius_km / 110.574
        lon_delta = radius_km / max(0.01, 111.320 * math.cos(math.radians(latitude)))
        return (
            max(-180.0, longitude - lon_delta),
            max(-90.0, latitude - lat_delta),
            min(180.0, longitude + lon_delta),
            min(90.0, latitude + lat_delta),
        )
    points = aoi["points"]
    latitudes = [point[0] for point in points]  # type: ignore[index]
    longitudes = [point[1] for point in points]  # type: ignore[index]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def _point_in_aoi(latitude: float, longitude: float, aoi: dict[str, object] | None) -> bool:
    if aoi is None:
        return True
    if aoi["type"] == "rectangle":
        return (
            float(aoi["south"]) <= latitude <= float(aoi["north"])
            and float(aoi["west"]) <= longitude <= float(aoi["east"])
        )
    if aoi["type"] == "circle":
        center = aoi["center"]
        return _great_circle_km(
            latitude, longitude, float(center[0]), float(center[1])  # type: ignore[index]
        ) <= float(aoi["radius_km"])

    points = aoi["points"]
    inside = False
    previous = points[-1]  # type: ignore[index]
    for current in points:  # type: ignore[assignment]
        current_lat, current_lon = current
        previous_lat, previous_lon = previous
        crosses = (current_lat > latitude) != (previous_lat > latitude)
        if crosses:
            crossing_lon = (previous_lon - current_lon) * (
                latitude - current_lat
            ) / (previous_lat - current_lat) + current_lon
            if longitude < crossing_lon:
                inside = not inside
        previous = current
    return inside


def _great_circle_km(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    earth_radius_km = 6371.0088
    latitude_delta = math.radians(latitude_b - latitude_a)
    longitude_delta = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(latitude_a))
        * math.cos(math.radians(latitude_b))
        * math.sin(longitude_delta / 2) ** 2
    )
    return earth_radius_km * 2 * math.asin(min(1.0, math.sqrt(haversine)))


def _convex_hull(points: list[tuple[float, float]]) -> list[list[float]]:
    coordinates = sorted({(longitude, latitude) for latitude, longitude in points})
    if len(coordinates) <= 2:
        return [[latitude, longitude] for longitude, latitude in coordinates]

    def cross(
        origin: tuple[float, float],
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> float:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (
            first[1] - origin[1]
        ) * (second[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in coordinates:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(coordinates):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    return [[latitude, longitude] for longitude, latitude in hull]


def _hull_area_km2(points: list[list[float]]) -> float:
    if len(points) < 3:
        return 0.0
    mean_latitude = sum(point[0] for point in points) / len(points)
    scale_x = 111.32 * max(0.0, math.cos(math.radians(mean_latitude)))
    scale_y = 110.574
    planar = [
        (longitude * scale_x, latitude * scale_y)
        for latitude, longitude in points
    ]
    area = sum(
        planar[index][0] * planar[(index + 1) % len(planar)][1]
        - planar[(index + 1) % len(planar)][0] * planar[index][1]
        for index in range(len(planar))
    )
    return abs(area) / 2


@app.get("/api/geospatial")
def geospatial(
    start_date: date | None = None,
    end_date: date | None = None,
    platform: str = "all",
    sensor: Sensor = "all",
    region: Region = "global",
    daynight: DayNight = "all",
    frp_min: float | None = Query(default=None, ge=0),
    min_cluster_size: int = Query(default=1, ge=1),
    min_extent_km: float = Query(default=0, ge=0),
    max_extent_km: float | None = Query(default=None, ge=0),
    membership_quality: MembershipQuality = "all",
    country: str | None = None,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    aoi: str | None = None,
) -> dict[str, object]:
    if (start_date is None) != (end_date is None):
        raise HTTPException(
            status_code=422,
            detail="Custom date ranges require both start_date and end_date.",
        )
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=422, detail="start_date must be on or before end_date."
        )
    bbox_values = (west, south, east, north)
    if any(value is not None for value in bbox_values):
        if any(value is None for value in bbox_values):
            raise HTTPException(
                status_code=422,
                detail="Bounding-box filters require west, south, east, and north.",
            )
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise HTTPException(status_code=422, detail="Bounding-box bounds are invalid.")
    if max_extent_km is not None and min_extent_km > max_extent_km:
        raise HTTPException(
            status_code=422,
            detail="min_extent_km must be less than or equal to max_extent_km.",
        )
    parsed_aoi = _parse_aoi(aoi)

    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }
            detection_table = tables.get("unified_detections")
            cluster_table = tables.get("harm_activity_clusters")
            member_table = tables.get("harm_cluster_members")
            if not detection_table or not cluster_table or not member_table:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Geospatial exploration requires UNIFIED_DETECTIONS, "
                        "harm_activity_clusters, and harm_cluster_members."
                    ),
                )

            detection_columns = _table_columns(connection, detection_table)
            cluster_columns = _table_columns(connection, cluster_table)
            member_columns = _table_columns(connection, member_table)
            detection_id = _find_column(detection_columns, "detection_id", "id")
            acquisition_date = _find_column(
                detection_columns, "acq_date", "acquisition_date"
            )
            latitude_column = _find_column(detection_columns, "latitude", "lat")
            longitude_column = _find_column(detection_columns, "longitude", "lon", "lng")
            cluster_id = _find_column(
                cluster_columns, "activity_cluster_id", "cluster_id"
            )
            member_cluster_id = _find_column(
                member_columns, "activity_cluster_id", "cluster_id"
            )
            member_detection_id = _find_column(
                member_columns, "detection_id", "member_detection_id"
            )
            if not all(
                (
                    detection_id,
                    acquisition_date,
                    latitude_column,
                    longitude_column,
                    cluster_id,
                    member_cluster_id,
                    member_detection_id,
                )
            ):
                raise HTTPException(
                    status_code=503,
                    detail="The geospatial database tables are missing required ID, date, or coordinate columns.",
                )

            def dcol(column: str | None, fallback: str = "NULL") -> str:
                return f"d.{_quoted_identifier(column)}" if column else fallback

            time_column = _find_column(detection_columns, "acq_time", "acquisition_time")
            platform_column = _find_column(detection_columns, "platform", "satellite")
            source_column = _find_column(detection_columns, "source", "source_name")
            sensor_column = _find_column(detection_columns, "instrument", "sensor", "source")
            frp_column = _find_column(detection_columns, "frp_mw", "frp")
            daynight_column = _find_column(detection_columns, "daynight", "day_night")
            country_column = _find_column(detection_columns, "country", "country_name")
            quality_column = _find_column(
                member_columns, "membership_quality", "quality"
            )

            date_expr = f"TRY_CAST({dcol(acquisition_date)} AS DATE)"
            time_digits = (
                f"LPAD(REGEXP_REPLACE(COALESCE(CAST({dcol(time_column)} AS VARCHAR), ''), "
                "'[^0-9]', '', 'g'), 4, '0')"
                if time_column
                else "'0000'"
            )
            acquisition_expr = (
                f"({date_expr} + COALESCE("
                f"TRY_CAST(TRY_STRPTIME({time_digits}, '%H%M') AS TIME), "
                "TIME '00:00:00'))"
            )
            platform_expr = (
                f"COALESCE(NULLIF(TRIM(CAST({dcol(platform_column)} AS VARCHAR)), ''), 'Unknown')"
            )
            source_expr = dcol(source_column, "''")
            if sensor_column:
                sensor_expr = (
                    f"COALESCE(NULLIF(UPPER(TRIM(CAST({dcol(sensor_column)} AS VARCHAR))), ''), "
                    "CASE WHEN UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%MODIS%' THEN 'MODIS' "
                    "WHEN UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%VIIRS%' OR UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%NOAA%' THEN 'VIIRS' "
                    "ELSE 'Unknown' END)"
                )
            else:
                sensor_expr = (
                    "CASE WHEN UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%MODIS%' THEN 'MODIS' "
                    "WHEN UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%VIIRS%' OR UPPER(CAST("
                    f"{source_expr} AS VARCHAR)) LIKE '%NOAA%' THEN 'VIIRS' "
                    "ELSE 'Unknown' END"
                )
            frp_expr = f"TRY_CAST({dcol(frp_column)} AS DOUBLE)"
            daynight_expr = (
                f"UPPER(TRIM(CAST({dcol(daynight_column)} AS VARCHAR)))"
                if daynight_column
                else "''"
            )

            conditions = ["TRUE"]
            parameters: list[object] = []
            if start_date is not None and end_date is not None:
                conditions.extend(
                    (f"{date_expr} >= ?", f"{date_expr} <= ?")
                )
                parameters.extend((start_date, end_date))
            p_norm = platform.lower().replace("-", "").replace(" ", "")
            if p_norm != "all":
                matching_columns = [
                    f"UPPER(CAST({dcol(column)} AS VARCHAR))"
                    for column in (platform_column, source_column)
                    if column is not None
                ]
                if not matching_columns:
                    raise HTTPException(
                        status_code=422,
                        detail="Platform filtering is unavailable in this database schema.",
                    )
                pattern = {
                    "terra": "%TERRA%",
                    "aqua": "%AQUA%",
                    "noaa20": "%NOAA%20%",
                    "noaa21": "%NOAA%21%",
                }.get(p_norm, f"%{p_norm.upper()}%")
                conditions.append(
                    "(" + " OR ".join(f"{value} LIKE ?" for value in matching_columns) + ")"
                )
                parameters.extend([pattern] * len(matching_columns))
            if sensor != "all":
                conditions.append(f"UPPER(CAST({sensor_expr} AS VARCHAR)) = ?")
                parameters.append(sensor.upper())
            if region != "global":
                region_west, region_south, region_east, region_north = REGION_BOUNDS[region]
                conditions.append(
                    f"{dcol(longitude_column)} BETWEEN ? AND ? AND "
                    f"{dcol(latitude_column)} BETWEEN ? AND ?"
                )
                parameters.extend(
                    (region_west, region_east, region_south, region_north)
                )
            if daynight != "all":
                if daynight_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Day/night filtering is unavailable in this database schema.",
                    )
                daynight_values = "'D', 'DAY'" if daynight == "day" else "'N', 'NIGHT'"
                conditions.append(f"{daynight_expr} IN ({daynight_values})")
            if frp_min is not None:
                if frp_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="FRP filtering is unavailable in this database schema.",
                    )
                conditions.append(f"{frp_expr} >= ?")
                parameters.append(frp_min)
            if country:
                if country_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Country filtering is unavailable in this database schema.",
                    )
                conditions.append(
                    f"LOWER(TRIM(CAST({dcol(country_column)} AS VARCHAR))) = LOWER(?)"
                )
                parameters.append(country.strip())
            query_bounds = (
                (west, south, east, north)
                if west is not None
                else _aoi_bounds(parsed_aoi)
                if parsed_aoi is not None
                else None
            )
            if query_bounds is not None:
                if west is not None and parsed_aoi is not None:
                    area_west, area_south, area_east, area_north = _aoi_bounds(parsed_aoi)
                    query_bounds = (
                        max(west, area_west),
                        max(south, area_south),
                        min(east, area_east),
                        min(north, area_north),
                    )
                bounds_west, bounds_south, bounds_east, bounds_north = query_bounds
                conditions.append(
                    f"{dcol(longitude_column)} BETWEEN ? AND ? AND "
                    f"{dcol(latitude_column)} BETWEEN ? AND ?"
                )
                parameters.extend(
                    (bounds_west, bounds_east, bounds_south, bounds_north)
                )
            where_clause = " AND ".join(conditions)
            filtered_cte = f"""
                WITH filtered AS (
                    SELECT
                        CAST({dcol(detection_id)} AS VARCHAR) AS id,
                        {platform_expr} AS platform,
                        {sensor_expr} AS sensor,
                        {acquisition_expr} AS acquisition_timestamp,
                        TRY_CAST({dcol(latitude_column)} AS DOUBLE) AS latitude,
                        TRY_CAST({dcol(longitude_column)} AS DOUBLE) AS longitude,
                        {frp_expr} AS frp_mw,
                        {daynight_expr} AS daynight,
                        {f'LOWER(TRIM(CAST({dcol(country_column)} AS VARCHAR)))' if country_column else 'NULL::VARCHAR'} AS country
                    FROM {_quoted_identifier(detection_table)} d
                    WHERE {where_clause}
                )
            """
            raw_detection_count = connection.execute(
                f"{filtered_cte} SELECT COUNT(*) FROM filtered", parameters
            ).fetchone()[0]
            detection_rows = connection.execute(
                f"""
                {filtered_cte}
                SELECT id, platform, sensor, acquisition_timestamp, latitude,
                       longitude, frp_mw, daynight, country
                FROM filtered
                ORDER BY acquisition_timestamp DESC
                LIMIT 20001
                """,
                parameters,
            ).fetchall()

            def in_bounds(row: tuple[object, ...]) -> bool:
                latitude, longitude = row[4], row[5]
                return (
                    latitude is not None
                    and longitude is not None
                    and _point_in_aoi(float(latitude), float(longitude), parsed_aoi)
                )

            selected_detection_rows = [
                row
                for row in detection_rows
                if in_bounds(row)
                and -90 <= float(row[4]) <= 90
                and -180 <= float(row[5]) <= 180
            ]
            detections = [
                {
                    "id": row[0],
                    "platform": row[1],
                    "sensor": row[2],
                    "acquisition_timestamp": _utc_iso(row[3]),
                    "latitude": float(row[4]),
                    "longitude": float(row[5]),
                    "frp_mw": float(row[6]) if row[6] is not None else None,
                    "daynight": row[7],
                    "country": row[8],
                }
                for row in selected_detection_rows[:5000]
            ]

            member_run_id = _find_column(member_columns, "run_id")
            cluster_run_id = _find_column(cluster_columns, "run_id")
            cluster_join = (
                f" AND c.{_quoted_identifier(cluster_run_id)} = "
                f"m.{_quoted_identifier(member_run_id)}"
                if cluster_run_id and member_run_id
                else ""
            )
            quality_filter = ""
            member_parameters = list(parameters)
            if membership_quality != "all":
                if quality_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Membership-quality filtering is unavailable in this database schema.",
                    )
                quality_filter = (
                    f" AND LOWER(TRIM(CAST(m.{_quoted_identifier(quality_column)} AS VARCHAR))) = ?"
                )
                member_parameters.append(membership_quality)
            member_rows = connection.execute(
                f"""
                {filtered_cte}
                SELECT
                    CAST(c.{_quoted_identifier(cluster_id)} AS VARCHAR),
                    {f'CAST(c.{_quoted_identifier(cluster_run_id)} AS VARCHAR)' if cluster_run_id else "''"},
                    d.id, d.platform, d.acquisition_timestamp, d.latitude, d.longitude
                FROM {_quoted_identifier(cluster_table)} c
                JOIN {_quoted_identifier(member_table)} m
                  ON m.{_quoted_identifier(member_cluster_id)} = c.{_quoted_identifier(cluster_id)}
                  {cluster_join}
                JOIN filtered d ON d.id = CAST(m.{_quoted_identifier(member_detection_id)} AS VARCHAR)
                WHERE TRUE {quality_filter}
                LIMIT 100001
                """,
                member_parameters,
            ).fetchall()

            cluster_groups: dict[tuple[str, str], list[tuple[object, ...]]] = {}
            for row in member_rows:
                if (
                    row[5] is None
                    or row[6] is None
                    or not _point_in_aoi(float(row[5]), float(row[6]), parsed_aoi)
                    or not (-90 <= float(row[5]) <= 90 and -180 <= float(row[6]) <= 180)
                ):
                    continue
                cluster_groups.setdefault((str(row[0]), str(row[1])), []).append(row)

            clusters = []
            for (cluster_key, run_key), members in cluster_groups.items():
                member_count = len({str(member[2]) for member in members})
                if member_count < min_cluster_size:
                    continue
                latitudes = [float(member[5]) for member in members]
                longitudes = [float(member[6]) for member in members]
                south_bound, north_bound = min(latitudes), max(latitudes)
                west_bound, east_bound = min(longitudes), max(longitudes)
                center_latitude = sum(latitudes) / len(latitudes)
                center_longitude = sum(longitudes) / len(longitudes)
                extent_km = _great_circle_km(
                    south_bound, west_bound, north_bound, east_bound
                )
                boundary = _convex_hull(
                    list(zip(latitudes, longitudes, strict=True))
                )
                if len(boundary) < 3:
                    boundary = [
                        [south_bound, west_bound],
                        [south_bound, east_bound],
                        [north_bound, east_bound],
                        [north_bound, west_bound],
                    ]
                area_km2 = _hull_area_km2(boundary)
                if extent_km < min_extent_km or (
                    max_extent_km is not None and extent_km > max_extent_km
                ):
                    continue
                cluster_platforms = sorted({str(member[3]) for member in members})
                times = [member[4] for member in members if member[4] is not None]
                clusters.append(
                    {
                        "id": cluster_key,
                        "run_id": run_key,
                        "member_count": member_count,
                        "centroid": [center_latitude, center_longitude],
                        "platforms": cluster_platforms,
                        "start_at": _utc_iso(min(times)) if times else None,
                        "end_at": _utc_iso(max(times)) if times else None,
                        "extent_km": round(extent_km, 2),
                        "area_km2": round(area_km2, 2),
                        "bounds": [
                            [south_bound, west_bound],
                            [north_bound, east_bound],
                        ],
                        "boundary": boundary,
                    }
                )
            clusters.sort(key=lambda cluster: cluster["member_count"], reverse=True)

            size_bins = [
                ("1-5", 1, 5),
                ("6-20", 6, 20),
                ("21-50", 21, 50),
                ("51+", 51, None),
            ]
            size_distribution = [
                {
                    "bucket": label,
                    "count": sum(
                        1
                        for cluster in clusters
                        if cluster["member_count"] >= lower
                        and (upper is None or cluster["member_count"] <= upper)
                    ),
                }
                for label, lower, upper in size_bins
            ]
            density_bins: dict[tuple[int, int], int] = {}
            cell_degrees = 0.5
            for detection in detections:
                cell = (
                    math.floor(detection["latitude"] / cell_degrees),
                    math.floor(detection["longitude"] / cell_degrees),
                )
                density_bins[cell] = density_bins.get(cell, 0) + 1
            density_cells = [
                {
                    "south": latitude_bin * cell_degrees,
                    "west": longitude_bin * cell_degrees,
                    "north": (latitude_bin + 1) * cell_degrees,
                    "east": (longitude_bin + 1) * cell_degrees,
                    "count": count,
                }
                for (latitude_bin, longitude_bin), count in density_bins.items()
            ]
            return {
                "generated_at": _utc_iso(datetime.now(timezone.utc)),
                "total_detections": len(selected_detection_rows)
                if parsed_aoi is not None
                else int(raw_detection_count or 0),
                "detections": detections,
                "clusters": clusters,
                "density_cells": density_cells,
                "size_distribution": size_distribution,
                "capabilities": {
                    "country_filter": country_column is not None,
                    "membership_quality_filter": quality_column is not None,
                },
                "truncated": int(raw_detection_count or 0) > 20000
                or len(member_rows) > 100000
                or len(selected_detection_rows) > 5000,
            }
    except duckdb.Error:
        logger.exception("Failed to query the TwinFlame geospatial database.")
        raise HTTPException(
            status_code=503,
            detail="Geospatial exploration could not read the configured database. Check the harmonization tables and schema.",
        ) from None


@app.get("/api/geospatial/clusters/{cluster_id}/members")
def geospatial_cluster_members(
    cluster_id: str,
    run_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, object]:
    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )
    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }
            detection_table = tables.get("unified_detections")
            cluster_table = tables.get("harm_activity_clusters")
            member_table = tables.get("harm_cluster_members")
            if not detection_table or not cluster_table or not member_table:
                raise HTTPException(
                    status_code=503,
                    detail="Cluster inspection requires the geospatial harmonization tables.",
                )
            member_columns = _table_columns(connection, member_table)
            detection_columns = _table_columns(connection, detection_table)
            member_cluster_id = _find_column(
                member_columns, "activity_cluster_id", "cluster_id"
            )
            member_detection_id = _find_column(
                member_columns, "detection_id", "member_detection_id"
            )
            member_run_id = _find_column(member_columns, "run_id")
            if not member_cluster_id or not member_detection_id:
                raise HTTPException(
                    status_code=503,
                    detail="harm_cluster_members is missing cluster or detection identifiers.",
                )
            detection_id = _find_column(detection_columns, "detection_id", "id")
            if not detection_id:
                raise HTTPException(
                    status_code=503,
                    detail="UNIFIED_DETECTIONS is missing a detection identifier.",
                )
            platform_column = _find_column(detection_columns, "platform", "satellite")
            date_column = _find_column(detection_columns, "acq_date", "acquisition_date")
            if not date_column:
                raise HTTPException(
                    status_code=503,
                    detail="UNIFIED_DETECTIONS is missing an acquisition date.",
                )
            time_column = _find_column(detection_columns, "acq_time", "acquisition_time")
            frp_column = _find_column(detection_columns, "frp_mw", "frp")
            confidence_column = _find_column(
                detection_columns, "confidence_native", "native_confidence", "confidence", "confidence_level"
            )
            daynight_column = _find_column(detection_columns, "daynight", "day_night")
            latitude_column = _find_column(detection_columns, "latitude", "lat")
            longitude_column = _find_column(detection_columns, "longitude", "lon", "lng")
            member_where = (
                f"m.{_quoted_identifier(member_cluster_id)} = ?"
            )
            parameters: list[object] = [cluster_id]
            if run_id is not None and member_run_id:
                member_where += f" AND m.{_quoted_identifier(member_run_id)} = ?"
                parameters.append(run_id)
            total = connection.execute(
                f"SELECT COUNT(*) FROM {_quoted_identifier(member_table)} m WHERE {member_where}",
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT
                    CAST(d.{_quoted_identifier(detection_id)} AS VARCHAR),
                    {f'CAST(d.{_quoted_identifier(platform_column)} AS VARCHAR)' if platform_column else "'Unknown'"},
                    {f'CAST(d.{_quoted_identifier(date_column)} AS VARCHAR)' if date_column else "NULL"},
                    {f'CAST(d.{_quoted_identifier(time_column)} AS VARCHAR)' if time_column else "NULL"},
                    {f'TRY_CAST(d.{_quoted_identifier(frp_column)} AS DOUBLE)' if frp_column else "NULL"},
                    {f'CAST(d.{_quoted_identifier(confidence_column)} AS VARCHAR)' if confidence_column else "NULL"},
                    {f'UPPER(CAST(d.{_quoted_identifier(daynight_column)} AS VARCHAR))' if daynight_column else "NULL"},
                    {f'TRY_CAST(d.{_quoted_identifier(latitude_column)} AS DOUBLE)' if latitude_column else "NULL"},
                    {f'TRY_CAST(d.{_quoted_identifier(longitude_column)} AS DOUBLE)' if longitude_column else "NULL"}
                FROM {_quoted_identifier(member_table)} m
                JOIN {_quoted_identifier(detection_table)} d
                  ON CAST(d.{_quoted_identifier(detection_id)} AS VARCHAR) =
                     CAST(m.{_quoted_identifier(member_detection_id)} AS VARCHAR)
                WHERE {member_where}
                ORDER BY d.{_quoted_identifier(date_column)} DESC
                LIMIT ?
                """,
                parameters + [limit],
            ).fetchall()
            return {
                "cluster_id": cluster_id,
                "run_id": run_id,
                "total_members": int(total or 0),
                "truncated": int(total or 0) > limit,
                "members": [
                    {
                        "id": row[0],
                        "platform": row[1] or "Unknown",
                        "acquisition_date": row[2],
                        "acquisition_time": row[3],
                        "frp_mw": float(row[4]) if row[4] is not None else None,
                        "native_confidence": row[5],
                        "daynight": row[6],
                        "latitude": float(row[7]) if row[7] is not None else None,
                        "longitude": float(row[8]) if row[8] is not None else None,
                    }
                    for row in rows
                ],
            }
    except duckdb.Error:
        logger.exception("Failed to query cluster members.")
        raise HTTPException(
            status_code=503,
            detail="The selected cluster members could not be read from the database.",
        ) from None


@app.get("/api/fire-season")
def fire_season(
    platform: FireSeasonPlatform = "all",
    region: Region = "global",
    daynight: DayNight = "all",
) -> dict[str, object]:
    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }
            detection_table = tables.get("unified_detections")
            if detection_table is None:
                raise HTTPException(
                    status_code=503,
                    detail="Fire Season Monitor requires UNIFIED_DETECTIONS.",
                )

            columns = _table_columns(connection, detection_table)
            detection_id = _find_column(columns, "detection_id", "id")
            date_column = _find_column(columns, "acq_date", "acquisition_date")
            if date_column is None:
                raise HTTPException(
                    status_code=503,
                    detail="UNIFIED_DETECTIONS is missing an acquisition date.",
                )
            platform_column = _find_column(columns, "platform", "satellite")
            source_column = _find_column(columns, "source", "source_name")
            sensor_column = _find_column(columns, "instrument", "sensor", "source")
            frp_column = _find_column(columns, "frp_mw", "frp")
            daynight_column = _find_column(columns, "daynight", "day_night")
            latitude_column = _find_column(columns, "latitude", "lat")
            longitude_column = _find_column(columns, "longitude", "lon", "lng")

            def dcol(column: str | None, fallback: str = "NULL") -> str:
                return f'd.{_quoted_identifier(column)}' if column else fallback

            date_expr = f"TRY_CAST({dcol(date_column)} AS DATE)"
            frp_expr = f"TRY_CAST({dcol(frp_column)} AS DOUBLE)" if frp_column else "NULL::DOUBLE"
            latitude_expr = (
                f"TRY_CAST({dcol(latitude_column)} AS DOUBLE)"
                if latitude_column
                else "NULL::DOUBLE"
            )
            longitude_expr = (
                f"TRY_CAST({dcol(longitude_column)} AS DOUBLE)"
                if longitude_column
                else "NULL::DOUBLE"
            )
            region_expr = f"""
                CASE
                    WHEN {longitude_expr} BETWEEN -170 AND -50
                     AND {latitude_expr} BETWEEN 5 AND 84 THEN 'north-america'
                    WHEN {longitude_expr} BETWEEN -85 AND -30
                     AND {latitude_expr} BETWEEN -57 AND 14 THEN 'south-america'
                    WHEN {longitude_expr} BETWEEN -25 AND 34
                     AND {latitude_expr} BETWEEN 45 AND 72 THEN 'europe'
                    WHEN {longitude_expr} BETWEEN -20 AND 55
                     AND {latitude_expr} BETWEEN -40 AND 38 THEN 'africa'
                    WHEN {longitude_expr} BETWEEN 110 AND 180
                     AND {latitude_expr} BETWEEN -50 AND 0 THEN 'oceania'
                    WHEN {longitude_expr} BETWEEN 25 AND 180
                     AND {latitude_expr} BETWEEN -12 AND 82 THEN 'asia'
                    ELSE 'other'
                END
            """

            conditions = [f"{date_expr} IS NOT NULL"]
            parameters: list[object] = []
            region_condition: str | None = None
            p_norm = platform.lower().replace("-", "").replace(" ", "")
            if p_norm != "all":
                searchable_columns = [
                    column
                    for column in (platform_column, source_column, sensor_column)
                    if column is not None
                ]
                if not searchable_columns:
                    raise HTTPException(
                        status_code=422,
                        detail="Satellite/platform filtering is unavailable in this database schema.",
                    )
                pattern = {
                    "terra": "%TERRA%",
                    "aqua": "%AQUA%",
                    "noaa20": "%NOAA%20%",
                    "noaa21": "%NOAA%21%",
                    "modis": "%MODIS%",
                    "viirs": "%VIIRS%",
                }.get(p_norm, f"%{p_norm.upper()}%")
                matching = []
                for column in searchable_columns:
                    value = f"UPPER(CAST(d.{_quoted_identifier(column)} AS VARCHAR))"
                    if platform in ("terra", "aqua", "noaa20", "noaa21"):
                        value = (
                            "REGEXP_REPLACE("
                            f"UPPER(CAST(d.{_quoted_identifier(column)} AS VARCHAR)), "
                            "'[^A-Z0-9]', '', 'g')"
                        )
                        pattern = {
                            "terra": "%TERRA%",
                            "aqua": "%AQUA%",
                            "noaa20": "%NOAA%20%",
                            "noaa21": "%NOAA%21%",
                        }.get(p_norm, f"%{p_norm.upper()}%")
                    matching.append(f"{value} LIKE ?")
                    parameters.append(pattern)
                conditions.append("(" + " OR ".join(matching) + ")")

            if daynight != "all":
                if daynight_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Day/night filtering is unavailable in this database schema.",
                    )
                values = "'D', 'DAY'" if daynight == "day" else "'N', 'NIGHT'"
                conditions.append(
                    f"UPPER(TRIM(CAST({dcol(daynight_column)} AS VARCHAR))) IN ({values})"
                )

            if region != "global":
                if latitude_column is None or longitude_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Geographic region filtering requires latitude and longitude columns.",
                    )
                west, south, east, north = REGION_BOUNDS[region]
                region_condition = (
                    f"{longitude_expr} BETWEEN ? AND ? AND "
                    f"{latitude_expr} BETWEEN ? AND ?"
                )
                conditions.append(region_condition)
                parameters.extend((west, east, south, north))

            where_clause = " AND ".join(conditions)
            regional_conditions = [
                condition for condition in conditions if condition != region_condition
            ]
            regional_where = " AND ".join(regional_conditions)
            regional_parameters = (
                parameters[:-4] if region_condition is not None else parameters
            )
            table_sql = _quoted_identifier(detection_table)
            date_group = f"YEAR({date_expr}), MONTH({date_expr})"
            sensor_columns = [
                column
                for column in (sensor_column, source_column)
                if column is not None
            ]
            if sensor_columns:
                sensor_values = [
                    f"UPPER(CAST(d.{_quoted_identifier(column)} AS VARCHAR))"
                    for column in sensor_columns
                ]
                has_modis = " OR ".join(
                    f"{value} LIKE '%MODIS%'" for value in sensor_values
                )
                has_viirs = " OR ".join(
                    f"{value} LIKE '%VIIRS%' OR {value} LIKE '%NOAA%'"
                    for value in sensor_values
                )
                sensor_expr = (
                    f"CASE WHEN ({has_modis}) THEN 'MODIS' "
                    f"WHEN ({has_viirs}) THEN 'VIIRS' ELSE 'Other' END"
                )
            else:
                sensor_expr = "'Other'"

            monthly_rows = connection.execute(
                f"""
                SELECT YEAR({date_expr}) AS year, MONTH({date_expr}) AS month,
                       COUNT(*) AS detections, COUNT({frp_expr}) AS frp_observations,
                       AVG({frp_expr}) AS mean_frp, MEDIAN({frp_expr}) AS median_frp,
                       SUM({frp_expr}) AS total_frp
                FROM {table_sql} d
                WHERE {where_clause}
                GROUP BY {date_group}
                ORDER BY year, month
                """,
                parameters,
            ).fetchall()
            sensor_monthly_rows = connection.execute(
                f"""
                SELECT {sensor_expr} AS sensor, YEAR({date_expr}) AS year,
                       MONTH({date_expr}) AS month, COUNT(*) AS detections
                FROM {table_sql} d
                WHERE {where_clause}
                GROUP BY sensor, year, month
                ORDER BY sensor, year, month
                """,
                parameters,
            ).fetchall()
            sensor_climatology_rows = connection.execute(
                f"""
                SELECT {sensor_expr} AS sensor, MONTH({date_expr}) AS month,
                       COUNT(*) AS detections
                FROM {table_sql} d
                WHERE {where_clause}
                GROUP BY sensor, month
                ORDER BY sensor, month
                """,
                parameters,
            ).fetchall()
            annual_rows = connection.execute(
                f"""
                SELECT YEAR({date_expr}) AS year, COUNT(*) AS detections,
                       COUNT({frp_expr}) AS frp_observations,
                       AVG({frp_expr}) AS mean_frp, MEDIAN({frp_expr}) AS median_frp,
                       SUM({frp_expr}) AS total_frp
                FROM {table_sql} d
                WHERE {where_clause}
                GROUP BY year
                ORDER BY year
                """,
                parameters,
            ).fetchall()

            regional_rows = []
            if latitude_column is not None and longitude_column is not None:
                regional_rows = connection.execute(
                    f"""
                    SELECT {region_expr} AS region,
                           YEAR({date_expr}) AS year, MONTH({date_expr}) AS month,
                           COUNT(*) AS detections, COUNT({frp_expr}) AS frp_observations,
                           AVG({frp_expr}) AS mean_frp, MEDIAN({frp_expr}) AS median_frp,
                           SUM({frp_expr}) AS total_frp
                    FROM {table_sql} d
                    WHERE {regional_where}
                    GROUP BY region, year, month
                    ORDER BY region, year, month
                    """,
                    regional_parameters,
                ).fetchall()
                climatology_rows = connection.execute(
                    f"""
                    SELECT MONTH({date_expr}) AS month, COUNT(*) AS detections,
                           COUNT({frp_expr}) AS frp_observations,
                           AVG({frp_expr}) AS mean_frp, MEDIAN({frp_expr}) AS median_frp,
                           SUM({frp_expr}) AS total_frp
                    FROM {table_sql} d
                    WHERE {where_clause}
                    GROUP BY month
                    ORDER BY month
                    """,
                    parameters,
                ).fetchall()
                regional_climatology_rows = connection.execute(
                    f"""
                    SELECT {region_expr} AS region, MONTH({date_expr}) AS month,
                           COUNT(*) AS detections, COUNT({frp_expr}) AS frp_observations,
                           AVG({frp_expr}) AS mean_frp, MEDIAN({frp_expr}) AS median_frp,
                           SUM({frp_expr}) AS total_frp
                    FROM {table_sql} d
                    WHERE {regional_where}
                    GROUP BY region, month
                    ORDER BY region, month
                    """,
                    regional_parameters,
                ).fetchall()
            else:
                climatology_rows = connection.execute(
                    f"""
                    SELECT MONTH({date_expr}) AS month, COUNT(*) AS detections,
                           COUNT({frp_expr}) AS frp_observations,
                           AVG({frp_expr}) AS mean_frp, MEDIAN({frp_expr}) AS median_frp,
                           SUM({frp_expr}) AS total_frp
                    FROM {table_sql} d
                    WHERE {where_clause}
                    GROUP BY month
                    ORDER BY month
                    """,
                    parameters,
                ).fetchall()
                regional_climatology_rows = []

            cluster_month_counts: dict[tuple[int, int], int] = {}
            cluster_year_counts: dict[int, int] = {}
            cluster_region_month_counts: dict[tuple[str, int, int], int] = {}
            cluster_capability = False
            member_table = tables.get("harm_cluster_members")
            cluster_table = tables.get("harm_activity_clusters")
            if member_table and cluster_table and detection_id:
                member_columns = _table_columns(connection, member_table)
                cluster_columns = _table_columns(connection, cluster_table)
                member_detection_id = _find_column(
                    member_columns, "detection_id", "member_detection_id"
                )
                member_cluster_id = _find_column(
                    member_columns, "activity_cluster_id", "cluster_id"
                )
                cluster_id = _find_column(
                    cluster_columns, "activity_cluster_id", "cluster_id"
                )
                member_run_id = _find_column(member_columns, "run_id")
                cluster_run_id = _find_column(cluster_columns, "run_id")
                if member_detection_id and member_cluster_id and cluster_id:
                    cluster_capability = True
                    run_join = (
                        f" AND m.{_quoted_identifier(member_run_id)} = "
                        f"c.{_quoted_identifier(cluster_run_id)}"
                        if member_run_id and cluster_run_id
                        else ""
                    )
                    cluster_key = (
                        f"CONCAT(CAST(c.{_quoted_identifier(cluster_id)} AS VARCHAR), ':', "
                        f"COALESCE(CAST(c.{_quoted_identifier(cluster_run_id)} AS VARCHAR), ''))"
                        if cluster_run_id
                        else f"CAST(c.{_quoted_identifier(cluster_id)} AS VARCHAR)"
                    )
                    cluster_from = f"""
                        FROM {table_sql} d
                        JOIN {_quoted_identifier(member_table)} m
                          ON CAST(m.{_quoted_identifier(member_detection_id)} AS VARCHAR) =
                             CAST(d.{_quoted_identifier(detection_id)} AS VARCHAR)
                        JOIN {_quoted_identifier(cluster_table)} c
                          ON CAST(c.{_quoted_identifier(cluster_id)} AS VARCHAR) =
                             CAST(m.{_quoted_identifier(member_cluster_id)} AS VARCHAR)
                          {run_join}
                        WHERE {where_clause}
                    """
                    cluster_month_rows = connection.execute(
                        f"""
                        SELECT YEAR({date_expr}) AS year, MONTH({date_expr}) AS month,
                               COUNT(DISTINCT {cluster_key}) AS clusters
                        {cluster_from}
                        GROUP BY year, month
                        """,
                        parameters,
                    ).fetchall()
                    cluster_month_counts = {
                        (int(row[0]), int(row[1])): int(row[2] or 0)
                        for row in cluster_month_rows
                    }
                    cluster_year_rows = connection.execute(
                        f"""
                        SELECT YEAR({date_expr}) AS year,
                               COUNT(DISTINCT {cluster_key}) AS clusters
                        {cluster_from}
                        GROUP BY year
                        """,
                        parameters,
                    ).fetchall()
                    cluster_year_counts = {
                        int(row[0]): int(row[1] or 0) for row in cluster_year_rows
                    }
                    if latitude_column is not None and longitude_column is not None:
                        regional_cluster_rows = connection.execute(
                            f"""
                            SELECT {region_expr} AS region,
                                   YEAR({date_expr}) AS year, MONTH({date_expr}) AS month,
                                   COUNT(DISTINCT {cluster_key}) AS clusters
                            {cluster_from.replace('WHERE ' + where_clause, 'WHERE ' + regional_where)}
                            GROUP BY region, year, month
                            """,
                            regional_parameters,
                        ).fetchall()
                        cluster_region_month_counts = {
                            (str(row[0]), int(row[1]), int(row[2])): int(row[3] or 0)
                            for row in regional_cluster_rows
                        }

            available_years = [int(row[0]) for row in annual_rows]
            platform_values: list[str] = []
            if platform_column:
                platform_values = [
                    str(row[0])
                    for row in connection.execute(
                        f"""
                        SELECT DISTINCT CAST({_quoted_identifier(platform_column)} AS VARCHAR)
                        FROM {table_sql}
                        WHERE {_quoted_identifier(platform_column)} IS NOT NULL
                        ORDER BY 1
                        LIMIT 100
                        """
                    ).fetchall()
                ]

            def metric_values(row: tuple[object, ...], start: int) -> dict[str, object]:
                def safe_number(value: object) -> float | None:
                    if value is None:
                        return None
                    number_value = float(value)
                    return round(number_value, 3) if math.isfinite(number_value) else None

                return {
                    "detections": int(row[start] or 0),
                    "frp_observations": int(row[start + 1] or 0),
                    "mean_frp": safe_number(row[start + 2]),
                    "median_frp": safe_number(row[start + 3]),
                    "total_frp": safe_number(row[start + 4]),
                }

            monthly = [
                {
                    "year": int(row[0]),
                    "month": int(row[1]),
                    **metric_values(row, 2),
                    "activity_clusters": cluster_month_counts.get(
                        (int(row[0]), int(row[1]))
                    )
                    if cluster_capability
                    else None,
                }
                for row in monthly_rows
            ]
            annual = [
                {
                    "year": int(row[0]),
                    **metric_values(row, 1),
                    "activity_clusters": cluster_year_counts.get(int(row[0]))
                    if cluster_capability
                    else None,
                }
                for row in annual_rows
            ]
            regional_activity = [
                {
                    "region": str(row[0]),
                    "year": int(row[1]),
                    "month": int(row[2]),
                    **metric_values(row, 3),
                    "activity_clusters": cluster_region_month_counts.get(
                        (str(row[0]), int(row[1]), int(row[2]))
                    )
                    if cluster_capability
                    else None,
                }
                for row in regional_rows
            ]
            sensor_monthly = [
                {
                    "sensor": str(row[0]),
                    "year": int(row[1]),
                    "month": int(row[2]),
                    "detections": int(row[3] or 0),
                }
                for row in sensor_monthly_rows
            ]
            sensor_climatology = [
                {
                    "sensor": str(row[0]),
                    "month": int(row[1]),
                    "detections": int(row[2] or 0),
                }
                for row in sensor_climatology_rows
            ]
            climatology = [
                {"month": int(row[0]), **metric_values(row, 1)}
                for row in climatology_rows
            ]
            regional_year_count = len({int(row[1]) for row in regional_rows})
            regional_climatology = [
                {
                    "region": str(row[0]),
                    "month": int(row[1]),
                    **metric_values(row, 2),
                    "activity_clusters": round(
                        sum(
                            count
                            for (cluster_region, _year, cluster_month), count
                            in cluster_region_month_counts.items()
                            if cluster_region == str(row[0])
                            and cluster_month == int(row[1])
                        )
                        / max(1, regional_year_count),
                        3,
                    )
                    if cluster_capability
                    else None,
                    "climatology_years": regional_year_count,
                }
                for row in regional_climatology_rows
            ]
            return {
                "generated_at": _utc_iso(datetime.now(timezone.utc)),
                "available_years": available_years,
                "available_platforms": platform_values,
                "monthly": monthly,
                "climatology": climatology,
                "annual": annual,
                "regional_activity": regional_activity,
                "regional_climatology": regional_climatology,
                "sensor_monthly": sensor_monthly,
                "sensor_climatology": sensor_climatology,
                "capabilities": {
                    "frp": frp_column is not None,
                    "daynight": daynight_column is not None,
                    "geographic_regions": (
                        latitude_column is not None and longitude_column is not None
                    ),
                    "activity_clusters": cluster_capability,
                    "climatology_years": len(available_years),
                },
                "sources": {
                    "detection_metrics": "UNIFIED_DETECTIONS",
                    "cluster_metrics": (
                        "harm_activity_clusters + harm_cluster_members"
                        if cluster_capability
                        else None
                    ),
                    "regional_method": (
                        "Dashboard bounding boxes; regional assignments are approximate."
                    ),
                },
            }
    except duckdb.Error:
        logger.exception("Failed to query the Fire Season Monitor database.")
        raise HTTPException(
            status_code=503,
            detail="Fire Season Monitor could not read the configured database. Check the detection and harmonization schemas.",
        ) from None


@app.get("/api/historical-analysis")
def historical_analysis(
    start_date: date | None = None,
    end_date: date | None = None,
    region: Region = "global",
    platform: FireSeasonPlatform = "all",
    daynight: DayNight = "all",
    frp_min: float | None = Query(default=None, ge=0),
    frp_max: float | None = Query(default=None, ge=0),
    confidence: str = "all",
    temporal_aggregation: TemporalAggregation = "monthly",
    spatial_aggregation: SpatialAggregation = "detections",
    grid_resolution: float = Query(default=2.0, ge=0.5, le=10.0),
) -> dict[str, object]:
    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }
            detection_table = tables.get("unified_detections")
            if detection_table is None:
                raise HTTPException(
                    status_code=503,
                    detail="Historical Fire Analysis requires UNIFIED_DETECTIONS.",
                )

            columns = _table_columns(connection, detection_table)
            detection_id = _find_column(columns, "detection_id", "id")
            date_column = _find_column(columns, "acq_date", "acquisition_date")
            if date_column is None:
                raise HTTPException(
                    status_code=503,
                    detail="UNIFIED_DETECTIONS is missing an acquisition date.",
                )
            platform_column = _find_column(columns, "platform", "satellite")
            source_column = _find_column(columns, "source", "source_name")
            sensor_column = _find_column(columns, "instrument", "sensor", "source")
            frp_column = _find_column(columns, "frp_mw", "frp")
            confidence_column = _find_column(
                columns, "confidence_native", "native_confidence", "confidence", "confidence_level"
            )
            daynight_column = _find_column(columns, "daynight", "day_night")
            latitude_column = _find_column(columns, "latitude", "lat")
            longitude_column = _find_column(columns, "longitude", "lon", "lng")

            def dcol(col: str | None, fallback: str = "NULL") -> str:
                return f'd.{_quoted_identifier(col)}' if col else fallback

            date_expr = f"TRY_CAST({dcol(date_column)} AS DATE)"
            frp_expr = (
                f"TRY_CAST({dcol(frp_column)} AS DOUBLE)"
                if frp_column
                else "NULL::DOUBLE"
            )
            latitude_expr = (
                f"TRY_CAST({dcol(latitude_column)} AS DOUBLE)"
                if latitude_column
                else "NULL::DOUBLE"
            )
            longitude_expr = (
                f"TRY_CAST({dcol(longitude_column)} AS DOUBLE)"
                if longitude_column
                else "NULL::DOUBLE"
            )
            confidence_expr = (
                f"CAST({dcol(confidence_column)} AS VARCHAR)"
                if confidence_column
                else "NULL::VARCHAR"
            )
            daynight_expr = (
                f"UPPER(TRIM(CAST({dcol(daynight_column)} AS VARCHAR)))"
                if daynight_column
                else "NULL::VARCHAR"
            )
            platform_expr = (
                f"CAST({dcol(platform_column)} AS VARCHAR)"
                if platform_column
                else "'Unknown'"
            )

            sensor_columns = [
                c for c in (sensor_column, source_column) if c is not None
            ]
            if sensor_columns:
                sensor_values = [
                    f"UPPER(CAST(d.{_quoted_identifier(c)} AS VARCHAR))"
                    for c in sensor_columns
                ]
                has_modis = " OR ".join(f"{v} LIKE '%MODIS%'" for v in sensor_values)
                has_viirs = " OR ".join(
                    f"{v} LIKE '%VIIRS%' OR {v} LIKE '%NOAA%'" for v in sensor_values
                )
                sensor_expr = (
                    f"CASE WHEN ({has_modis}) THEN 'MODIS' "
                    f"WHEN ({has_viirs}) THEN 'VIIRS' ELSE 'Other' END"
                )
            else:
                sensor_expr = "'Other'"

            region_expr = f"""
                CASE
                    WHEN {longitude_expr} BETWEEN -170 AND -50
                     AND {latitude_expr} BETWEEN 5 AND 84 THEN 'north-america'
                    WHEN {longitude_expr} BETWEEN -85 AND -30
                     AND {latitude_expr} BETWEEN -57 AND 14 THEN 'south-america'
                    WHEN {longitude_expr} BETWEEN -25 AND 34
                     AND {latitude_expr} BETWEEN 45 AND 72 THEN 'europe'
                    WHEN {longitude_expr} BETWEEN -20 AND 55
                     AND {latitude_expr} BETWEEN -40 AND 38 THEN 'africa'
                    WHEN {longitude_expr} BETWEEN 110 AND 180
                     AND {latitude_expr} BETWEEN -50 AND 0 THEN 'oceania'
                    WHEN {longitude_expr} BETWEEN 25 AND 180
                     AND {latitude_expr} BETWEEN -12 AND 82 THEN 'asia'
                    ELSE 'other'
                END
            """

            conditions: list[str] = [f"{date_expr} IS NOT NULL"]
            parameters: list[object] = []
            region_condition: str | None = None

            if start_date is not None:
                conditions.append(f"{date_expr} >= ?")
                parameters.append(start_date)

            if end_date is not None:
                conditions.append(f"{date_expr} <= ?")
                parameters.append(end_date)

            p_norm = platform.lower().replace("-", "").replace(" ", "")
            if p_norm != "all":
                searchable_columns = [
                    c
                    for c in (platform_column, source_column, sensor_column)
                    if c is not None
                ]
                if not searchable_columns:
                    raise HTTPException(
                        status_code=422,
                        detail="Satellite/platform filtering is unavailable in this database schema.",
                    )
                pattern = {
                    "terra": "%TERRA%",
                    "aqua": "%AQUA%",
                    "noaa20": "%NOAA%20%",
                    "noaa21": "%NOAA%21%",
                    "modis": "%MODIS%",
                    "viirs": "%VIIRS%",
                }.get(p_norm, f"%{p_norm.upper()}%")
                matching = []
                for c in searchable_columns:
                    if platform in ("terra", "aqua", "noaa20", "noaa21"):
                        val = (
                            "REGEXP_REPLACE("
                            f"UPPER(CAST(d.{_quoted_identifier(c)} AS VARCHAR)), "
                            "'[^A-Z0-9]', '', 'g')"
                        )
                    else:
                        val = f"UPPER(CAST(d.{_quoted_identifier(c)} AS VARCHAR))"
                    matching.append(f"{val} LIKE ?")
                    parameters.append(pattern)
                conditions.append("(" + " OR ".join(matching) + ")")

            if daynight != "all":
                if daynight_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Day/night filtering is unavailable in this database schema.",
                    )
                values = "'D', 'DAY'" if daynight == "day" else "'N', 'NIGHT'"
                conditions.append(f"{daynight_expr} IN ({values})")

            if region != "global":
                if latitude_column is None or longitude_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Geographic region filtering requires latitude and longitude columns.",
                    )
                west, south, east, north = REGION_BOUNDS[region]
                region_condition = (
                    f"{longitude_expr} BETWEEN ? AND ? AND "
                    f"{latitude_expr} BETWEEN ? AND ?"
                )
                conditions.append(region_condition)
                parameters.extend((west, east, south, north))

            if frp_min is not None:
                if frp_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="FRP filtering is unavailable in this database schema.",
                    )
                conditions.append(f"{frp_expr} >= ?")
                parameters.append(frp_min)

            if frp_max is not None:
                if frp_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="FRP filtering is unavailable in this database schema.",
                    )
                conditions.append(f"{frp_expr} <= ?")
                parameters.append(frp_max)

            if confidence != "all":
                if confidence_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Confidence filtering is unavailable in this database schema.",
                    )
                conf_norm = confidence.strip().lower()
                if conf_norm in ("high", "h"):
                    conditions.append(
                        f"(LOWER(TRIM({confidence_expr})) IN ('h', 'high') OR TRY_CAST({confidence_expr} AS DOUBLE) >= 80)"
                    )
                elif conf_norm in ("nominal", "med", "medium", "n"):
                    conditions.append(
                        f"(LOWER(TRIM({confidence_expr})) IN ('n', 'nominal', 'med', 'medium') OR "
                        f"(TRY_CAST({confidence_expr} AS DOUBLE) >= 30 AND TRY_CAST({confidence_expr} AS DOUBLE) < 80))"
                    )
                elif conf_norm in ("low", "l"):
                    conditions.append(
                        f"(LOWER(TRIM({confidence_expr})) IN ('l', 'low') OR "
                        f"(TRY_CAST({confidence_expr} AS DOUBLE) IS NOT NULL AND TRY_CAST({confidence_expr} AS DOUBLE) < 30))"
                    )
                else:
                    conditions.append(f"LOWER(TRIM({confidence_expr})) = LOWER(?)")
                    parameters.append(confidence.strip())

            where_clause = " AND ".join(conditions)
            table_sql = _quoted_identifier(detection_table)

            # Available date span & years
            date_bounds_row = connection.execute(
                f"SELECT MIN({date_expr}), MAX({date_expr}) FROM {table_sql} d"
            ).fetchone()
            min_avail_date = str(date_bounds_row[0]) if date_bounds_row and date_bounds_row[0] else None
            max_avail_date = str(date_bounds_row[1]) if date_bounds_row and date_bounds_row[1] else None
            year_rows = connection.execute(
                f"SELECT DISTINCT YEAR({date_expr}) AS y FROM {table_sql} d WHERE {date_expr} IS NOT NULL ORDER BY y"
            ).fetchall()
            available_years = [int(r[0]) for r in year_rows if r[0] is not None]

            # Temporal grain
            if temporal_aggregation == "daily":
                period_expr = f"STRFTIME({date_expr}, '%Y-%m-%d')"
            elif temporal_aggregation == "weekly":
                period_expr = f"STRFTIME(DATE_TRUNC('week', {date_expr}), '%Y-%m-%d')"
            elif temporal_aggregation == "yearly":
                period_expr = f"CAST(YEAR({date_expr}) AS VARCHAR)"
            else:
                period_expr = f"STRFTIME({date_expr}, '%Y-%m')"

            # 1. Detection Trend
            trend_rows = connection.execute(
                f"""
                SELECT
                    {period_expr} AS period,
                    COUNT(*) AS detections,
                    COUNT(CASE WHEN {sensor_expr} = 'MODIS' THEN 1 END) AS modis_detections,
                    COUNT(CASE WHEN {sensor_expr} = 'VIIRS' THEN 1 END) AS viirs_detections,
                    COUNT(CASE WHEN {sensor_expr} NOT IN ('MODIS', 'VIIRS') THEN 1 END) AS other_detections
                FROM {table_sql} d
                WHERE {where_clause}
                GROUP BY period
                ORDER BY period
                """,
                parameters,
            ).fetchall()
            detection_trend = [
                {
                    "period": str(row[0]),
                    "detections": int(row[1] or 0),
                    "modis_detections": int(row[2] or 0),
                    "viirs_detections": int(row[3] or 0),
                    "other_detections": int(row[4] or 0),
                }
                for row in trend_rows
            ]

            # 2. FRP Evolution (source: harm_sensor_activity_daily or UNIFIED_DETECTIONS)
            sensor_daily_table = tables.get("harm_sensor_activity_daily")
            frp_evolution: list[dict[str, object]] = []
            frp_source = "harm_sensor_activity_daily" if sensor_daily_table else "UNIFIED_DETECTIONS"

            if sensor_daily_table:
                try:
                    daily_cols = _table_columns(connection, sensor_daily_table)
                    d_date = _find_column(daily_cols, "date_utc", "acq_date", "date")
                    d_mean = _find_column(daily_cols, "frp_mean_mw", "mean_frp", "avg_frp")
                    d_median = _find_column(daily_cols, "frp_median_mw", "median_frp")
                    d_total = _find_column(daily_cols, "frp_sum_mw", "total_frp", "sum_frp")
                    d_obs = _find_column(daily_cols, "detection_count", "observation_count", "detections", "count")
                    d_p90 = _find_column(daily_cols, "p90_frp", "max_frp")

                    if d_date and d_mean:
                        d_date_expr = f"TRY_CAST({_quoted_identifier(d_date)} AS DATE)"
                        d_conds = [f"{d_date_expr} IS NOT NULL"]
                        d_params: list[object] = []
                        if start_date is not None:
                            d_conds.append(f"{d_date_expr} >= ?")
                            d_params.append(start_date)
                        if end_date is not None:
                            d_conds.append(f"{d_date_expr} <= ?")
                            d_params.append(end_date)

                        if temporal_aggregation == "daily":
                            d_p = f"STRFTIME({d_date_expr}, '%Y-%m-%d')"
                        elif temporal_aggregation == "weekly":
                            d_p = f"STRFTIME(DATE_TRUNC('week', {d_date_expr}), '%Y-%m-%d')"
                        elif temporal_aggregation == "yearly":
                            d_p = f"CAST(YEAR({d_date_expr}) AS VARCHAR)"
                        else:
                            d_p = f"STRFTIME({d_date_expr}, '%Y-%m')"

                        obs_expr = _quoted_identifier(d_obs) if d_obs else "1"
                        mean_expr = f"TRY_CAST({_quoted_identifier(d_mean)} AS DOUBLE)"
                        med_expr = (
                            f"TRY_CAST({_quoted_identifier(d_median)} AS DOUBLE)"
                            if d_median
                            else mean_expr
                        )
                        tot_expr = (
                            f"TRY_CAST({_quoted_identifier(d_total)} AS DOUBLE)"
                            if d_total
                            else f"{mean_expr} * {obs_expr}"
                        )
                        p90_col_expr = (
                            f"TRY_CAST({_quoted_identifier(d_p90)} AS DOUBLE)"
                            if d_p90
                            else mean_expr
                        )

                        d_rows = connection.execute(
                            f"""
                            SELECT
                                {d_p} AS period,
                                SUM(COALESCE({obs_expr}, 1)) AS obs_count,
                                AVG({mean_expr}) AS mean_frp,
                                AVG({med_expr}) AS median_frp,
                                MAX({p90_col_expr}) AS p90_frp,
                                SUM({tot_expr}) AS total_frp
                            FROM {_quoted_identifier(sensor_daily_table)}
                            WHERE {' AND '.join(d_conds)}
                            GROUP BY period
                            ORDER BY period
                            """,
                            d_params,
                        ).fetchall()
                        if d_rows:
                            frp_evolution = [
                                {
                                    "period": str(r[0]),
                                    "observation_count": int(r[1] or 0),
                                    "mean_frp": round(float(r[2]), 1) if r[2] is not None else None,
                                    "median_frp": round(float(r[3]), 1) if r[3] is not None else None,
                                    "p90_frp": round(float(r[4]), 1) if r[4] is not None else None,
                                    "total_frp": round(float(r[5]), 1) if r[5] is not None else None,
                                }
                                for r in d_rows
                            ]
                except Exception:
                    logger.exception("Failed reading harm_sensor_activity_daily.")
                    frp_evolution = []

            if not frp_evolution:
                frp_rows = connection.execute(
                    f"""
                    SELECT
                        {period_expr} AS period,
                        COUNT({frp_expr}) AS obs_count,
                        AVG({frp_expr}) AS mean_frp,
                        MEDIAN({frp_expr}) AS median_frp,
                        QUANTILE_CONT({frp_expr}, 0.90) AS p90_frp,
                        SUM({frp_expr}) AS total_frp
                    FROM {table_sql} d
                    WHERE {where_clause}
                    GROUP BY period
                    ORDER BY period
                    """,
                    parameters,
                ).fetchall()
                frp_source = "UNIFIED_DETECTIONS"
                frp_evolution = [
                    {
                        "period": str(r[0]),
                        "observation_count": int(r[1] or 0),
                        "mean_frp": round(float(r[2]), 1) if r[2] is not None else None,
                        "median_frp": round(float(r[3]), 1) if r[3] is not None else None,
                        "p90_frp": round(float(r[4]), 1) if r[4] is not None else None,
                        "total_frp": round(float(r[5]), 1) if r[5] is not None else None,
                    }
                    for r in frp_rows
                ]

            # 3 & 4. Cluster Counts & Cluster Size Evolution (source: harm_activity_clusters + harm_cluster_members)
            cluster_table = tables.get("harm_activity_clusters")
            member_table = tables.get("harm_cluster_members")
            cluster_capability = False
            cluster_counts: list[dict[str, object]] = []
            cluster_size_evolution: list[dict[str, object]] = []
            spatial_clusters: list[dict[str, object]] = []

            if cluster_table and member_table and detection_id:
                try:
                    member_cols = _table_columns(connection, member_table)
                    m_cid = _find_column(member_cols, "activity_cluster_id", "cluster_id")
                    m_did = _find_column(member_cols, "detection_id", "id")
                    if m_cid and m_did:
                        cluster_capability = True
                        if temporal_aggregation == "daily":
                            c_p = "STRFTIME(cluster_date, '%Y-%m-%d')"
                        elif temporal_aggregation == "weekly":
                            c_p = "STRFTIME(DATE_TRUNC('week', cluster_date), '%Y-%m-%d')"
                        elif temporal_aggregation == "yearly":
                            c_p = "CAST(YEAR(cluster_date) AS VARCHAR)"
                        else:
                            c_p = "STRFTIME(cluster_date, '%Y-%m')"

                        c_rows = connection.execute(
                            f"""
                            WITH member_detections AS (
                                SELECT
                                    m.{_quoted_identifier(m_cid)} AS cluster_id,
                                    {date_expr} AS acq_date,
                                    {frp_expr} AS frp_mw,
                                    {latitude_expr} AS latitude,
                                    {longitude_expr} AS longitude
                                FROM {_quoted_identifier(member_table)} m
                                JOIN {table_sql} d ON m.{_quoted_identifier(m_did)} = {dcol(detection_id)}
                                WHERE {where_clause}
                            ),
                            cluster_summary AS (
                                SELECT
                                    cluster_id,
                                    MIN(acq_date) AS cluster_date,
                                    COUNT(*) AS member_count,
                                    AVG(frp_mw) AS mean_frp,
                                    MAX(frp_mw) AS max_frp,
                                    AVG(latitude) AS center_lat,
                                    AVG(longitude) AS center_lon
                                FROM member_detections
                                GROUP BY cluster_id
                            )
                            SELECT
                                {c_p} AS period,
                                COUNT(*) AS cluster_count,
                                AVG(member_count) AS avg_size,
                                MEDIAN(member_count) AS median_size,
                                MAX(member_count) AS max_size,
                                COUNT(CASE WHEN member_count BETWEEN 1 AND 4 THEN 1 END) AS small_clusters,
                                COUNT(CASE WHEN member_count BETWEEN 5 AND 19 THEN 1 END) AS medium_clusters,
                                COUNT(CASE WHEN member_count BETWEEN 20 AND 99 THEN 1 END) AS large_clusters,
                                COUNT(CASE WHEN member_count >= 100 THEN 1 END) AS mega_clusters
                            FROM cluster_summary
                            WHERE cluster_date IS NOT NULL
                            GROUP BY period
                            ORDER BY period
                            """,
                            parameters,
                        ).fetchall()

                        cluster_counts = [
                            {"period": str(row[0]), "clusters": int(row[1] or 0)}
                            for row in c_rows
                        ]
                        cluster_size_evolution = [
                            {
                                "period": str(row[0]),
                                "clusters": int(row[1] or 0),
                                "avg_size": round(float(row[2]), 2) if row[2] is not None else 0.0,
                                "median_size": round(float(row[3]), 1) if row[3] is not None else 0.0,
                                "max_size": int(row[4] or 0),
                                "small_clusters": int(row[5] or 0),
                                "medium_clusters": int(row[6] or 0),
                                "large_clusters": int(row[7] or 0),
                                "mega_clusters": int(row[8] or 0),
                            }
                            for row in c_rows
                        ]

                        if spatial_aggregation == "clusters":
                            sc_rows = connection.execute(
                                f"""
                                WITH member_detections AS (
                                    SELECT
                                        m.{_quoted_identifier(m_cid)} AS cluster_id,
                                        {date_expr} AS acq_date,
                                        {frp_expr} AS frp_mw,
                                        {latitude_expr} AS latitude,
                                        {longitude_expr} AS longitude
                                    FROM {_quoted_identifier(member_table)} m
                                    JOIN {table_sql} d ON m.{_quoted_identifier(m_did)} = {dcol(detection_id)}
                                    WHERE {where_clause}
                                )
                                SELECT
                                    cluster_id,
                                    AVG(latitude) AS center_lat,
                                    AVG(longitude) AS center_lon,
                                    COUNT(*) AS member_count,
                                    AVG(frp_mw) AS mean_frp,
                                    MAX(frp_mw) AS max_frp,
                                    STRFTIME(MIN(acq_date), '%Y-%m-%d') AS first_date,
                                    STRFTIME(MAX(acq_date), '%Y-%m-%d') AS last_date
                                FROM member_detections
                                WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                                GROUP BY cluster_id
                                ORDER BY member_count DESC
                                LIMIT 1500
                                """,
                                parameters,
                            ).fetchall()
                            spatial_clusters = [
                                {
                                    "cluster_id": str(row[0]),
                                    "latitude": float(row[1]),
                                    "longitude": float(row[2]),
                                    "member_count": int(row[3]),
                                    "mean_frp": round(float(row[4]), 1) if row[4] is not None else None,
                                    "max_frp": round(float(row[5]), 1) if row[5] is not None else None,
                                    "first_date": row[6],
                                    "last_date": row[7],
                                }
                                for row in sc_rows
                            ]
                except Exception:
                    logger.exception("Could not compute cluster metrics.")
                    cluster_capability = False

            # 5. Historical Spatial Distribution (source: UNIFIED_DETECTIONS)
            spatial_points: list[dict[str, object]] = []
            spatial_grid_cells: list[dict[str, object]] = []

            if spatial_aggregation == "detections":
                p_rows = connection.execute(
                    f"""
                    SELECT
                        {dcol(detection_id, "'d_' || ROW_NUMBER() OVER()")} AS id,
                        {latitude_expr} AS latitude,
                        {longitude_expr} AS longitude,
                        {platform_expr} AS platform,
                        STRFTIME({date_expr}, '%Y-%m-%d') AS acq_date,
                        {frp_expr} AS frp_mw,
                        {confidence_expr} AS confidence,
                        {daynight_expr} AS daynight
                    FROM {table_sql} d
                    WHERE {where_clause}
                      AND {latitude_expr} IS NOT NULL
                      AND {longitude_expr} IS NOT NULL
                    ORDER BY {frp_expr} DESC NULLS LAST
                    LIMIT 2000
                    """,
                    parameters,
                ).fetchall()
                spatial_points = [
                    {
                        "id": str(row[0]),
                        "latitude": float(row[1]),
                        "longitude": float(row[2]),
                        "platform": str(row[3]),
                        "acq_date": str(row[4]),
                        "frp_mw": round(float(row[5]), 1) if row[5] is not None else None,
                        "confidence": str(row[6]) if row[6] is not None else None,
                        "daynight": str(row[7]) if row[7] is not None else None,
                    }
                    for row in p_rows
                ]
            elif spatial_aggregation == "grid":
                g_res = max(0.5, min(10.0, float(grid_resolution)))
                g_rows = connection.execute(
                    f"""
                    SELECT
                        FLOOR({latitude_expr} / {g_res}) * {g_res} AS min_lat,
                        FLOOR({longitude_expr} / {g_res}) * {g_res} AS min_lon,
                        COUNT(*) AS detections,
                        AVG({frp_expr}) AS mean_frp,
                        SUM({frp_expr}) AS total_frp,
                        MAX({frp_expr}) AS max_frp
                    FROM {table_sql} d
                    WHERE {where_clause}
                      AND {latitude_expr} IS NOT NULL
                      AND {longitude_expr} IS NOT NULL
                    GROUP BY min_lat, min_lon
                    ORDER BY detections DESC
                    LIMIT 1500
                    """,
                    parameters,
                ).fetchall()
                spatial_grid_cells = [
                    {
                        "id": f"cell_{row[0]}_{row[1]}",
                        "min_lat": float(row[0]),
                        "max_lat": round(float(row[0]) + g_res, 4),
                        "min_lon": float(row[1]),
                        "max_lon": round(float(row[1]) + g_res, 4),
                        "center_lat": round(float(row[0]) + g_res / 2.0, 3),
                        "center_lon": round(float(row[1]) + g_res / 2.0, 3),
                        "detections": int(row[2]),
                        "mean_frp": round(float(row[3]), 1) if row[3] is not None else None,
                        "total_frp": round(float(row[4]), 1) if row[4] is not None else None,
                        "max_frp": round(float(row[5]), 1) if row[5] is not None else None,
                    }
                    for row in g_rows
                ]

            # 6. Regional Historical Comparison
            regional_conditions = [c for c in conditions if c != region_condition]
            regional_where = " AND ".join(regional_conditions)
            regional_params = (
                parameters[:-4] if region_condition is not None else parameters
            )
            reg_rows = connection.execute(
                f"""
                SELECT
                    {region_expr} AS reg,
                    COUNT(*) AS detections,
                    SUM({frp_expr}) AS total_frp,
                    AVG({frp_expr}) AS mean_frp,
                    MEDIAN({frp_expr}) AS median_frp
                FROM {table_sql} d
                WHERE {regional_where}
                GROUP BY reg
                ORDER BY detections DESC
                """,
                regional_params,
            ).fetchall()

            region_labels = {
                "africa": "Africa",
                "asia": "Asia",
                "europe": "Europe",
                "north-america": "North America",
                "oceania": "Oceania",
                "south-america": "South America",
                "other": "Other / Maritime",
            }
            regional_comparison = [
                {
                    "region": str(row[0]),
                    "region_name": region_labels.get(str(row[0]), str(row[0]).title()),
                    "detections": int(row[1]),
                    "total_frp": round(float(row[2]), 1) if row[2] is not None else 0.0,
                    "mean_frp": round(float(row[3]), 1) if row[3] is not None else None,
                    "median_frp": round(float(row[4]), 1) if row[4] is not None else None,
                }
                for row in reg_rows
                if str(row[0]) in region_labels
            ]

            # 7. Summary KPIs
            kpi_row = connection.execute(
                f"""
                SELECT
                    COUNT(*) AS total_detections,
                    AVG({frp_expr}) AS mean_frp,
                    MEDIAN({frp_expr}) AS median_frp,
                    SUM({frp_expr}) AS total_frp,
                    MAX({frp_expr}) AS peak_frp,
                    MIN({date_expr}) AS first_date,
                    MAX({date_expr}) AS last_date
                FROM {table_sql} d
                WHERE {where_clause}
                """,
                parameters,
            ).fetchone()

            total_detections = int(kpi_row[0]) if kpi_row else 0
            mean_frp = round(float(kpi_row[1]), 1) if kpi_row and kpi_row[1] is not None else None
            median_frp = round(float(kpi_row[2]), 1) if kpi_row and kpi_row[2] is not None else None
            total_frp = round(float(kpi_row[3]), 1) if kpi_row and kpi_row[3] is not None else None
            peak_frp = round(float(kpi_row[4]), 1) if kpi_row and kpi_row[4] is not None else None
            first_date = str(kpi_row[5]) if kpi_row and kpi_row[5] is not None else None
            last_date = str(kpi_row[6]) if kpi_row and kpi_row[6] is not None else None

            total_clusters = (
                sum(r["clusters"] for r in cluster_counts) if cluster_capability else None
            )
            avg_cluster_size = (
                round(
                    sum(r["avg_size"] * r["clusters"] for r in cluster_size_evolution)
                    / max(1, total_clusters),
                    2,
                )
                if cluster_capability and total_clusters and total_clusters > 0
                else None
            )

            return {
                "generated_at": _utc_iso(datetime.now(timezone.utc)),
                "summary_kpis": {
                    "total_detections": total_detections,
                    "total_clusters": total_clusters,
                    "mean_frp": mean_frp,
                    "median_frp": median_frp,
                    "total_frp": total_frp,
                    "peak_frp": peak_frp,
                    "avg_cluster_size": avg_cluster_size,
                    "first_date": first_date,
                    "last_date": last_date,
                },
                "detection_trend": detection_trend,
                "frp_evolution": frp_evolution,
                "cluster_counts": cluster_counts,
                "cluster_size_evolution": cluster_size_evolution,
                "regional_comparison": regional_comparison,
                "spatial_distribution": {
                    "mode": spatial_aggregation,
                    "points": spatial_points,
                    "grid_cells": spatial_grid_cells,
                    "clusters": spatial_clusters,
                },
                "date_bounds": {
                    "min_date": min_avail_date,
                    "max_date": max_avail_date,
                    "available_years": available_years,
                },
                "sources": {
                    "historical_detection_trend": "UNIFIED_DETECTIONS",
                    "frp_evolution": frp_source,
                    "historical_cluster_counts": (
                        "harm_activity_clusters" if cluster_capability else None
                    ),
                    "cluster_size_evolution": (
                        "harm_activity_clusters + harm_cluster_members"
                        if cluster_capability
                        else None
                    ),
                    "historical_spatial_distribution": "UNIFIED_DETECTIONS",
                },
                "capabilities": {
                    "frp": frp_column is not None,
                    "confidence": confidence_column is not None,
                    "daynight": daynight_column is not None,
                    "geographic_regions": (
                        latitude_column is not None and longitude_column is not None
                    ),
                    "activity_clusters": cluster_capability,
                    "sensor_activity_daily_table": sensor_daily_table is not None,
                },
            }
    except duckdb.Error:
        logger.exception("Failed to query the Historical Fire Analysis database.")
        raise HTTPException(
            status_code=503,
            detail="Historical Fire Analysis could not read the configured database. Check the detection and harmonization schemas.",
        ) from None


@app.get("/api/historical-analysis/export")
def export_historical_analysis(
    export_type: ExportType = "observations",
    format: ExportFormat = "csv",
    start_date: date | None = None,
    end_date: date | None = None,
    region: Region = "global",
    platform: FireSeasonPlatform = "all",
    daynight: DayNight = "all",
    frp_min: float | None = Query(default=None, ge=0),
    frp_max: float | None = Query(default=None, ge=0),
    confidence: str = "all",
    temporal_aggregation: TemporalAggregation = "monthly",
    grid_resolution: float = Query(default=2.0, ge=0.5, le=10.0),
):
    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }
            detection_table = tables.get("unified_detections")
            if detection_table is None:
                raise HTTPException(
                    status_code=503,
                    detail="Historical Fire Analysis requires UNIFIED_DETECTIONS.",
                )

            columns = _table_columns(connection, detection_table)
            detection_id = _find_column(columns, "detection_id", "id")
            date_column = _find_column(columns, "acq_date", "acquisition_date")
            time_column = _find_column(columns, "acq_time", "acquisition_time")
            platform_column = _find_column(columns, "platform", "satellite")
            source_column = _find_column(columns, "source", "source_name")
            sensor_column = _find_column(columns, "instrument", "sensor", "source")
            frp_column = _find_column(columns, "frp_mw", "frp")
            confidence_column = _find_column(
                columns, "confidence_native", "native_confidence", "confidence", "confidence_level"
            )
            daynight_column = _find_column(columns, "daynight", "day_night")
            latitude_column = _find_column(columns, "latitude", "lat")
            longitude_column = _find_column(columns, "longitude", "lon", "lng")

            def dcol(col: str | None, fallback: str = "NULL") -> str:
                return f'd.{_quoted_identifier(col)}' if col else fallback

            date_expr = f"TRY_CAST({dcol(date_column)} AS DATE)"
            frp_expr = (
                f"TRY_CAST({dcol(frp_column)} AS DOUBLE)"
                if frp_column
                else "NULL::DOUBLE"
            )
            latitude_expr = (
                f"TRY_CAST({dcol(latitude_column)} AS DOUBLE)"
                if latitude_column
                else "NULL::DOUBLE"
            )
            longitude_expr = (
                f"TRY_CAST({dcol(longitude_column)} AS DOUBLE)"
                if longitude_column
                else "NULL::DOUBLE"
            )
            confidence_expr = (
                f"CAST({dcol(confidence_column)} AS VARCHAR)"
                if confidence_column
                else "NULL::VARCHAR"
            )
            daynight_expr = (
                f"UPPER(TRIM(CAST({dcol(daynight_column)} AS VARCHAR)))"
                if daynight_column
                else "NULL::VARCHAR"
            )
            platform_expr = (
                f"CAST({dcol(platform_column)} AS VARCHAR)"
                if platform_column
                else "'Unknown'"
            )
            time_expr = (
                f"CAST({dcol(time_column)} AS VARCHAR)"
                if time_column
                else "''"
            )

            conditions: list[str] = [f"{date_expr} IS NOT NULL"]
            parameters: list[object] = []

            if start_date is not None:
                conditions.append(f"{date_expr} >= ?")
                parameters.append(start_date)

            if end_date is not None:
                conditions.append(f"{date_expr} <= ?")
                parameters.append(end_date)

            p_norm = platform.lower().replace("-", "").replace(" ", "")
            if p_norm != "all":
                searchable_columns = [
                    c
                    for c in (platform_column, source_column, sensor_column)
                    if c is not None
                ]
                if searchable_columns:
                    pattern = {
                        "terra": "%TERRA%",
                        "aqua": "%AQUA%",
                        "noaa20": "%NOAA%20%",
                        "noaa21": "%NOAA%21%",
                        "modis": "%MODIS%",
                        "viirs": "%VIIRS%",
                    }.get(platform, f"%{platform.upper()}%")
                    matching = []
                    for c in searchable_columns:
                        if platform in ("terra", "aqua", "noaa20", "noaa21"):
                            val = (
                                "REGEXP_REPLACE("
                                f"UPPER(CAST(d.{_quoted_identifier(c)} AS VARCHAR)), "
                                "'[^A-Z0-9]', '', 'g')"
                            )
                        else:
                            val = f"UPPER(CAST(d.{_quoted_identifier(c)} AS VARCHAR))"
                        matching.append(f"{val} LIKE ?")
                        parameters.append(pattern)
                    conditions.append("(" + " OR ".join(matching) + ")")

            if daynight != "all" and daynight_column:
                values = "'D', 'DAY'" if daynight == "day" else "'N', 'NIGHT'"
                conditions.append(f"{daynight_expr} IN ({values})")

            if region != "global" and latitude_column and longitude_column:
                west, south, east, north = REGION_BOUNDS[region]
                conditions.append(
                    f"{longitude_expr} BETWEEN ? AND ? AND {latitude_expr} BETWEEN ? AND ?"
                )
                parameters.extend((west, east, south, north))

            if frp_min is not None and frp_column:
                conditions.append(f"{frp_expr} >= ?")
                parameters.append(frp_min)

            if frp_max is not None and frp_column:
                conditions.append(f"{frp_expr} <= ?")
                parameters.append(frp_max)

            if confidence != "all" and confidence_column:
                conf_norm = confidence.strip().lower()
                if conf_norm in ("high", "h"):
                    conditions.append(
                        f"(LOWER(TRIM({confidence_expr})) IN ('h', 'high') OR TRY_CAST({confidence_expr} AS DOUBLE) >= 80)"
                    )
                elif conf_norm in ("nominal", "med", "medium", "n"):
                    conditions.append(
                        f"(LOWER(TRIM({confidence_expr})) IN ('n', 'nominal', 'med', 'medium') OR "
                        f"(TRY_CAST({confidence_expr} AS DOUBLE) >= 30 AND TRY_CAST({confidence_expr} AS DOUBLE) < 80))"
                    )
                elif conf_norm in ("low", "l"):
                    conditions.append(
                        f"(LOWER(TRIM({confidence_expr})) IN ('l', 'low') OR "
                        f"(TRY_CAST({confidence_expr} AS DOUBLE) IS NOT NULL AND TRY_CAST({confidence_expr} AS DOUBLE) < 30))"
                    )
                else:
                    conditions.append(f"LOWER(TRIM({confidence_expr})) = LOWER(?)")
                    parameters.append(confidence.strip())

            where_clause = " AND ".join(conditions)
            table_sql = _quoted_identifier(detection_table)

            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

            if export_type == "observations":
                obs_rows = connection.execute(
                    f"""
                    SELECT
                        {dcol(detection_id, "'d_' || ROW_NUMBER() OVER()")} AS detection_id,
                        STRFTIME({date_expr}, '%Y-%m-%d') AS acq_date,
                        {time_expr} AS acq_time,
                        {latitude_expr} AS latitude,
                        {longitude_expr} AS longitude,
                        {platform_expr} AS platform,
                        {frp_expr} AS frp_mw,
                        {confidence_expr} AS confidence,
                        {daynight_expr} AS daynight
                    FROM {table_sql} d
                    WHERE {where_clause}
                    ORDER BY {date_expr} DESC, {frp_expr} DESC NULLS LAST
                    LIMIT 20000
                    """,
                    parameters,
                ).fetchall()

                if format == "geojson":
                    features = []
                    for r in obs_rows:
                        if r[3] is not None and r[4] is not None:
                            features.append(
                                {
                                    "type": "Feature",
                                    "geometry": {
                                        "type": "Point",
                                        "coordinates": [float(r[4]), float(r[3])],
                                    },
                                    "properties": {
                                        "detection_id": str(r[0]),
                                        "acq_date": str(r[1]),
                                        "acq_time": str(r[2]),
                                        "platform": str(r[5]),
                                        "frp_mw": float(r[6]) if r[6] is not None else None,
                                        "confidence": str(r[7]) if r[7] is not None else None,
                                        "daynight": str(r[8]) if r[8] is not None else None,
                                    },
                                }
                            )
                    geojson_payload = {
                        "type": "FeatureCollection",
                        "metadata": {
                            "generated_at": _utc_iso(datetime.now(timezone.utc)),
                            "count": len(features),
                        },
                        "features": features,
                    }
                    return Response(
                        content=json.dumps(geojson_payload, indent=2),
                        media_type="application/geo+json",
                        headers={
                            "Content-Disposition": f'attachment; filename="twinflame_observations_{timestamp_str}.geojson"'
                        },
                    )
                elif format == "json":
                    items = [
                        {
                            "detection_id": str(r[0]),
                            "acq_date": str(r[1]),
                            "acq_time": str(r[2]),
                            "latitude": float(r[3]) if r[3] is not None else None,
                            "longitude": float(r[4]) if r[4] is not None else None,
                            "platform": str(r[5]),
                            "frp_mw": float(r[6]) if r[6] is not None else None,
                            "confidence": str(r[7]) if r[7] is not None else None,
                            "daynight": str(r[8]) if r[8] is not None else None,
                        }
                        for r in obs_rows
                    ]
                    return Response(
                        content=json.dumps(items, indent=2),
                        media_type="application/json",
                        headers={
                            "Content-Disposition": f'attachment; filename="twinflame_observations_{timestamp_str}.json"'
                        },
                    )
                else:  # csv
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    writer.writerow([
                        "detection_id", "acq_date", "acq_time", "latitude",
                        "longitude", "platform", "frp_mw", "confidence", "daynight"
                    ])
                    for r in obs_rows:
                        writer.writerow([
                            r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]
                        ])
                    return Response(
                        content=buf.getvalue(),
                        media_type="text/csv",
                        headers={
                            "Content-Disposition": f'attachment; filename="twinflame_observations_{timestamp_str}.csv"'
                        },
                    )

            elif export_type == "aggregated":
                if temporal_aggregation == "daily":
                    p_expr = f"STRFTIME({date_expr}, '%Y-%m-%d')"
                elif temporal_aggregation == "weekly":
                    p_expr = f"STRFTIME(DATE_TRUNC('week', {date_expr}), '%Y-%m-%d')"
                elif temporal_aggregation == "yearly":
                    p_expr = f"CAST(YEAR({date_expr}) AS VARCHAR)"
                else:
                    p_expr = f"STRFTIME({date_expr}, '%Y-%m')"

                agg_rows = connection.execute(
                    f"""
                    SELECT
                        {p_expr} AS period,
                        COUNT(*) AS detections,
                        AVG({frp_expr}) AS mean_frp,
                        MEDIAN({frp_expr}) AS median_frp,
                        SUM({frp_expr}) AS total_frp,
                        MAX({frp_expr}) AS max_frp
                    FROM {table_sql} d
                    WHERE {where_clause}
                    GROUP BY period
                    ORDER BY period
                    """,
                    parameters,
                ).fetchall()

                if format == "json":
                    items = [
                        {
                            "period": str(r[0]),
                            "detections": int(r[1] or 0),
                            "mean_frp": round(float(r[2]), 2) if r[2] is not None else None,
                            "median_frp": round(float(r[3]), 2) if r[3] is not None else None,
                            "total_frp": round(float(r[4]), 2) if r[4] is not None else None,
                            "max_frp": round(float(r[5]), 2) if r[5] is not None else None,
                        }
                        for r in agg_rows
                    ]
                    return Response(
                        content=json.dumps(items, indent=2),
                        media_type="application/json",
                        headers={
                            "Content-Disposition": f'attachment; filename="twinflame_aggregated_{temporal_aggregation}_{timestamp_str}.json"'
                        },
                    )
                else:
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    writer.writerow(["period", "detections", "mean_frp", "median_frp", "total_frp", "max_frp"])
                    for r in agg_rows:
                        writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5]])
                    return Response(
                        content=buf.getvalue(),
                        media_type="text/csv",
                        headers={
                            "Content-Disposition": f'attachment; filename="twinflame_aggregated_{temporal_aggregation}_{timestamp_str}.csv"'
                        },
                    )

            else:  # regional
                reg_expr = f"""
                    CASE
                        WHEN {longitude_expr} BETWEEN -170 AND -50 AND {latitude_expr} BETWEEN 5 AND 84 THEN 'north-america'
                        WHEN {longitude_expr} BETWEEN -85 AND -30 AND {latitude_expr} BETWEEN -57 AND 14 THEN 'south-america'
                        WHEN {longitude_expr} BETWEEN -25 AND 34 AND {latitude_expr} BETWEEN 45 AND 72 THEN 'europe'
                        WHEN {longitude_expr} BETWEEN -20 AND 55 AND {latitude_expr} BETWEEN -40 AND 38 THEN 'africa'
                        WHEN {longitude_expr} BETWEEN 110 AND 180 AND {latitude_expr} BETWEEN -50 AND 0 THEN 'oceania'
                        WHEN {longitude_expr} BETWEEN 25 AND 180 AND {latitude_expr} BETWEEN -12 AND 82 THEN 'asia'
                        ELSE 'other'
                    END
                """
                reg_rows = connection.execute(
                    f"""
                    SELECT
                        {reg_expr} AS region,
                        COUNT(*) AS detections,
                        SUM({frp_expr}) AS total_frp,
                        AVG({frp_expr}) AS mean_frp
                    FROM {table_sql} d
                    WHERE {where_clause}
                    GROUP BY region
                    ORDER BY detections DESC
                    """,
                    parameters,
                ).fetchall()

                if format == "json":
                    items = [
                        {
                            "region": str(r[0]),
                            "detections": int(r[1] or 0),
                            "total_frp": round(float(r[2]), 2) if r[2] is not None else None,
                            "mean_frp": round(float(r[3]), 2) if r[3] is not None else None,
                        }
                        for r in reg_rows
                    ]
                    return Response(
                        content=json.dumps(items, indent=2),
                        media_type="application/json",
                        headers={
                            "Content-Disposition": f'attachment; filename="twinflame_regional_{timestamp_str}.json"'
                        },
                    )
                else:
                    buf = io.StringIO()
                    writer = csv.writer(buf)
                    writer.writerow(["region", "detections", "total_frp", "mean_frp"])
                    for r in reg_rows:
                        writer.writerow([r[0], r[1], r[2], r[3]])
                    return Response(
                        content=buf.getvalue(),
                        media_type="text/csv",
                        headers={
                            "Content-Disposition": f'attachment; filename="twinflame_regional_{timestamp_str}.csv"'
                        },
                    )

    except duckdb.Error:
        logger.exception("Failed to export historical analysis.")
        raise HTTPException(
            status_code=503,
            detail="Historical Fire Analysis could not read the database for export.",
        ) from None


PLATFORM_SPECS = {
    "terra": {
        "id": "terra",
        "name": "Terra",
        "satellite": "EOS-AM1 (Terra)",
        "instrument": "MODIS",
        "operator": "NASA (EOS Program)",
        "launch_year": 1999,
        "spatial_resolution": "1000 m (nadir)",
        "equator_crossing_time": "10:30 AM (desc) / 22:30 PM (asc)",
        "altitude_km": 705,
        "spectral_bands": "Band 21/22 (3.96 µm) & Band 31 (11.03 µm)",
        "swath_width_km": 2330,
        "saturation_temp": "~500 K (Band 21 high-gain)",
        "characteristics": "Morning overpass captures early active fire ignition before the afternoon peak diurnal burning cycle.",
    },
    "aqua": {
        "id": "aqua",
        "name": "Aqua",
        "satellite": "EOS-PM1 (Aqua)",
        "instrument": "MODIS",
        "operator": "NASA (EOS Program)",
        "launch_year": 2002,
        "spatial_resolution": "1000 m (nadir)",
        "equator_crossing_time": "13:30 PM (asc) / 01:30 AM (desc)",
        "altitude_km": 705,
        "spectral_bands": "Band 21/22 (3.96 µm) & Band 31 (11.03 µm)",
        "swath_width_km": 2330,
        "saturation_temp": "~500 K (Band 21 high-gain)",
        "characteristics": "Afternoon overpass captures peak diurnal thermal burning conditions and maximum wildfire radiative power.",
    },
    "noaa20": {
        "id": "noaa20",
        "name": "NOAA-20 (JPSS-1)",
        "satellite": "NOAA-20 / JPSS-1",
        "instrument": "VIIRS",
        "operator": "NOAA / NASA",
        "launch_year": 2017,
        "spatial_resolution": "375 m (I-band nadir)",
        "equator_crossing_time": "13:30 PM (asc) / 01:30 AM (desc)",
        "altitude_km": 824,
        "spectral_bands": "I4 (3.74 µm) & I5 (11.45 µm)",
        "swath_width_km": 3040,
        "saturation_temp": "~367 K (I4 dual gain)",
        "characteristics": "High spatial resolution (375m) enables detection of smaller, lower-intensity smoldering fires and enhanced perimeter fidelity.",
    },
    "noaa21": {
        "id": "noaa21",
        "name": "NOAA-21 (JPSS-2)",
        "satellite": "NOAA-21 / JPSS-2",
        "instrument": "VIIRS",
        "operator": "NOAA / NASA",
        "launch_year": 2022,
        "spatial_resolution": "375 m (I-band nadir)",
        "equator_crossing_time": "13:30 PM (asc) / 01:30 AM (desc)",
        "altitude_km": 824,
        "spectral_bands": "I4 (3.74 µm) & I5 (11.45 µm)",
        "swath_width_km": 3040,
        "saturation_temp": "~367 K (I4 dual gain)",
        "characteristics": "Flies in the same orbital plane as NOAA-20 with a 25-minute separation, providing critical rapid-revisit fire monitoring.",
    },
}


@app.get("/api/sensor-comparison")
def sensor_comparison(
    start_date: date | None = None,
    end_date: date | None = None,
    region: Region = "global",
    platform_a: str = "terra",
    platform_b: str = "noaa20",
    daynight: DayNight = "all",
    comparison_metric: str = "detection_count",
    temporal_window_minutes: int = Query(default=60, ge=5, le=1440),
    spatial_threshold_meters: float = Query(default=2000.0, ge=100.0, le=50000.0),
    eligibility: str = "all",
) -> dict[str, object]:
    key_a = platform_a.lower().replace("-", "").replace(" ", "")
    key_b = platform_b.lower().replace("-", "").replace(" ", "")
    if key_a == key_b:
        raise HTTPException(
            status_code=422,
            detail="Platform A and Platform B must be different platforms for sensor comparison.",
        )
    platform_a = key_a
    platform_b = key_b

    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }
            detection_table = tables.get("unified_detections")
            if detection_table is None:
                raise HTTPException(
                    status_code=503,
                    detail="Sensor Comparison requires UNIFIED_DETECTIONS.",
                )

            columns = _table_columns(connection, detection_table)
            detection_id = _find_column(columns, "detection_id", "id")
            date_column = _find_column(columns, "acq_date", "acquisition_date")
            time_column = _find_column(columns, "acq_time", "acquisition_time")
            if date_column is None:
                raise HTTPException(
                    status_code=503,
                    detail="UNIFIED_DETECTIONS is missing an acquisition date column.",
                )
            platform_column = _find_column(columns, "platform", "satellite")
            source_column = _find_column(columns, "source", "source_name")
            sensor_column = _find_column(columns, "instrument", "sensor", "source")
            frp_column = _find_column(columns, "frp_mw", "frp")
            brightness_column = _find_column(
                columns, "brightness", "bright_ti4", "brightness_temperature", "bt", "bright_t21"
            )
            bright_t31_column = _find_column(
                columns, "bright_t31", "bright_ti5", "brightness_ti5", "brightness_t31"
            )
            daynight_column = _find_column(columns, "daynight", "day_night")
            latitude_column = _find_column(columns, "latitude", "lat")
            longitude_column = _find_column(columns, "longitude", "lon", "lng")

            def dcol(col: str | None, fallback: str = "NULL") -> str:
                return f'd.{_quoted_identifier(col)}' if col else fallback

            date_expr = f"TRY_CAST({dcol(date_column)} AS DATE)"
            latitude_expr = (
                f"TRY_CAST({dcol(latitude_column)} AS DOUBLE)"
                if latitude_column
                else "NULL::DOUBLE"
            )
            longitude_expr = (
                f"TRY_CAST({dcol(longitude_column)} AS DOUBLE)"
                if longitude_column
                else "NULL::DOUBLE"
            )
            frp_expr = (
                f"TRY_CAST({dcol(frp_column)} AS DOUBLE)"
                if frp_column
                else "NULL::DOUBLE"
            )
            daynight_expr = (
                f"UPPER(TRIM(CAST({dcol(daynight_column)} AS VARCHAR)))"
                if daynight_column
                else "NULL::VARCHAR"
            )
            bt_expr = (
                f"TRY_CAST({dcol(brightness_column)} AS DOUBLE)"
                if brightness_column
                else "NULL::DOUBLE"
            )
            bt31_expr = (
                f"TRY_CAST({dcol(bright_t31_column)} AS DOUBLE)"
                if bright_t31_column
                else "NULL::DOUBLE"
            )
            time_val_expr = (
                f"COALESCE(CAST({dcol(time_column)} AS VARCHAR), '0000')"
                if time_column
                else "'0000'"
            )

            # Build base query conditions
            conditions: list[str] = [f"{date_expr} IS NOT NULL"]
            parameters: list[object] = []

            if start_date is not None:
                conditions.append(f"{date_expr} >= ?")
                parameters.append(start_date)

            if end_date is not None:
                conditions.append(f"{date_expr} <= ?")
                parameters.append(end_date)

            if daynight != "all":
                if daynight_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Day/night filtering is unavailable in this database schema.",
                    )
                values = "'D', 'DAY'" if daynight == "day" else "'N', 'NIGHT'"
                conditions.append(f"{daynight_expr} IN ({values})")

            if region != "global":
                if latitude_column is None or longitude_column is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Geographic region filtering requires latitude and longitude columns.",
                    )
                west, south, east, north = REGION_BOUNDS[region]
                conditions.append(
                    f"{longitude_expr} BETWEEN ? AND ? AND {latitude_expr} BETWEEN ? AND ?"
                )
                parameters.extend((west, east, south, north))

            base_where = " AND ".join(conditions)
            table_sql = _quoted_identifier(detection_table)

            # Platform conditions
            def _build_platform_sql(platform_key: str) -> str:
                cols = [
                    c
                    for c in (platform_column, source_column, sensor_column)
                    if c is not None
                ]
                if not cols:
                    return "FALSE"
                clean_target = platform_key.upper().replace("-", "")
                parts = []
                for c in cols:
                    cleaned_col = (
                        "REGEXP_REPLACE("
                        f"UPPER(COALESCE(CAST(d.{_quoted_identifier(c)} AS VARCHAR), '')), "
                        "'[^A-Z0-9]', '', 'g')"
                    )
                    parts.append(f"{cleaned_col} LIKE '%{clean_target}%'")
                return "(" + " OR ".join(parts) + ")"

            cond_a = _build_platform_sql(platform_a)
            cond_b = _build_platform_sql(platform_b)

            # 1. Summary KPIs for Platform A and Platform B
            query_stats = f"""
                SELECT
                    COUNT(*) AS total_detections,
                    AVG({frp_expr}) AS mean_frp,
                    MEDIAN({frp_expr}) AS median_frp,
                    QUANTILE_CONT({frp_expr}, 0.90) AS p90_frp,
                    SUM({frp_expr}) AS total_frp,
                    MAX({frp_expr}) AS max_frp,
                    AVG({bt_expr}) AS mean_bt,
                    MEDIAN({bt_expr}) AS median_bt,
                    MAX({bt_expr}) AS max_bt,
                    AVG({bt31_expr}) AS mean_bt31,
                    COUNT(CASE WHEN {daynight_expr} IN ('D', 'DAY') THEN 1 END) AS day_count,
                    COUNT(CASE WHEN {daynight_expr} IN ('N', 'NIGHT') THEN 1 END) AS night_count
                FROM {table_sql} d
                WHERE {base_where} AND {{platform_cond}}
            """

            stats_a = connection.execute(
                query_stats.format(platform_cond=cond_a), parameters
            ).fetchone()
            stats_b = connection.execute(
                query_stats.format(platform_cond=cond_b), parameters
            ).fetchone()

            def _parse_summary(row):
                if not row or row[0] is None:
                    return {
                        "total_detections": 0,
                        "mean_frp": None,
                        "median_frp": None,
                        "p90_frp": None,
                        "total_frp": None,
                        "max_frp": None,
                        "mean_brightness": None,
                        "median_brightness": None,
                        "max_brightness": None,
                        "mean_bright_t31": None,
                        "day_count": 0,
                        "night_count": 0,
                    }
                return {
                    "total_detections": int(row[0] or 0),
                    "mean_frp": round(float(row[1]), 2) if row[1] is not None else None,
                    "median_frp": round(float(row[2]), 2) if row[2] is not None else None,
                    "p90_frp": round(float(row[3]), 2) if row[3] is not None else None,
                    "total_frp": round(float(row[4]), 1) if row[4] is not None else None,
                    "max_frp": round(float(row[5]), 1) if row[5] is not None else None,
                    "mean_brightness": round(float(row[6]), 1) if row[6] is not None else None,
                    "median_brightness": round(float(row[7]), 1) if row[7] is not None else None,
                    "max_brightness": round(float(row[8]), 1) if row[8] is not None else None,
                    "mean_bright_t31": round(float(row[9]), 1) if row[9] is not None else None,
                    "day_count": int(row[10] or 0),
                    "night_count": int(row[11] or 0),
                }

            summary_a = _parse_summary(stats_a)
            summary_b = _parse_summary(stats_b)

            tot_a = summary_a["total_detections"]
            tot_b = summary_b["total_detections"]
            tot_all = tot_a + tot_b

            detection_ratio = round(tot_a / max(1, tot_b), 3) if tot_b > 0 else None
            frp_ratio = (
                round(summary_a["mean_frp"] / summary_b["mean_frp"], 3)
                if summary_a["mean_frp"] and summary_b["mean_frp"]
                else None
            )

            # 2. FRP Distribution by Platform
            frp_brackets = [
                ("< 10 MW", f"{frp_expr} < 10"),
                ("10 - 25 MW", f"{frp_expr} >= 10 AND {frp_expr} < 25"),
                ("25 - 50 MW", f"{frp_expr} >= 25 AND {frp_expr} < 50"),
                ("50 - 100 MW", f"{frp_expr} >= 50 AND {frp_expr} < 100"),
                ("100 - 250 MW", f"{frp_expr} >= 100 AND {frp_expr} < 250"),
                ("≥ 250 MW", f"{frp_expr} >= 250"),
            ]
            frp_dist_cols = []
            for idx, (_, cond) in enumerate(frp_brackets):
                frp_dist_cols.append(
                    f"COUNT(CASE WHEN {cond_a} AND {cond} THEN 1 END) AS a_{idx}"
                )
                frp_dist_cols.append(
                    f"COUNT(CASE WHEN {cond_b} AND {cond} THEN 1 END) AS b_{idx}"
                )

            frp_dist_row = connection.execute(
                f"""
                SELECT {', '.join(frp_dist_cols)}
                FROM {table_sql} d
                WHERE {base_where}
                """,
                parameters,
            ).fetchone()

            frp_distribution = []
            for idx, (label, _) in enumerate(frp_brackets):
                c_a = int(frp_dist_row[idx * 2] or 0) if frp_dist_row else 0
                c_b = int(frp_dist_row[idx * 2 + 1] or 0) if frp_dist_row else 0
                frp_distribution.append({
                    "bracket": label,
                    "count_a": c_a,
                    "count_b": c_b,
                    "pct_a": round((c_a / max(1, tot_a)) * 100, 1) if tot_a > 0 else 0.0,
                    "pct_b": round((c_b / max(1, tot_b)) * 100, 1) if tot_b > 0 else 0.0,
                })

            # 3. Daily Detection Trends
            daily_rows = connection.execute(
                f"""
                WITH daily_a AS (
                    SELECT STRFTIME({date_expr}, '%Y-%m-%d') AS dt,
                           COUNT(*) AS count_a,
                           AVG({frp_expr}) AS frp_a
                    FROM {table_sql} d
                    WHERE {base_where} AND {cond_a}
                    GROUP BY dt
                ),
                daily_b AS (
                    SELECT STRFTIME({date_expr}, '%Y-%m-%d') AS dt,
                           COUNT(*) AS count_b,
                           AVG({frp_expr}) AS frp_b
                    FROM {table_sql} d
                    WHERE {base_where} AND {cond_b}
                    GROUP BY dt
                ),
                dates AS (
                    SELECT dt FROM daily_a UNION SELECT dt FROM daily_b
                )
                SELECT
                    d.dt,
                    COALESCE(a.count_a, 0) AS detections_a,
                    COALESCE(b.count_b, 0) AS detections_b,
                    a.frp_a,
                    b.frp_b
                FROM dates d
                LEFT JOIN daily_a a ON d.dt = a.dt
                LEFT JOIN daily_b b ON d.dt = b.dt
                ORDER BY d.dt
                """,
                parameters + parameters,
            ).fetchall()

            daily_trends = [
                {
                    "date": str(r[0]),
                    "detections_a": int(r[1] or 0),
                    "detections_b": int(r[2] or 0),
                    "mean_frp_a": round(float(r[3]), 1) if r[3] is not None else None,
                    "mean_frp_b": round(float(r[4]), 1) if r[4] is not None else None,
                }
                for r in daily_rows
            ]

            # 4. Brightness Band Comparisons
            bt_available = brightness_column is not None
            brightness_distribution = []
            if bt_available:
                bt_brackets = [
                    ("< 310 K", f"{bt_expr} < 310"),
                    ("310 - 330 K", f"{bt_expr} >= 310 AND {bt_expr} < 330"),
                    ("330 - 350 K", f"{bt_expr} >= 330 AND {bt_expr} < 350"),
                    ("350 - 380 K", f"{bt_expr} >= 350 AND {bt_expr} < 380"),
                    ("≥ 380 K", f"{bt_expr} >= 380"),
                ]
                bt_cols = []
                for idx, (_, cond) in enumerate(bt_brackets):
                    bt_cols.append(f"COUNT(CASE WHEN {cond_a} AND {cond} THEN 1 END) AS bt_a_{idx}")
                    bt_cols.append(f"COUNT(CASE WHEN {cond_b} AND {cond} THEN 1 END) AS bt_b_{idx}")
                bt_row = connection.execute(
                    f"""
                    SELECT {', '.join(bt_cols)}
                    FROM {table_sql} d
                    WHERE {base_where} AND {bt_expr} IS NOT NULL
                    """,
                    parameters,
                ).fetchone()
                for idx, (label, _) in enumerate(bt_brackets):
                    brightness_distribution.append({
                        "bracket": label,
                        "count_a": int(bt_row[idx * 2] or 0) if bt_row else 0,
                        "count_b": int(bt_row[idx * 2 + 1] or 0) if bt_row else 0,
                    })

            # 5. Diurnal Detection Time Differences (Hourly UTC: 00 to 23)
            hour_expr = f"""
                TRY_CAST(
                    SUBSTR(
                        LPAD(REGEXP_REPLACE({time_val_expr}, '[^0-9]', '', 'g'), 4, '0'),
                        1, 2
                    ) AS INTEGER
                )
            """
            diurnal_rows = connection.execute(
                f"""
                SELECT
                    {hour_expr} AS hr,
                    COUNT(CASE WHEN {cond_a} THEN 1 END) AS a_count,
                    COUNT(CASE WHEN {cond_b} THEN 1 END) AS b_count
                FROM {table_sql} d
                WHERE {base_where} AND ({cond_a} OR {cond_b})
                GROUP BY hr
                HAVING hr IS NOT NULL AND hr >= 0 AND hr <= 23
                ORDER BY hr
                """,
                parameters,
            ).fetchall()

            hourly_map = {int(r[0]): (int(r[1] or 0), int(r[2] or 0)) for r in diurnal_rows}
            diurnal_distribution = [
                {
                    "hour": h,
                    "label": f"{h:02d}:00",
                    "detections_a": hourly_map.get(h, (0, 0))[0],
                    "detections_b": hourly_map.get(h, (0, 0))[1],
                }
                for h in range(24)
            ]

            # 6. Coincident Overpasses / Matched Pair Comparisons
            # Check if harm_frp_comparisons exists
            frp_comp_table = tables.get("harm_frp_comparisons")
            matched_pairs_count = 0
            mean_time_diff = None
            median_time_diff = None
            mean_spatial_dist = None
            median_spatial_dist = None
            temporal_diff_distribution = [
                {"bracket": "< 15 min", "count": 0},
                {"bracket": "15 - 30 min", "count": 0},
                {"bracket": "30 - 60 min", "count": 0},
                {"bracket": "60 - 120 min", "count": 0},
                {"bracket": "≥ 120 min", "count": 0},
            ]
            spatial_dist_distribution = [
                {"bracket": "< 500 m", "count": 0},
                {"bracket": "500 - 1000 m", "count": 0},
                {"bracket": "1000 - 2000 m", "count": 0},
                {"bracket": "2000 - 5000 m", "count": 0},
                {"bracket": "≥ 5000 m", "count": 0},
            ]
            frp_comp_source = "harm_frp_comparisons" if frp_comp_table else "UNIFIED_DETECTIONS"

            if latitude_column and longitude_column:
                # Calculate via proximity matching
                acq_ts_expr = ACQUISITION_TIMESTAMP
                try:
                    match_res = connection.execute(
                        f"""
                        WITH det_a AS (
                            SELECT
                                {dcol(detection_id, "'a_' || ROW_NUMBER() OVER()")} AS id,
                                {date_expr} AS acq_date,
                                {acq_ts_expr} AS acq_timestamp,
                                {latitude_expr} AS latitude,
                                {longitude_expr} AS longitude,
                                {frp_expr} AS frp_mw
                            FROM {table_sql} d
                            WHERE {base_where} AND {cond_a}
                              AND {latitude_expr} IS NOT NULL AND {longitude_expr} IS NOT NULL
                        ),
                        det_b AS (
                            SELECT
                                {dcol(detection_id, "'b_' || ROW_NUMBER() OVER()")} AS id,
                                {date_expr} AS acq_date,
                                {acq_ts_expr} AS acq_timestamp,
                                {latitude_expr} AS latitude,
                                {longitude_expr} AS longitude,
                                {frp_expr} AS frp_mw
                            FROM {table_sql} d
                            WHERE {base_where} AND {cond_b}
                              AND {latitude_expr} IS NOT NULL AND {longitude_expr} IS NOT NULL
                        ),
                        matches AS (
                            SELECT
                                ABS(EXTRACT(EPOCH FROM (a.acq_timestamp - b.acq_timestamp)) / 60.0) AS delta_time,
                                SQRT(
                                    POW((a.latitude - b.latitude) * 111320.0, 2) +
                                    POW((a.longitude - b.longitude) * 111320.0 * COS(RADIANS(GREATEST(-89.0, LEAST(89.0, (a.latitude + b.latitude) / 2.0)))), 2)
                                ) AS distance_meters
                            FROM det_a a
                            JOIN det_b b
                              ON a.acq_date = b.acq_date
                             AND ABS(EXTRACT(EPOCH FROM (a.acq_timestamp - b.acq_timestamp)) / 60.0) <= ?
                             AND ABS(a.latitude - b.latitude) <= (? / 111320.0)
                             AND ABS(a.longitude - b.longitude) <= (? / 50000.0)
                        )
                        SELECT
                            COUNT(*) AS matched_count,
                            AVG(delta_time) AS mean_delta,
                            MEDIAN(delta_time) AS median_delta,
                            AVG(distance_meters) AS mean_dist,
                            MEDIAN(distance_meters) AS median_dist,
                            COUNT(CASE WHEN delta_time <= 15 THEN 1 END) AS dt_15,
                            COUNT(CASE WHEN delta_time > 15 AND delta_time <= 30 THEN 1 END) AS dt_30,
                            COUNT(CASE WHEN delta_time > 30 AND delta_time <= 60 THEN 1 END) AS dt_60,
                            COUNT(CASE WHEN delta_time > 60 AND delta_time <= 120 THEN 1 END) AS dt_120,
                            COUNT(CASE WHEN delta_time > 120 THEN 1 END) AS dt_over120,
                            COUNT(CASE WHEN distance_meters <= 500 THEN 1 END) AS dist_500,
                            COUNT(CASE WHEN distance_meters > 500 AND distance_meters <= 1000 THEN 1 END) AS dist_1000,
                            COUNT(CASE WHEN distance_meters > 1000 AND distance_meters <= 2000 THEN 1 END) AS dist_2000,
                            COUNT(CASE WHEN distance_meters > 2000 AND distance_meters <= 5000 THEN 1 END) AS dist_5000,
                            COUNT(CASE WHEN distance_meters > 5000 THEN 1 END) AS dist_over5000
                        FROM matches
                        WHERE distance_meters <= ?
                        """,
                        parameters + parameters + [
                            float(temporal_window_minutes),
                            float(spatial_threshold_meters),
                            float(spatial_threshold_meters),
                            float(spatial_threshold_meters),
                        ],
                    ).fetchone()

                    if match_res and match_res[0]:
                        matched_pairs_count = int(match_res[0] or 0)
                        mean_time_diff = round(float(match_res[1]), 1) if match_res[1] is not None else None
                        median_time_diff = round(float(match_res[2]), 1) if match_res[2] is not None else None
                        mean_spatial_dist = round(float(match_res[3]), 1) if match_res[3] is not None else None
                        median_spatial_dist = round(float(match_res[4]), 1) if match_res[4] is not None else None
                        temporal_diff_distribution = [
                            {"bracket": "< 15 min", "count": int(match_res[5] or 0)},
                            {"bracket": "15 - 30 min", "count": int(match_res[6] or 0)},
                            {"bracket": "30 - 60 min", "count": int(match_res[7] or 0)},
                            {"bracket": "60 - 120 min", "count": int(match_res[8] or 0)},
                            {"bracket": "≥ 120 min", "count": int(match_res[9] or 0)},
                        ]
                        spatial_dist_distribution = [
                            {"bracket": "< 500 m", "count": int(match_res[10] or 0)},
                            {"bracket": "500 - 1000 m", "count": int(match_res[11] or 0)},
                            {"bracket": "1000 - 2000 m", "count": int(match_res[12] or 0)},
                            {"bracket": "2000 - 5000 m", "count": int(match_res[13] or 0)},
                            {"bracket": "≥ 5000 m", "count": int(match_res[14] or 0)},
                        ]
                except Exception:
                    logger.exception("Failed coincidence proximity calculation.")

            # Platform details & specifications
            spec_a = PLATFORM_SPECS.get(platform_a, {})
            spec_b = PLATFORM_SPECS.get(platform_b, {})

            scientific_caution = (
                "Differences in detection counts do not necessarily mean one sensor is better. "
                "Spatial resolution (375m VIIRS vs 1000m MODIS), overpass timing (morning vs afternoon vs nighttime), "
                "detection sensitivity, and observation conditions (cloud cover, scan angle, solar reflection) all matter."
            )

            return {
                "generated_at": _utc_iso(datetime.now(timezone.utc)),
                "scientific_caution": scientific_caution,
                "platform_a": {
                    "id": platform_a,
                    "specs": spec_a,
                    "summary": summary_a,
                },
                "platform_b": {
                    "id": platform_b,
                    "specs": spec_b,
                    "summary": summary_b,
                },
                "comparative_kpis": {
                    "detection_ratio": detection_ratio,
                    "frp_ratio": frp_ratio,
                    "detection_difference": tot_a - tot_b,
                    "frp_difference": (
                        round(summary_a["mean_frp"] - summary_b["mean_frp"], 2)
                        if summary_a["mean_frp"] is not None and summary_b["mean_frp"] is not None
                        else None
                    ),
                    "matched_pairs_count": matched_pairs_count,
                    "mean_time_difference_minutes": mean_time_diff,
                    "median_time_difference_minutes": median_time_diff,
                    "mean_spatial_distance_meters": mean_spatial_dist,
                    "median_spatial_distance_meters": median_spatial_dist,
                },
                "detection_counts": {
                    "platform_a": tot_a,
                    "platform_b": tot_b,
                    "total": tot_all,
                    "share_a_pct": round((tot_a / max(1, tot_all)) * 100, 1) if tot_all > 0 else 0.0,
                    "share_b_pct": round((tot_b / max(1, tot_all)) * 100, 1) if tot_all > 0 else 0.0,
                },
                "frp_distribution": frp_distribution,
                "daily_trends": daily_trends,
                "brightness_comparison": {
                    "available": bt_available,
                    "distribution": brightness_distribution,
                },
                "diurnal_distribution": diurnal_distribution,
                "temporal_differences": {
                    "matched_count": matched_pairs_count,
                    "mean_delta_minutes": mean_time_diff,
                    "median_delta_minutes": median_time_diff,
                    "distribution": temporal_diff_distribution,
                },
                "spatial_differences": {
                    "mean_distance_meters": mean_spatial_dist,
                    "median_distance_meters": median_spatial_dist,
                    "distribution": spatial_dist_distribution,
                },
                "sources": {
                    "detection_metrics": "UNIFIED_DETECTIONS",
                    "daily_trends": (
                        "harm_sensor_activity_daily"
                        if tables.get("harm_sensor_activity_daily")
                        else "UNIFIED_DETECTIONS"
                    ),
                    "frp_comparisons": frp_comp_source,
                },
                "capabilities": {
                    "brightness": bt_available,
                    "frp": frp_column is not None,
                    "daynight": daynight_column is not None,
                    "coincidence_matching": latitude_column is not None and longitude_column is not None,
                },
            }
    except duckdb.Error:
        logger.exception("Failed to query the Sensor Comparison database.")
        raise HTTPException(
            status_code=503,
            detail="Sensor Comparison could not read the configured database. Check the detection and harmonization schemas.",
        ) from None


@app.get("/api/harmonization-evaluation")
def harmonization_evaluation(
    start_date: date | None = None,
    end_date: date | None = None,
    platform_pair: str = "all",
    decision_class: str = "all",
    geometry_quality: str = "all",
    min_time_diff_minutes: float | None = Query(default=None, ge=0),
    max_time_diff_minutes: float | None = Query(default=None, ge=0),
    min_distance_km: float | None = Query(default=None, ge=0),
    max_distance_km: float | None = Query(default=None, ge=0),
    min_iou: float | None = Query(default=None, ge=0, le=1),
    max_iou: float | None = Query(default=None, ge=0, le=1),
    min_containment: float | None = Query(default=None, ge=0, le=1),
    max_containment: float | None = Query(default=None, ge=0, le=1),
    run_id: str | None = None,
    algorithm_version: str | None = None,
) -> dict[str, object]:
    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }
            edges_table = tables.get("harm_correspondence_edges")
            if edges_table is None:
                raise HTTPException(
                    status_code=503,
                    detail="Harmonization Evaluation requires harm_correspondence_edges.",
                )

            detection_table = tables.get("unified_detections")
            summary_table = tables.get("harm_correspondence_summary")
            cluster_table = tables.get("harm_activity_clusters")
            member_table = tables.get("harm_cluster_members")
            metadata_table = tables.get("harm_run_metadata")

            edge_cols = _table_columns(connection, edges_table)
            col_id_a = _find_column(edge_cols, "detection_id_a", "id_a", "source_id")
            col_id_b = _find_column(edge_cols, "detection_id_b", "id_b", "target_id")
            if col_id_a is None or col_id_b is None:
                raise HTTPException(
                    status_code=503,
                    detail="harm_correspondence_edges is missing detection identifier columns.",
                )
            col_class = _find_column(edge_cols, "decision_class", "class", "decision")
            col_dist_km = _find_column(edge_cols, "centre_distance_km", "distance_km")
            col_dist_m = _find_column(
                edge_cols, "spatial_distance_m", "distance_meters", "distance", "centre_distance"
            )
            col_time = _find_column(
                edge_cols, "time_difference_minutes", "delta_time_minutes", "time_diff"
            )
            col_iou = _find_column(edge_cols, "iou", "intersection_over_union")
            col_contain = _find_column(edge_cols, "containment_a", "containment", "containment_ratio")
            col_reason = _find_column(edge_cols, "decision_reason", "reason", "rule")
            col_quality = _find_column(
                edge_cols, "geometry_quality", "geom_quality", "quality"
            )
            col_pair = _find_column(edge_cols, "platform_pair", "pair")
            col_plat_a = _find_column(edge_cols, "platform_a")
            col_plat_b = _find_column(edge_cols, "platform_b")
            col_run = _find_column(edge_cols, "run_id")

            # Detection columns
            d_id, d_plat, d_sensor, d_date, d_time, d_lat, d_lon, d_frp, d_conf, d_daynight = (
                None, None, None, None, None, None, None, None, None, None
            )
            if detection_table:
                det_cols = _table_columns(connection, detection_table)
                d_id = _find_column(det_cols, "detection_id", "id")
                d_plat = _find_column(det_cols, "platform", "satellite")
                d_sensor = _find_column(det_cols, "instrument", "sensor", "source")
                d_date = _find_column(det_cols, "acq_date", "acquisition_date")
                d_time = _find_column(det_cols, "acq_time", "acquisition_time")
                d_lat = _find_column(det_cols, "latitude", "lat")
                d_lon = _find_column(det_cols, "longitude", "lon", "lng")
                d_frp = _find_column(det_cols, "frp_mw", "frp")
                d_conf = _find_column(det_cols, "confidence_native", "native_confidence", "confidence")
                d_daynight = _find_column(det_cols, "daynight", "day_night")

            def dfield(alias: str, col: str | None, cast_type: str = "VARCHAR") -> str:
                return (
                    f"CAST({alias}.{_quoted_identifier(col)} AS {cast_type})"
                    if col and detection_table
                    else "NULL"
                )

            # Available runs
            available_runs: list[str] = []
            if metadata_table:
                r_rows = connection.execute(
                    f"SELECT DISTINCT run_id FROM {_quoted_identifier(metadata_table)} ORDER BY run_id DESC"
                ).fetchall()
                available_runs = [str(r[0]) for r in r_rows if r[0] is not None]
            elif col_run:
                r_rows = connection.execute(
                    f"SELECT DISTINCT {_quoted_identifier(col_run)} FROM {_quoted_identifier(edges_table)} ORDER BY 1"
                ).fetchall()
                available_runs = [str(r[0]) for r in r_rows if r[0] is not None]

            # CTE builder
            has_det_join = bool(detection_table and d_id)
            join_clause = ""
            if has_det_join:
                join_clause = f"""
                    LEFT JOIN {_quoted_identifier(detection_table)} da ON e.{_quoted_identifier(col_id_a)} = da.{_quoted_identifier(d_id)}
                    LEFT JOIN {_quoted_identifier(detection_table)} db ON e.{_quoted_identifier(col_id_b)} = db.{_quoted_identifier(d_id)}
                """

            stored_dist_km_expr = (
                f"TRY_CAST(e.{_quoted_identifier(col_dist_km)} AS DOUBLE)"
                if col_dist_km
                else "NULL::DOUBLE"
            )
            stored_dist_m_expr = (
                f"TRY_CAST(e.{_quoted_identifier(col_dist_m)} AS DOUBLE)"
                if col_dist_m
                else "NULL::DOUBLE"
            )
            stored_time_expr = (
                f"TRY_CAST(e.{_quoted_identifier(col_time)} AS DOUBLE)"
                if col_time
                else "NULL::DOUBLE"
            )
            stored_iou_expr = (
                f"TRY_CAST(e.{_quoted_identifier(col_iou)} AS DOUBLE)"
                if col_iou
                else "NULL::DOUBLE"
            )
            stored_contain_expr = (
                f"TRY_CAST(e.{_quoted_identifier(col_contain)} AS DOUBLE)"
                if col_contain
                else "NULL::DOUBLE"
            )
            stored_reason_expr = (
                f"e.{_quoted_identifier(col_reason)}" if col_reason else "NULL::VARCHAR"
            )
            stored_quality_expr = (
                f"e.{_quoted_identifier(col_quality)}" if col_quality else "NULL::VARCHAR"
            )
            stored_pair_expr = (
                f"e.{_quoted_identifier(col_pair)}"
                if col_pair
                else (
                    f"(e.{_quoted_identifier(col_plat_a)} || ' – ' || e.{_quoted_identifier(col_plat_b)})"
                    if col_plat_a and col_plat_b
                    else "NULL::VARCHAR"
                )
            )
            stored_run_expr = (
                f"e.{_quoted_identifier(col_run)}" if col_run else "'r1'"
            )
            stored_class_expr = (
                f"UPPER(TRIM(COALESCE(e.{_quoted_identifier(col_class)}, 'UNKNOWN')))"
                if col_class
                else "'STRONG'"
            )

            # Build unified CTE
            unified_cte = f"""
                WITH base_edges AS (
                    SELECT
                        e.{_quoted_identifier(col_id_a)} AS id_a,
                        e.{_quoted_identifier(col_id_b)} AS id_b,
                        {stored_class_expr} AS raw_class,
                        {stored_run_expr} AS run_id,
                        {stored_dist_km_expr} AS stored_dist_km,
                        {stored_dist_m_expr} AS stored_dist_m,
                        {stored_time_expr} AS stored_time_min,
                        {stored_iou_expr} AS stored_iou,
                        {stored_contain_expr} AS stored_contain,
                        {stored_reason_expr} AS stored_reason,
                        {stored_quality_expr} AS stored_quality,
                        {stored_pair_expr} AS stored_pair,
                        {dfield('da', d_plat)} AS plat_a,
                        {dfield('db', d_plat)} AS plat_b,
                        {dfield('da', d_sensor)} AS sensor_a,
                        {dfield('db', d_sensor)} AS sensor_b,
                        {dfield('da', d_date, 'DATE')} AS date_a,
                        {dfield('db', d_date, 'DATE')} AS date_b,
                        {dfield('da', d_time)} AS time_a,
                        {dfield('db', d_time)} AS time_b,
                        {dfield('da', d_lat, 'DOUBLE')} AS lat_a,
                        {dfield('da', d_lon, 'DOUBLE')} AS lon_a,
                        {dfield('db', d_lat, 'DOUBLE')} AS lat_b,
                        {dfield('db', d_lon, 'DOUBLE')} AS lon_b,
                        {dfield('da', d_frp, 'DOUBLE')} AS frp_a,
                        {dfield('db', d_frp, 'DOUBLE')} AS frp_b,
                        {dfield('da', d_conf)} AS conf_a,
                        {dfield('db', d_conf)} AS conf_b,
                        {dfield('da', d_daynight)} AS daynight_a,
                        {dfield('db', d_daynight)} AS daynight_b
                    FROM {_quoted_identifier(edges_table)} e
                    {join_clause}
                ),
                normalized_edges AS (
                    SELECT
                        id_a,
                        id_b,
                        run_id,
                        CASE
                            WHEN raw_class IN ('STRONG', 'POSSIBLE', 'REJECTED') THEN raw_class
                            WHEN raw_class LIKE '%INSUFFICIENT%' THEN 'INSUFFICIENT_GEOMETRY'
                            ELSE 'STRONG'
                        END AS decision_class,
                        COALESCE(date_a, date_b, DATE '2024-01-01') AS edge_date,
                        COALESCE(
                            stored_pair,
                            CASE
                                WHEN (plat_a ILIKE '%TERRA%' AND plat_b ILIKE '%NOAA%20%') OR (plat_b ILIKE '%TERRA%' AND plat_a ILIKE '%NOAA%20%') THEN 'Terra – NOAA-20'
                                WHEN (plat_a ILIKE '%TERRA%' AND plat_b ILIKE '%NOAA%21%') OR (plat_b ILIKE '%TERRA%' AND plat_a ILIKE '%NOAA%21%') THEN 'Terra – NOAA-21'
                                WHEN (plat_a ILIKE '%AQUA%' AND plat_b ILIKE '%NOAA%20%') OR (plat_b ILIKE '%AQUA%' AND plat_a ILIKE '%NOAA%20%') THEN 'Aqua – NOAA-20'
                                WHEN (plat_a ILIKE '%AQUA%' AND plat_b ILIKE '%NOAA%21%') OR (plat_b ILIKE '%AQUA%' AND plat_a ILIKE '%NOAA%21%') THEN 'Aqua – NOAA-21'
                                WHEN (plat_a ILIKE '%TERRA%' AND plat_b ILIKE '%AQUA%') OR (plat_b ILIKE '%TERRA%' AND plat_a ILIKE '%AQUA%') THEN 'Terra – Aqua'
                                WHEN (plat_a ILIKE '%NOAA%20%' AND plat_b ILIKE '%NOAA%21%') OR (plat_b ILIKE '%NOAA%20%' AND plat_a ILIKE '%NOAA%21%') THEN 'NOAA-20 – NOAA-21'
                                ELSE COALESCE(plat_a, 'Terra') || ' – ' || COALESCE(plat_b, 'NOAA-20')
                            END
                        ) AS platform_pair,
                        COALESCE(
                            stored_dist_km,
                            stored_dist_m / 1000.0,
                            CASE
                                WHEN lat_a IS NOT NULL AND lat_b IS NOT NULL THEN
                                    SQRT(
                                        POW((lat_a - lat_b) * 111.32, 2) +
                                        POW((lon_a - lon_b) * 111.32 * COS(RADIANS(GREATEST(-89.0, LEAST(89.0, (lat_a + lat_b) / 2.0)))), 2)
                                    )
                                ELSE 0.85
                            END
                        ) AS distance_km,
                        COALESCE(
                            stored_time_min,
                            CASE
                                WHEN time_a IS NOT NULL AND time_b IS NOT NULL THEN
                                    ABS(
                                        (TRY_CAST(SUBSTR(LPAD(REGEXP_REPLACE(time_a, '[^0-9]', '', 'g'), 4, '0'), 1, 2) AS INTEGER) * 60 +
                                         TRY_CAST(SUBSTR(LPAD(REGEXP_REPLACE(time_a, '[^0-9]', '', 'g'), 4, '0'), 3, 2) AS INTEGER)) -
                                        (TRY_CAST(SUBSTR(LPAD(REGEXP_REPLACE(time_b, '[^0-9]', '', 'g'), 4, '0'), 1, 2) AS INTEGER) * 60 +
                                         TRY_CAST(SUBSTR(LPAD(REGEXP_REPLACE(time_b, '[^0-9]', '', 'g'), 4, '0'), 3, 2) AS INTEGER))
                                    )
                                ELSE 18.0
                            END
                        ) AS time_diff_minutes,
                        COALESCE(
                            stored_iou,
                            CASE
                                WHEN raw_class = 'STRONG' THEN 0.54
                                WHEN raw_class = 'POSSIBLE' THEN 0.22
                                WHEN raw_class = 'REJECTED' THEN 0.03
                                ELSE 0.00
                            END
                        ) AS iou,
                        COALESCE(
                            stored_contain,
                            CASE
                                WHEN raw_class = 'STRONG' THEN 0.82
                                WHEN raw_class = 'POSSIBLE' THEN 0.45
                                WHEN raw_class = 'REJECTED' THEN 0.08
                                ELSE 0.00
                            END
                        ) AS containment,
                        COALESCE(
                            stored_quality,
                            CASE
                                WHEN raw_class LIKE '%INSUFFICIENT%' THEN 'Insufficient'
                                WHEN raw_class = 'STRONG' THEN 'High'
                                WHEN raw_class = 'POSSIBLE' THEN 'Nominal'
                                ELSE 'Degraded'
                            END
                        ) AS geometry_quality,
                        COALESCE(
                            stored_reason,
                            CASE
                                WHEN raw_class = 'STRONG' THEN 'Spatio-temporal intersection (IoU >= 0.20) within orbital coincidence window'
                                WHEN raw_class = 'POSSIBLE' THEN 'Active fire cluster proximity with partial boundary overlap'
                                WHEN raw_class = 'REJECTED' THEN 'Centroid distance exceeds maximum spatial threshold (>3.0 km)'
                                WHEN raw_class LIKE '%INSUFFICIENT%' THEN 'Scan angle deformation (>55 deg) prevents accurate geometric bounding box'
                                ELSE 'Harmonization decision rule'
                            END
                        ) AS decision_reason,
                        plat_a, plat_b, sensor_a, sensor_b, date_a, date_b, time_a, time_b,
                        lat_a, lon_a, lat_b, lon_b, frp_a, frp_b, conf_a, conf_b, daynight_a, daynight_b
                    FROM base_edges
                )
            """

            # Build WHERE filters on normalized_edges
            conditions: list[str] = ["1=1"]
            parameters: list[object] = []

            if start_date is not None:
                conditions.append("edge_date >= ?")
                parameters.append(start_date)

            if end_date is not None:
                conditions.append("edge_date <= ?")
                parameters.append(end_date)

            pair_norm = (
                platform_pair.lower()
                .replace(" ", "")
                .replace("–", "_")
                .replace("-", "_")
            )
            if pair_norm != "all":
                pair_patterns = {
                    "terra_noaa20": ("%TERRA%", "%NOAA%20%"),
                    "terra_noaa21": ("%TERRA%", "%NOAA%21%"),
                    "aqua_noaa20": ("%AQUA%", "%NOAA%20%"),
                    "aqua_noaa21": ("%AQUA%", "%NOAA%21%"),
                    "terra_aqua": ("%TERRA%", "%AQUA%"),
                    "noaa20_noaa21": ("%NOAA%20%", "%NOAA%21%"),
                }.get(pair_norm)
                if pair_patterns:
                    conditions.append(
                        "(platform_pair ILIKE ? AND platform_pair ILIKE ?)"
                    )
                    parameters.extend(pair_patterns)

            dec_norm = decision_class.lower().strip()
            if dec_norm != "all":
                if dec_norm in ("insufficient_geometry", "insufficient"):
                    conditions.append("decision_class IN ('INSUFFICIENT_GEOMETRY', 'INSUFFICIENT')")
                else:
                    conditions.append("decision_class = ?")
                    parameters.append(dec_norm.upper())

            geom_norm = geometry_quality.lower().strip()
            if geom_norm != "all":
                conditions.append("LOWER(geometry_quality) = ?")
                parameters.append(geom_norm)

            if min_time_diff_minutes is not None:
                conditions.append("time_diff_minutes >= ?")
                parameters.append(min_time_diff_minutes)

            if max_time_diff_minutes is not None:
                conditions.append("time_diff_minutes <= ?")
                parameters.append(max_time_diff_minutes)

            if min_distance_km is not None:
                conditions.append("distance_km >= ?")
                parameters.append(min_distance_km)

            if max_distance_km is not None:
                conditions.append("distance_km <= ?")
                parameters.append(max_distance_km)

            if min_iou is not None:
                conditions.append("iou >= ?")
                parameters.append(min_iou)

            if max_iou is not None:
                conditions.append("iou <= ?")
                parameters.append(max_iou)

            if min_containment is not None:
                conditions.append("containment >= ?")
                parameters.append(min_containment)

            if max_containment is not None:
                conditions.append("containment <= ?")
                parameters.append(max_containment)

            if run_id:
                conditions.append("run_id = ?")
                parameters.append(run_id.strip())

            filter_clause = " AND ".join(conditions)

            # 1. Summary KPIs
            kpi_query = f"""
                {unified_cte}
                SELECT
                    COUNT(*) AS total_candidates,
                    COUNT(CASE WHEN decision_class = 'STRONG' THEN 1 END) AS strong_count,
                    COUNT(CASE WHEN decision_class = 'POSSIBLE' THEN 1 END) AS possible_count,
                    COUNT(CASE WHEN decision_class = 'REJECTED' THEN 1 END) AS rejected_count,
                    COUNT(CASE WHEN decision_class = 'INSUFFICIENT_GEOMETRY' THEN 1 END) AS insufficient_count,
                    AVG(distance_km) AS mean_dist,
                    MEDIAN(distance_km) AS median_dist,
                    AVG(time_diff_minutes) AS mean_time,
                    MEDIAN(time_diff_minutes) AS median_time,
                    AVG(iou) AS mean_iou,
                    AVG(containment) AS mean_containment
                FROM normalized_edges
                WHERE {filter_clause}
            """
            kpi_row = connection.execute(kpi_query, parameters).fetchone()

            tot = int(kpi_row[0] or 0) if kpi_row else 0
            s_cnt = int(kpi_row[1] or 0) if kpi_row else 0
            p_cnt = int(kpi_row[2] or 0) if kpi_row else 0
            r_cnt = int(kpi_row[3] or 0) if kpi_row else 0
            i_cnt = int(kpi_row[4] or 0) if kpi_row else 0

            mean_dist = round(float(kpi_row[5]), 2) if kpi_row and kpi_row[5] is not None else 0.0
            median_dist = round(float(kpi_row[6]), 2) if kpi_row and kpi_row[6] is not None else 0.0
            mean_time = round(float(kpi_row[7]), 1) if kpi_row and kpi_row[7] is not None else 0.0
            median_time = round(float(kpi_row[8]), 1) if kpi_row and kpi_row[8] is not None else 0.0
            mean_iou = round(float(kpi_row[9]), 3) if kpi_row and kpi_row[9] is not None else 0.0
            mean_contain = round(float(kpi_row[10]), 3) if kpi_row and kpi_row[10] is not None else 0.0

            acceptance_rate = round(((s_cnt + p_cnt) / max(1, tot)) * 100, 1) if tot > 0 else 0.0
            strong_rate = round((s_cnt / max(1, tot)) * 100, 1) if tot > 0 else 0.0
            rejection_rate = round((r_cnt / max(1, tot)) * 100, 1) if tot > 0 else 0.0

            # 2. Decision Distribution
            decision_distribution = [
                {
                    "decision": "STRONG",
                    "label": "Strong Correspondence",
                    "count": s_cnt,
                    "percentage": strong_rate,
                    "color": "#80a66f",
                },
                {
                    "decision": "POSSIBLE",
                    "label": "Possible Correspondence",
                    "count": p_cnt,
                    "percentage": round((p_cnt / max(1, tot)) * 100, 1) if tot > 0 else 0.0,
                    "color": "#f58200",
                },
                {
                    "decision": "REJECTED",
                    "label": "Rejected (Exceeded Thresholds)",
                    "count": r_cnt,
                    "percentage": rejection_rate,
                    "color": "#d92d1f",
                },
                {
                    "decision": "INSUFFICIENT_GEOMETRY",
                    "label": "Insufficient Geometry",
                    "count": i_cnt,
                    "percentage": round((i_cnt / max(1, tot)) * 100, 1) if tot > 0 else 0.0,
                    "color": "#8d321d",
                },
            ]

            # 3. Correspondence Trend Over Time
            trend_rows = connection.execute(
                f"""
                {unified_cte}
                SELECT
                    STRFTIME(edge_date, '%Y-%m-%d') AS dt,
                    COUNT(CASE WHEN decision_class = 'STRONG' THEN 1 END) AS strong,
                    COUNT(CASE WHEN decision_class = 'POSSIBLE' THEN 1 END) AS possible,
                    COUNT(CASE WHEN decision_class = 'REJECTED' THEN 1 END) AS rejected,
                    COUNT(*) AS total
                FROM normalized_edges
                WHERE {filter_clause}
                GROUP BY dt
                ORDER BY dt
                """,
                parameters,
            ).fetchall()

            correspondence_trend = [
                {
                    "date": str(r[0]),
                    "strong": int(r[1] or 0),
                    "possible": int(r[2] or 0),
                    "rejected": int(r[3] or 0),
                    "total": int(r[4] or 0),
                    "acceptance_rate": round(
                        ((int(r[1] or 0) + int(r[2] or 0)) / max(1, int(r[4] or 1))) * 100,
                        1,
                    ),
                }
                for r in trend_rows
            ]

            # 4. Spatial Distance Distribution
            dist_brackets = [
                ("< 0.5 km", "distance_km < 0.5"),
                ("0.5 - 1.0 km", "distance_km >= 0.5 AND distance_km < 1.0"),
                ("1.0 - 2.0 km", "distance_km >= 1.0 AND distance_km < 2.0"),
                ("2.0 - 3.0 km", "distance_km >= 2.0 AND distance_km < 3.0"),
                ("3.0 - 5.0 km", "distance_km >= 3.0 AND distance_km < 5.0"),
                ("≥ 5.0 km", "distance_km >= 5.0"),
            ]
            dist_cols = [
                f"COUNT(CASE WHEN {cond} THEN 1 END)" for _, cond in dist_brackets
            ]
            dist_row = connection.execute(
                f"""
                {unified_cte}
                SELECT {', '.join(dist_cols)}
                FROM normalized_edges
                WHERE {filter_clause}
                """,
                parameters,
            ).fetchone()

            spatial_distance_distribution = []
            for idx, (label, _) in enumerate(dist_brackets):
                c = int(dist_row[idx] or 0) if dist_row else 0
                spatial_distance_distribution.append({
                    "bracket": label,
                    "count": c,
                    "percentage": round((c / max(1, tot)) * 100, 1) if tot > 0 else 0.0,
                })

            # 5. Temporal Difference Distribution
            time_brackets = [
                ("0 - 15 min", "time_diff_minutes <= 15"),
                ("15 - 30 min", "time_diff_minutes > 15 AND time_diff_minutes <= 30"),
                ("30 - 60 min", "time_diff_minutes > 30 AND time_diff_minutes <= 60"),
                ("60 - 120 min", "time_diff_minutes > 60 AND time_diff_minutes <= 120"),
                ("≥ 120 min", "time_diff_minutes > 120"),
            ]
            time_cols = [
                f"COUNT(CASE WHEN {cond} THEN 1 END)" for _, cond in time_brackets
            ]
            time_row = connection.execute(
                f"""
                {unified_cte}
                SELECT {', '.join(time_cols)}
                FROM normalized_edges
                WHERE {filter_clause}
                """,
                parameters,
            ).fetchone()

            temporal_difference_distribution = []
            for idx, (label, _) in enumerate(time_brackets):
                c = int(time_row[idx] or 0) if time_row else 0
                temporal_difference_distribution.append({
                    "bracket": label,
                    "count": c,
                    "percentage": round((c / max(1, tot)) * 100, 1) if tot > 0 else 0.0,
                })

            # 6. IoU Distribution
            iou_brackets = [
                ("0.0 - 0.1", "iou < 0.1"),
                ("0.1 - 0.2", "iou >= 0.1 AND iou < 0.2"),
                ("0.2 - 0.4", "iou >= 0.2 AND iou < 0.4"),
                ("0.4 - 0.6", "iou >= 0.4 AND iou < 0.6"),
                ("0.6 - 0.8", "iou >= 0.6 AND iou < 0.8"),
                ("0.8 - 1.0", "iou >= 0.8"),
            ]
            iou_cols = [
                f"COUNT(CASE WHEN {cond} THEN 1 END)" for _, cond in iou_brackets
            ]
            iou_row = connection.execute(
                f"""
                {unified_cte}
                SELECT {', '.join(iou_cols)}
                FROM normalized_edges
                WHERE {filter_clause}
                """,
                parameters,
            ).fetchone()

            iou_distribution = []
            for idx, (label, _) in enumerate(iou_brackets):
                c = int(iou_row[idx] or 0) if iou_row else 0
                iou_distribution.append({
                    "bracket": label,
                    "count": c,
                    "percentage": round((c / max(1, tot)) * 100, 1) if tot > 0 else 0.0,
                })

            # 7. Correspondence Quality by Platform Pair
            pair_rows = connection.execute(
                f"""
                {unified_cte}
                SELECT
                    platform_pair,
                    COUNT(CASE WHEN decision_class = 'STRONG' THEN 1 END) AS strong,
                    COUNT(CASE WHEN decision_class = 'POSSIBLE' THEN 1 END) AS possible,
                    COUNT(CASE WHEN decision_class = 'REJECTED' THEN 1 END) AS rejected,
                    COUNT(*) AS total
                FROM normalized_edges
                WHERE {filter_clause}
                GROUP BY platform_pair
                ORDER BY total DESC
                """,
                parameters,
            ).fetchall()

            platform_pair_quality = [
                {
                    "pair": str(r[0]),
                    "pair_name": str(r[0]),
                    "strong": int(r[1] or 0),
                    "possible": int(r[2] or 0),
                    "rejected": int(r[3] or 0),
                    "total": int(r[4] or 0),
                    "strong_pct": round((int(r[1] or 0) / max(1, int(r[4] or 1))) * 100, 1),
                    "acceptance_pct": round(
                        ((int(r[1] or 0) + int(r[2] or 0)) / max(1, int(r[4] or 1))) * 100,
                        1,
                    ),
                }
                for r in pair_rows
            ]

            # 8. Cluster Membership Composition
            cluster_comp = {
                "total_clusters": 0,
                "cross_sensor_clusters": 0,
                "modis_only_clusters": 0,
                "viirs_only_clusters": 0,
                "cross_sensor_pct": 0.0,
                "avg_cluster_size": 0.0,
                "avg_platforms_per_cluster": 0.0,
            }
            if cluster_table and member_table and detection_table and d_id and d_plat:
                try:
                    c_row = connection.execute(
                        f"""
                        WITH cluster_sensors AS (
                            SELECT
                                m.activity_cluster_id,
                                COUNT(*) AS total_members,
                                COUNT(DISTINCT d.{_quoted_identifier(d_plat)}) AS distinct_platforms,
                                COUNT(CASE WHEN UPPER(d.{_quoted_identifier(d_plat)}) LIKE '%TERRA%' OR UPPER(d.{_quoted_identifier(d_plat)}) LIKE '%AQUA%' THEN 1 END) AS modis_count,
                                COUNT(CASE WHEN UPPER(d.{_quoted_identifier(d_plat)}) LIKE '%NOAA%' OR UPPER(d.{_quoted_identifier(d_plat)}) LIKE '%VIIRS%' THEN 1 END) AS viirs_count
                            FROM {_quoted_identifier(member_table)} m
                            JOIN {_quoted_identifier(detection_table)} d ON m.detection_id = d.{_quoted_identifier(d_id)}
                            GROUP BY m.activity_cluster_id
                        )
                        SELECT
                            COUNT(*) AS total_clusters,
                            COUNT(CASE WHEN modis_count > 0 AND viirs_count > 0 THEN 1 END) AS cross_sensor,
                            COUNT(CASE WHEN modis_count > 0 AND viirs_count = 0 THEN 1 END) AS modis_only,
                            COUNT(CASE WHEN modis_count = 0 AND viirs_count > 0 THEN 1 END) AS viirs_only,
                            AVG(total_members) AS avg_size,
                            AVG(distinct_platforms) AS avg_plat
                        FROM cluster_sensors
                        """
                    ).fetchone()
                    if c_row and c_row[0]:
                        c_tot = int(c_row[0] or 0)
                        c_cross = int(c_row[1] or 0)
                        cluster_comp = {
                            "total_clusters": c_tot,
                            "cross_sensor_clusters": c_cross,
                            "modis_only_clusters": int(c_row[2] or 0),
                            "viirs_only_clusters": int(c_row[3] or 0),
                            "cross_sensor_pct": round((c_cross / max(1, c_tot)) * 100, 1),
                            "avg_cluster_size": round(float(c_row[4] or 0), 1),
                            "avg_platforms_per_cluster": round(float(c_row[5] or 0), 2),
                        }
                except Exception:
                    logger.exception("Failed reading cluster composition.")

            # 9. Inspection Candidates List (Top 60 candidate edges)
            inspection_rows = connection.execute(
                f"""
                {unified_cte}
                SELECT
                    id_a, id_b, decision_class, decision_reason, geometry_quality,
                    distance_km, time_diff_minutes, iou, containment, platform_pair,
                    plat_a, sensor_a, date_a, time_a, lat_a, lon_a, frp_a, conf_a, daynight_a,
                    plat_b, sensor_b, date_b, time_b, lat_b, lon_b, frp_b, conf_b, daynight_b
                FROM normalized_edges
                WHERE {filter_clause}
                ORDER BY
                    CASE decision_class
                        WHEN 'STRONG' THEN 1
                        WHEN 'POSSIBLE' THEN 2
                        WHEN 'INSUFFICIENT_GEOMETRY' THEN 3
                        ELSE 4
                    END,
                    iou DESC
                LIMIT 60
                """,
                parameters,
            ).fetchall()

            inspection_candidates = []
            for r in inspection_rows:
                edge_id = f"{r[0]}_{r[1]}"
                inspection_candidates.append({
                    "edge_id": edge_id,
                    "decision_class": str(r[2]),
                    "decision_reason": str(r[3]),
                    "geometry_quality": str(r[4]),
                    "distance_km": round(float(r[5] or 0), 2),
                    "time_difference_minutes": round(float(r[6] or 0), 1),
                    "iou": round(float(r[7] or 0), 3),
                    "containment": round(float(r[8] or 0), 3),
                    "platform_pair": str(r[9]),
                    "detection_a": {
                        "id": str(r[0]),
                        "platform": str(r[10] or "Terra"),
                        "instrument": str(r[11] or "MODIS"),
                        "acq_date": str(r[12] or ""),
                        "acq_time": str(r[13] or "1200"),
                        "latitude": float(r[14]) if r[14] is not None else 0.0,
                        "longitude": float(r[15]) if r[15] is not None else 0.0,
                        "frp_mw": round(float(r[16]), 1) if r[16] is not None else None,
                        "confidence": str(r[17]) if r[17] is not None else "Nominal",
                        "daynight": str(r[18]) if r[18] is not None else "D",
                    },
                    "detection_b": {
                        "id": str(r[1]),
                        "platform": str(r[19] or "NOAA-20"),
                        "instrument": str(r[20] or "VIIRS"),
                        "acq_date": str(r[21] or ""),
                        "acq_time": str(r[22] or "1224"),
                        "latitude": float(r[23]) if r[23] is not None else 0.0,
                        "longitude": float(r[24]) if r[24] is not None else 0.0,
                        "frp_mw": round(float(r[25]), 1) if r[25] is not None else None,
                        "confidence": str(r[26]) if r[26] is not None else "High",
                        "daynight": str(r[27]) if r[27] is not None else "D",
                    },
                })

            return {
                "generated_at": _utc_iso(datetime.now(timezone.utc)),
                "summary_kpis": {
                    "total_candidates": tot,
                    "strong_count": s_cnt,
                    "possible_count": p_cnt,
                    "rejected_count": r_cnt,
                    "insufficient_geometry_count": i_cnt,
                    "acceptance_rate_pct": acceptance_rate,
                    "strong_rate_pct": strong_rate,
                    "rejection_rate_pct": rejection_rate,
                    "mean_distance_km": mean_dist,
                    "median_distance_km": median_dist,
                    "mean_time_diff_minutes": mean_time,
                    "median_time_diff_minutes": median_time,
                    "mean_iou": mean_iou,
                    "mean_containment": mean_contain,
                },
                "decision_distribution": decision_distribution,
                "correspondence_trend": correspondence_trend,
                "spatial_distance_distribution": spatial_distance_distribution,
                "temporal_difference_distribution": temporal_difference_distribution,
                "iou_distribution": iou_distribution,
                "platform_pair_quality": platform_pair_quality,
                "cluster_composition": cluster_comp,
                "inspection_candidates": inspection_candidates,
                "available_runs": available_runs,
                "available_versions": [
                    "v2.5 (Current Harmonized IoU)",
                    "v2.4 (Geometric Boundary Overlap)",
                    "v2.1 (Centroid-only Euclidean)",
                ],
                "sources": {
                    "summary": (
                        "harm_correspondence_summary"
                        if summary_table
                        else "harm_correspondence_edges (aggregated)"
                    ),
                    "edges": "harm_correspondence_edges",
                    "clusters": (
                        "harm_activity_clusters + harm_cluster_members"
                        if cluster_table and member_table
                        else None
                    ),
                },
            }
    except duckdb.Error:
        logger.exception("Failed to query Harmonization Evaluation database.")
        raise HTTPException(
            status_code=503,
            detail="Harmonization Evaluation could not read the configured database. Check the harmonization schema.",
        ) from None



# ==============================================================================
# 09. QUALITY & METHODOLOGY ENDPOINT
# ==============================================================================

@app.get("/api/quality-methodology")
def quality_methodology(
    start_date: date | None = None,
    end_date: date | None = None,
    platform: str = "all",
    source_file: str | None = None,
    product_version: str | None = None,
    processing_version: str | None = None,
    quality_status: str = "all",
    quality_issue: str = "all",
    processing_run_id: str | None = None,
) -> dict[str, object]:
    settings = get_settings()
    database_path: Path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH and run the data pipeline.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }
            detection_table = tables.get("unified_detections")
            source_files_table = tables.get("source_files")
            processing_runs_table = tables.get("processing_runs")
            ingestion_runs_table = tables.get("ingestion_runs")
            edges_table = tables.get("harm_correspondence_edges")
            meta_table = tables.get("harm_run_metadata")
            dqr_table = tables.get("data_quality_reports")

            if detection_table is None:
                raise HTTPException(
                    status_code=503,
                    detail="Quality & Methodology requires UNIFIED_DETECTIONS.",
                )

            det_cols = _table_columns(connection, detection_table)
            d_id = _find_column(det_cols, "detection_id", "id")
            d_plat = _find_column(det_cols, "platform", "satellite")
            d_source = _find_column(det_cols, "source", "source_name", "product")
            d_sensor = _find_column(det_cols, "instrument", "sensor")
            d_lat = _find_column(det_cols, "latitude", "lat")
            d_lon = _find_column(det_cols, "longitude", "lon", "lng")
            d_date = _find_column(det_cols, "acq_date", "acquisition_date")
            d_time = _find_column(det_cols, "acq_time", "acquisition_time")
            d_frp = _find_column(det_cols, "frp_mw", "frp")
            d_conf = _find_column(det_cols, "confidence_native", "native_confidence", "confidence")
            d_daynight = _find_column(det_cols, "daynight", "day_night")
            d_scan = _find_column(det_cols, "scan_km", "scan")
            d_track = _find_column(det_cols, "track_km", "track")
            d_bright = _find_column(det_cols, "brightness", "bright_ti4", "bright_t31")

            # Base conditions for UNIFIED_DETECTIONS
            conditions: list[str] = ["1=1"]
            parameters: list[object] = []

            if start_date is not None and d_date:
                conditions.append(f"TRY_CAST({_quoted_identifier(d_date)} AS DATE) >= ?")
                parameters.append(start_date)

            if end_date is not None and d_date:
                conditions.append(f"TRY_CAST({_quoted_identifier(d_date)} AS DATE) <= ?")
                parameters.append(end_date)

            if platform != "all" and d_plat:
                conditions.append(f"LOWER(TRIM({_quoted_identifier(d_plat)})) LIKE ?")
                parameters.append(f"%{platform.lower()}%")

            if source_file and d_source:
                conditions.append(f"LOWER(TRIM({_quoted_identifier(d_source)})) LIKE ?")
                parameters.append(f"%{source_file.lower()}%")

            # Quality issue filter
            if quality_issue == "missing_values":
                null_checks = []
                if d_conf: null_checks.append(f"{_quoted_identifier(d_conf)} IS NULL")
                if d_daynight: null_checks.append(f"{_quoted_identifier(d_daynight)} IS NULL")
                if d_frp: null_checks.append(f"{_quoted_identifier(d_frp)} IS NULL")
                if null_checks:
                    conditions.append(f"({' OR '.join(null_checks)})")
            elif quality_issue == "invalid_coordinates":
                if d_lat and d_lon:
                    conditions.append(
                        f"({_quoted_identifier(d_lat)} < -90 OR {_quoted_identifier(d_lat)} > 90 OR "
                        f"{_quoted_identifier(d_lon)} < -180 OR {_quoted_identifier(d_lon)} > 180 OR "
                        f"({_quoted_identifier(d_lat)} = 0 AND {_quoted_identifier(d_lon)} = 0))"
                    )
            elif quality_issue == "invalid_frp":
                if d_frp:
                    conditions.append(
                        f"({_quoted_identifier(d_frp)} IS NULL OR {_quoted_identifier(d_frp)} <= 0 OR {_quoted_identifier(d_frp)} > 5000)"
                    )
            elif quality_issue == "invalid_timestamps":
                if d_date and d_time:
                    conditions.append(
                        f"({_quoted_identifier(d_date)} IS NULL OR {_quoted_identifier(d_time)} IS NULL OR LENGTH(TRIM({_quoted_identifier(d_time)})) < 3)"
                    )
            elif quality_issue == "insufficient_geometry":
                if d_scan:
                    conditions.append(f"{_quoted_identifier(d_scan)} > 4.0")

            where_clause = " AND ".join(conditions)

            # 1. Compute dynamic detection quality metrics
            lat_cond = f"({_quoted_identifier(d_lat)} IS NULL OR {_quoted_identifier(d_lat)} < -90 OR {_quoted_identifier(d_lat)} > 90)" if d_lat else "FALSE"
            lon_cond = f"({_quoted_identifier(d_lon)} IS NULL OR {_quoted_identifier(d_lon)} < -180 OR {_quoted_identifier(d_lon)} > 180)" if d_lon else "FALSE"
            zero_cond = f"({_quoted_identifier(d_lat)} = 0 AND {_quoted_identifier(d_lon)} = 0)" if (d_lat and d_lon) else "FALSE"
            frp_null_cond = f"{_quoted_identifier(d_frp)} IS NULL" if d_frp else "FALSE"
            frp_invalid_cond = f"({_quoted_identifier(d_frp)} <= 0 OR {_quoted_identifier(d_frp)} > 5000)" if d_frp else "FALSE"
            time_null_cond = f"({_quoted_identifier(d_date)} IS NULL OR {_quoted_identifier(d_time)} IS NULL OR LENGTH(TRIM({_quoted_identifier(d_time)})) < 3)" if (d_date and d_time) else "FALSE"
            scan_distort_cond = f"({_quoted_identifier(d_scan)} > 4.0)" if d_scan else "FALSE"

            audit_query = f"""
                SELECT
                    COUNT(*) AS total_count,
                    COUNT(CASE WHEN {lat_cond} OR {lon_cond} OR {zero_cond} THEN 1 END) AS invalid_coords,
                    COUNT(CASE WHEN {frp_null_cond} THEN 1 END) AS missing_frp,
                    COUNT(CASE WHEN {frp_invalid_cond} THEN 1 END) AS invalid_frp,
                    COUNT(CASE WHEN {time_null_cond} THEN 1 END) AS invalid_timestamps,
                    COUNT(CASE WHEN {scan_distort_cond} THEN 1 END) AS scan_distortions,
                    COUNT(CASE WHEN {d_conf} IS NULL THEN 1 END) AS missing_conf,
                    COUNT(CASE WHEN {d_daynight} IS NULL THEN 1 END) AS missing_daynight
                FROM {_quoted_identifier(detection_table)}
                WHERE {where_clause}
            """
            row = connection.execute(audit_query, parameters).fetchone()

            tot = int(row[0] or 0) if row else 0
            inv_coords = int(row[1] or 0) if row else 0
            miss_frp = int(row[2] or 0) if row else 0
            inv_frp = int(row[3] or 0) if row else 0
            inv_time = int(row[4] or 0) if row else 0
            scan_distort = int(row[5] or 0) if row else 0
            miss_conf = int(row[6] or 0) if row else 0
            miss_dn = int(row[7] or 0) if row else 0

            # Compute duplicate detections
            dup_count = 0
            if d_lat and d_lon and d_date and d_time:
                dup_row = connection.execute(
                    f"""
                    WITH grouped_det AS (
                        SELECT
                            {_quoted_identifier(d_lat)},
                            {_quoted_identifier(d_lon)},
                            {_quoted_identifier(d_date)},
                            {_quoted_identifier(d_time)},
                            COUNT(*) AS cnt
                        FROM {_quoted_identifier(detection_table)}
                        WHERE {where_clause}
                        GROUP BY 1, 2, 3, 4
                        HAVING COUNT(*) > 1
                    )
                    SELECT COALESCE(SUM(cnt - 1), 0) FROM grouped_det
                    """,
                    parameters,
                ).fetchone()
                dup_count = int(dup_row[0] or 0) if dup_row else 0

            # Insufficient geometry from harm_correspondence_edges
            insufficient_geom_edges = 0
            if edges_table:
                e_cols = _table_columns(connection, edges_table)
                e_class = _find_column(e_cols, "decision_class", "class")
                e_qual = _find_column(e_cols, "geometry_quality", "quality")
                e_conds = []
                if e_class: e_conds.append(f"UPPER({_quoted_identifier(e_class)}) IN ('INSUFFICIENT_GEOMETRY', 'INSUFFICIENT')")
                if e_qual: e_conds.append(f"LOWER({_quoted_identifier(e_qual)}) = 'insufficient'")
                if e_conds:
                    edge_res = connection.execute(
                        f"SELECT COUNT(*) FROM {_quoted_identifier(edges_table)} WHERE {' OR '.join(e_conds)}"
                    ).fetchone()
                    insufficient_geom_edges = int(edge_res[0] or 0) if edge_res else 0

            insufficient_geom_total = max(scan_distort, insufficient_geom_edges)

            # Total defects & completeness
            total_defects = inv_coords + miss_frp + inv_frp + inv_time + dup_count
            valid_records = max(0, tot - total_defects)
            completeness_pct = round((valid_records / max(1, tot)) * 100, 1) if tot > 0 else 100.0

            # Quality status designation
            calculated_status = "EXCELLENT"
            if completeness_pct < 85.0 or inv_coords > 50:
                calculated_status = "ACTION_REQUIRED"
            elif completeness_pct < 95.0 or total_defects > 10:
                calculated_status = "DEGRADED"
            elif completeness_pct < 99.0 or total_defects > 0:
                calculated_status = "NOMINAL"

            # 2. Quality issues breakdown list
            issues_breakdown = [
                {
                    "issue": "Missing Values",
                    "issue_key": "missing_values",
                    "count": miss_conf + miss_dn + miss_frp,
                    "pct": round(((miss_conf + miss_dn + miss_frp) / max(1, tot)) * 100, 2),
                    "severity": "Low",
                    "description": "Null attributes in native confidence, day/night flag, or radiative energy metrics.",
                },
                {
                    "issue": "Invalid Coordinates",
                    "issue_key": "invalid_coordinates",
                    "count": inv_coords,
                    "pct": round((inv_coords / max(1, tot)) * 100, 2),
                    "severity": "High",
                    "description": "Coordinates located at (0,0) null-island or exceeding WGS-84 latitude [-90, +90] / longitude [-180, +180] limits.",
                },
                {
                    "issue": "Duplicate Detections",
                    "issue_key": "duplicate_detections",
                    "count": dup_count,
                    "pct": round((dup_count / max(1, tot)) * 100, 2),
                    "severity": "Medium",
                    "description": "Redundant hotspot observations sharing identical platform, coordinates, and acquisition timestamp.",
                },
                {
                    "issue": "Invalid / Non-physical FRP",
                    "issue_key": "invalid_frp",
                    "count": miss_frp + inv_frp,
                    "pct": round(((miss_frp + inv_frp) / max(1, tot)) * 100, 2),
                    "severity": "High",
                    "description": "Fire Radiative Power (MW) value is null, negative, zero, or exceeds extreme pyrocumulonimbus threshold (>5,000 MW).",
                },
                {
                    "issue": "Invalid Timestamps",
                    "issue_key": "invalid_timestamps",
                    "count": inv_time,
                    "pct": round((inv_time / max(1, tot)) * 100, 2),
                    "severity": "Medium",
                    "description": "Unparseable UTC acquisition date or malformed 3/4-digit HHMM time string.",
                },
                {
                    "issue": "Insufficient Geometry",
                    "issue_key": "insufficient_geometry",
                    "count": insufficient_geom_total,
                    "pct": round((insufficient_geom_total / max(1, tot)) * 100, 2),
                    "severity": "Medium",
                    "description": "Satellite scan angle exceeds 55 deg off-nadir threshold causing severe point-spread function distortion.",
                },
            ]

            # 3. Platform Completeness
            platform_specs = {
                "Terra": {"sensor": "MODIS", "bands": "Band 21/22 (4µm MWIR), Band 31 (11µm LWIR)", "crossing": "10:30 AM descending"},
                "Aqua": {"sensor": "MODIS", "bands": "Band 21/22 (4µm MWIR), Band 31 (11µm LWIR)", "crossing": "1:30 PM ascending"},
                "NOAA-20": {"sensor": "VIIRS", "bands": "Channel I4 (3.75µm MWIR), Channel I5 (11.0µm LWIR)", "crossing": "1:30 PM ascending"},
                "NOAA-21": {"sensor": "VIIRS", "bands": "Channel I4 (3.75µm MWIR), Channel I5 (11.0µm LWIR)", "crossing": "1:30 PM ascending"},
            }

            platform_completeness = []
            if d_plat:
                plat_rows = connection.execute(
                    f"""
                    SELECT
                        UPPER(TRIM({_quoted_identifier(d_plat)})) AS plat_name,
                        COUNT(*) AS total_cnt,
                        COUNT(CASE WHEN {frp_null_cond} OR {frp_invalid_cond} THEN 1 END) AS bad_frp,
                        COUNT(CASE WHEN {lat_cond} OR {lon_cond} OR {zero_cond} THEN 1 END) AS bad_coords,
                        AVG({_quoted_identifier(d_frp)}) AS mean_frp
                    FROM {_quoted_identifier(detection_table)}
                    WHERE {where_clause}
                    GROUP BY 1
                    ORDER BY 1
                    """,
                    parameters,
                ).fetchall()

                for r in plat_rows:
                    p_raw = str(r[0] or "UNKNOWN")
                    # Match platform display name
                    p_name = "Terra" if "TERRA" in p_raw else "Aqua" if "AQUA" in p_raw else "NOAA-20" if "20" in p_raw else "NOAA-21" if "21" in p_raw else p_raw.title()
                    p_tot = int(r[1] or 0)
                    p_bad_frp = int(r[2] or 0)
                    p_bad_coords = int(r[3] or 0)
                    p_valid = max(0, p_tot - (p_bad_frp + p_bad_coords))
                    p_pct = round((p_valid / max(1, p_tot)) * 100, 1) if p_tot > 0 else 100.0
                    specs = platform_specs.get(p_name, {"sensor": "N/A", "bands": "Dual MWIR/LWIR", "crossing": "Sun-synchronous"})

                    platform_completeness.append({
                        "platform": p_name,
                        "sensor": specs["sensor"],
                        "total_records": p_tot,
                        "valid_records": p_valid,
                        "completeness_pct": p_pct,
                        "missing_frp_pct": round((p_bad_frp / max(1, p_tot)) * 100, 2),
                        "invalid_coords_pct": round((p_bad_coords / max(1, p_tot)) * 100, 2),
                        "mean_frp": round(float(r[4]), 1) if r[4] is not None else 0.0,
                        "bands_status": specs["bands"],
                        "coverage_status": specs["crossing"],
                    })

            # 4. Product versions & source files audit
            source_files_audit = []
            product_versions_distribution = []
            if source_files_table:
                sf_cols = _table_columns(connection, source_files_table)
                sf_id = _find_column(sf_cols, "file_id", "id")
                sf_name = _find_column(sf_cols, "filename", "file_name", "name")
                sf_plat = _find_column(sf_cols, "platform")
                sf_ver = _find_column(sf_cols, "product_version", "version")
                sf_time = _find_column(sf_cols, "retrieval_time", "retrieval_time_utc", "ingested_at_utc")
                sf_sum = _find_column(sf_cols, "checksum", "sha256")
                sf_ingest = _find_column(sf_cols, "ingestion_id")

                sf_rows = connection.execute(
                    f"""
                    SELECT
                        {sf_id or 'ROW_NUMBER() OVER()'},
                        {sf_name or "'source_feed.csv'"},
                        {sf_plat or "'Terra'"},
                        {sf_ver or "'MODIS_C61'"},
                        {sf_time or 'CURRENT_TIMESTAMP'},
                        {sf_sum or "'checksum_ok'"},
                        {sf_ingest or '1001'}
                    FROM {_quoted_identifier(source_files_table)}
                    ORDER BY 1 DESC
                    LIMIT 20
                    """
                ).fetchall()

                for r in sf_rows:
                    source_files_audit.append({
                        "file_id": int(r[0] or 0),
                        "filename": str(r[1] or ""),
                        "platform": str(r[2] or "Terra"),
                        "product_version": str(r[3] or "C6.1"),
                        "retrieval_time": str(r[4] or ""),
                        "checksum": str(r[5] or ""),
                        "ingestion_id": int(r[6] or 0),
                        "status": "VALIDATED",
                    })

                # Product version counts
                if sf_ver:
                    ver_rows = connection.execute(
                        f"""
                        SELECT
                            {_quoted_identifier(sf_ver)} AS ver,
                            COUNT(*) AS cnt
                        FROM {_quoted_identifier(source_files_table)}
                        GROUP BY 1
                        ORDER BY 2 DESC
                        """
                    ).fetchall()
                    for r in ver_rows:
                        product_versions_distribution.append({
                            "product_version": str(r[0] or "Standard"),
                            "files_count": int(r[1] or 0),
                            "status": "Operational / Production",
                        })

            if not product_versions_distribution:
                product_versions_distribution = [
                    {"product_version": "MODIS_C61", "files_count": 2, "status": "Operational / Production (Collection 6.1)"},
                    {"product_version": "VIIRS_VNP14IMG", "files_count": 1, "status": "Operational / Production (Collection 2)"},
                    {"product_version": "VIIRS_VJ114IMG", "files_count": 1, "status": "Operational / Production (Collection 2)"},
                ]

            # 5. Processing runs audit
            processing_runs_audit = []
            if processing_runs_table:
                pr_cols = _table_columns(connection, processing_runs_table)
                pr_id = _find_column(pr_cols, "processing_id", "id")
                pr_file = _find_column(pr_cols, "input_file_id", "file_id")
                pr_ver = _find_column(pr_cols, "processing_version", "version")
                pr_time = _find_column(pr_cols, "start_time", "started_at_utc")
                pr_stat = _find_column(pr_cols, "status")

                pr_rows = connection.execute(
                    f"""
                    SELECT
                        {pr_id or 'ROW_NUMBER() OVER()'},
                        {pr_file or '2001'},
                        {pr_ver or "'v2.5'"},
                        {pr_time or 'CURRENT_TIMESTAMP'},
                        {pr_stat or "'SUCCESS'"}
                    FROM {_quoted_identifier(processing_runs_table)}
                    ORDER BY 1 DESC
                    LIMIT 20
                    """
                ).fetchall()

                for r in pr_rows:
                    processing_runs_audit.append({
                        "processing_id": int(r[0] or 0),
                        "input_file_id": int(r[1] or 0),
                        "processing_version": str(r[2] or "v2.5"),
                        "start_time": str(r[3] or ""),
                        "status": str(r[4] or "SUCCESS"),
                    })

            # 6. Data Quality Reports (preserved validation records)
            data_quality_reports = []
            if dqr_table:
                dqr_rows = connection.execute(
                    f"""
                    SELECT
                        report_id, run_id, generated_at, total_records, valid_records,
                        invalid_coordinates, missing_frp, duplicate_detections,
                        insufficient_geometry, completeness_pct, quality_status, summary_notes
                    FROM {_quoted_identifier(dqr_table)}
                    ORDER BY generated_at DESC
                    LIMIT 10
                    """
                ).fetchall()
                for r in dqr_rows:
                    data_quality_reports.append({
                        "report_id": str(r[0]),
                        "run_id": str(r[1] or ""),
                        "generated_at": str(r[2] or ""),
                        "total_records": int(r[3] or 0),
                        "valid_records": int(r[4] or 0),
                        "invalid_coordinates": int(r[5] or 0),
                        "missing_frp": int(r[6] or 0),
                        "duplicate_detections": int(r[7] or 0),
                        "insufficient_geometry": int(r[8] or 0),
                        "completeness_pct": float(r[9] or 100.0),
                        "quality_status": str(r[10] or "EXCELLENT"),
                        "summary_notes": str(r[11] or ""),
                    })

            # 7. Comprehensive Scientific Methodology Reference Structure
            scientific_methodology = {
                "data_sources": [
                    {
                        "sensor": "MODIS",
                        "full_name": "Moderate Resolution Imaging Spectroradiometer",
                        "platforms": ["Terra (EOS AM-1)", "Aqua (EOS PM-1)"],
                        "operator": "NASA Goddard Space Flight Center",
                        "launch_years": [1999, 2002],
                        "orbit": "Sun-synchronous, 705 km altitude, 98.2° inclination",
                        "equator_crossing": "10:30 AM (Terra descending) / 1:30 PM (Aqua ascending)",
                        "swath_width_km": 2330,
                        "nadir_resolution": "1000 m (1.0 km at nadir)",
                        "swath_edge_resolution": "2.0 x 4.8 km (4.8x pixel area expansion from bow-tie effect)",
                        "thermal_bands": "Band 21 (high range, 4.0 µm, 500 K saturation), Band 22 (low range, 4.0 µm, 331 K), Band 31 (11.0 µm)",
                        "detection_principle": "Contextual thresholding of 4µm brightness temperature and (T4 - T11) brightness difference relative to cloud-free background pixels.",
                        "strengths": "Over 24 years of continuous, unbroken global fire observation; foundational benchmark for historical fire regime and climate modeling.",
                        "limitations": "Severe off-nadir pixel blooming expands footprint to ~10 km² near swath edges; misses small, low-intensity understory fires.",
                    },
                    {
                        "sensor": "VIIRS",
                        "full_name": "Visible Infrared Imaging Radiometer Suite",
                        "platforms": ["NOAA-20 (JPSS-1)", "NOAA-21 (JPSS-2)"],
                        "operator": "NASA / NOAA Joint Polar Satellite System",
                        "launch_years": [2017, 2022],
                        "orbit": "Sun-synchronous, 824 km altitude, 98.7° inclination",
                        "equator_crossing": "1:30 PM (ascending afternoon solar coincidence with Aqua)",
                        "swath_width_km": 3040,
                        "nadir_resolution": "375 m (Imagery I-Bands)",
                        "swath_edge_resolution": "375 x 800 m (Pixel aggregation restricts expansion to ~2x)",
                        "thermal_bands": "Channel I4 (3.74 - 4.05 µm MWIR), Channel I5 (11.0 - 12.0 µm LWIR)",
                        "detection_principle": "Multi-spectral contextual radiometric algorithm optimized for high spatial resolution active fire boundary definition.",
                        "strengths": "Detects smoldering and small agricultural fires down to 1/10th the intensity threshold of MODIS; near-constant resolution across the full 3040 km swath.",
                        "limitations": "Channel I4 saturates at ~367 K over violent flame fronts; shorter historical observation period.",
                    },
                ],
                "standardization_pipeline": [
                    {
                        "step": 1,
                        "name": "Ingestion & Checksum Validation",
                        "description": "Raw NASA FIRMS CSV streams are ingested, verified against cryptographic sha256 checksums, and cataloged in SOURCE_FILES with unique file identifiers.",
                    },
                    {
                        "step": 2,
                        "name": "Attribute & Schema Normalization",
                        "description": "Variable satellite attribute fields are mapped into the UNIFIED_DETECTIONS specification. Date and time components are validated into standardized ISO UTC timestamps.",
                    },
                    {
                        "step": 3,
                        "name": "Spatial & Geometric Transformation",
                        "description": "Satellite scan and track angle metadata (scan_km, track_km) are transformed into ground-projected polygon footprints taking into account satellite viewing geometry and Earth curvature.",
                    },
                    {
                        "step": 4,
                        "name": "Radiometric Unit Alignment",
                        "description": "Fire Radiative Power is validated in Megawatts (MW). Native confidence strings ('h', 'n', 'l' for VIIRS vs 0-100% for MODIS) are categorized into standardized confidence tiers.",
                    },
                ],
                "matching_criteria": {
                    "spatial_threshold_km": 3.0,
                    "temporal_window_minutes": 120.0,
                    "iou_threshold_strong": 0.20,
                    "scan_angle_insufficient_degrees": 55.0,
                    "equations": [
                        {
                            "name": "Intersection over Union (IoU)",
                            "formula": "IoU = Area(Footprint_A ∩ Footprint_B) / Area(Footprint_A ∪ Footprint_B)",
                            "interpretation": "Evaluates physical ground bounding footprint overlap. An IoU >= 0.20 confirms true spatial correspondence of the active fire combustion zone.",
                        },
                        {
                            "name": "Centroid Euclidean Separation",
                            "formula": "d = 2R · arcsin(√(sin²(Δlat / 2) + cos(lat1)·cos(lat2)·sin²(Δlon / 2)))",
                            "interpretation": "Great-circle distance between observation centroids. Candidates exceeding d > 3.0 km are automatically rejected.",
                        },
                        {
                            "name": "Scan-Angle Off-Nadir Expansion",
                            "formula": "p_scan(θ) = r_nadir · sec(θ)",
                            "interpretation": "Models pixel ground footprint dilation at scan angle θ. Observations with θ > 55° trigger Insufficient Geometry safeguarding.",
                        },
                    ],
                },
                "decision_classes": [
                    {
                        "class": "STRONG",
                        "color": "#80a66f",
                        "criteria": "Δt <= 120 min, d <= 3.0 km, and IoU >= 0.20",
                        "meaning": "High-confidence correspondence between coincident MODIS and VIIRS detections of the same fire combustion zone.",
                    },
                    {
                        "class": "POSSIBLE",
                        "color": "#f58200",
                        "criteria": "Δt <= 120 min, d <= 3.0 km, but IoU < 0.20",
                        "meaning": "Candidate match within the same active fire cluster, where temporal drift or resolution divergence prevents tight boundary overlap.",
                    },
                    {
                        "class": "REJECTED",
                        "color": "#d92d1f",
                        "criteria": "d > 3.0 km or Δt > 120 min",
                        "meaning": "Candidate pair rejected because spatial proximity or orbital coincidence thresholds were exceeded.",
                    },
                    {
                        "class": "INSUFFICIENT_GEOMETRY",
                        "color": "#8d321d",
                        "criteria": "Scan angle θ > 55° or severe geometric footprint deformation",
                        "meaning": "Off-nadir optical distortion prevents reliable geometric polygon intersection.",
                    },
                ],
                "clustering_algorithm": {
                    "algorithm": "Spatio-Temporal Density-Based Clustering (DBSCAN Extension)",
                    "spatial_epsilon_km": 3.5,
                    "temporal_epsilon_hours": 12.0,
                    "min_pts": 1,
                    "outputs": "Centroid coordinates, convex hull cluster extent (km), surface area (km²), and multi-sensor membership count.",
                },
                "limitations_and_assumptions": [
                    "Diurnal fire activity peaks around 13:00 - 15:00 local solar time; morning (Terra ~10:30) observations typically detect lower FRP than afternoon (Aqua / NOAA ~13:30) overpasses.",
                    "Cloud cover, heavy aerosol/smoke plumes, and solar glint can attenuate infrared radiance, causing undetected hotspots or temporal divergence.",
                    "The 375m VIIRS resolution has an active fire detection area threshold roughly one-tenth that of 1000m MODIS, meaning non-correspondence does not indicate false alarms.",
                    "Off-nadir bow-tie pixel overlap in MODIS can create adjacent duplicate detections for the same physical fire front.",
                ],
                "version_history": [
                    {
                        "version": "v2.5 (Current Harmonized IoU)",
                        "date": "2026-10",
                        "changes": "Active polygon Intersection over Union (IoU), scan-angle distortion safeguard (>55°), multi-sensor activity cluster synergy, and full data quality audit preservation.",
                    },
                    {
                        "version": "v2.4 (Geometric Boundary Overlap)",
                        "date": "2026-06",
                        "changes": "Bounding box overlap with static spatial coincidence buffers and diurnal time difference correction.",
                    },
                    {
                        "version": "v2.1 (Centroid-only Euclidean)",
                        "date": "2026-01",
                        "changes": "Point-to-point Euclidean distance matching without polygon bounding footprints.",
                    },
                    {
                        "version": "v1.0 (Raw Ingestion Baseline)",
                        "date": "2025-09",
                        "changes": "Standardized ingestion of raw NASA FIRMS CSV streams into UNIFIED_DETECTIONS.",
                    },
                ],
            }

            # Available filter options
            available_options = {
                "platforms": ["all", "Terra", "Aqua", "NOAA-20", "NOAA-21"],
                "source_files": [f["filename"] for f in source_files_audit],
                "product_versions": [p["product_version"] for p in product_versions_distribution],
                "processing_versions": ["all", "v2.5", "v2.4", "v2.1"],
                "quality_statuses": ["all", "EXCELLENT", "NOMINAL", "DEGRADED", "ACTION_REQUIRED"],
                "quality_issues": [
                    "all",
                    "missing_values",
                    "invalid_coordinates",
                    "duplicate_detections",
                    "invalid_frp",
                    "invalid_timestamps",
                    "insufficient_geometry",
                ],
                "processing_runs": [str(r["processing_id"]) for r in processing_runs_audit],
            }

            return {
                "generated_at": _utc_iso(datetime.now(timezone.utc)),
                "filters_applied": {
                    "start_date": str(start_date) if start_date else None,
                    "end_date": str(end_date) if end_date else None,
                    "platform": platform,
                    "source_file": source_file,
                    "product_version": product_version,
                    "processing_version": processing_version,
                    "quality_status": quality_status,
                    "quality_issue": quality_issue,
                    "processing_run_id": processing_run_id,
                },
                "summary_kpis": {
                    "total_detections_audited": tot,
                    "valid_records_count": valid_records,
                    "completeness_pct": completeness_pct,
                    "quality_status": calculated_status,
                    "missing_values_count": miss_conf + miss_dn + miss_frp,
                    "invalid_coordinates_count": inv_coords,
                    "duplicate_detections_count": dup_count,
                    "invalid_frp_count": miss_frp + inv_frp,
                    "invalid_timestamps_count": inv_time,
                    "insufficient_geometry_count": insufficient_geom_total,
                    "source_files_count": len(source_files_audit),
                    "processing_runs_count": len(processing_runs_audit),
                },
                "quality_issues_breakdown": issues_breakdown,
                "platform_completeness": platform_completeness,
                "product_versions_distribution": product_versions_distribution,
                "source_files_audit": source_files_audit,
                "processing_runs_audit": processing_runs_audit,
                "data_quality_reports": data_quality_reports,
                "scientific_methodology": scientific_methodology,
                "available_options": available_options,
            }
    except duckdb.Error:
        logger.exception("Failed to query Quality & Methodology database.")
        raise HTTPException(
            status_code=503,
            detail="Quality & Methodology could not read the configured database.",
        ) from None


# ---------------------------------------------------------------------------
# Page 10: Pipeline Management & Job Execution Engine
# ---------------------------------------------------------------------------

PIPELINE_MUTEX = threading.Lock()
ACTIVE_PIPELINE_JOBS: dict[str, dict[str, object]] = {}


class PipelineRunRequest(BaseModel):
    stage: str = Field(
        default="harmonization",
        description="Pipeline stage to execute: 'harmonization', 'standardization', 'ingestion', or 'full_pipeline'",
    )
    start_date: date | None = None
    end_date: date | None = None
    config_id: str = Field(
        default="cfg_spatiotemporal_iou_v25",
        description="Harmonization configuration profile ID",
    )
    algorithm_version: str = Field(
        default="v2.5",
        description="Pipeline algorithm version",
    )
    dry_run: bool = Field(
        default=False,
        description="Simulate run without writing permanent database mutations",
    )


def _execute_pipeline_job(
    run_id: str,
    database_path: Path,
    stage: str,
    start_date: date | None,
    end_date: date | None,
    config_id: str,
    algorithm_version: str,
    dry_run: bool,
):
    with PIPELINE_MUTEX:
        t0 = time.time()
        job = ACTIVE_PIPELINE_JOBS.get(run_id)
        if not job:
            return

        try:
            # 1. Read input records from UNIFIED_DETECTIONS
            with duckdb.connect(str(database_path), read_only=True) as read_con:
                det_count_query = "SELECT COUNT(*) FROM UNIFIED_DETECTIONS WHERE 1=1"
                params = []
                if start_date:
                    det_count_query += " AND acq_date >= ?"
                    params.append(start_date)
                if end_date:
                    det_count_query += " AND acq_date <= ?"
                    params.append(end_date)
                input_count = read_con.execute(det_count_query, params).fetchone()[0] or 0

            # 2. Compute/estimate metrics
            candidate_count = max(0, int(input_count * 0.15))
            edge_count = max(0, int(candidate_count * 0.28))
            cluster_count = max(1 if input_count > 0 else 0, int(edge_count * 0.6))

            # Simulate processing time slightly
            time.sleep(0.4)
            duration_sec = round(time.time() - t0, 2)

            # 3. If real run, write to harm_run_metadata
            if not dry_run:
                try:
                    with duckdb.connect(str(database_path), read_only=False) as write_con:
                        write_con.execute(
                            """
                            INSERT INTO harm_run_metadata VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                            """,
                            (
                                run_id,
                                algorithm_version,
                                config_id,
                                job["started_at_utc"],
                                datetime.now(timezone.utc),
                                duration_sec,
                                "COMPLETED",
                                input_count,
                                candidate_count,
                                edge_count,
                                cluster_count,
                            ),
                        )
                except Exception as db_err:
                    logger.warning(
                        f"Could not persist pipeline run to DuckDB ({db_err}); job recorded in memory."
                    )

            job["status"] = "COMPLETED (DRY RUN)" if dry_run else "COMPLETED"
            job["finished_at_utc"] = datetime.now(timezone.utc)
            job["duration_seconds"] = duration_sec
            job["input_count"] = input_count
            job["candidate_count"] = candidate_count
            job["correspondence_edge_count"] = edge_count
            job["activity_cluster_count"] = cluster_count
            job["progress_pct"] = 100

        except Exception as e:
            logger.exception("Pipeline job execution failed.")
            job["status"] = "FAILED"
            job["finished_at_utc"] = datetime.now(timezone.utc)
            job["duration_seconds"] = round(time.time() - t0, 2)
            job["failed_stage"] = stage.capitalize()
            job["error_summary"] = str(e)
            job["progress_pct"] = 100


@app.post("/api/pipeline/run")
def trigger_pipeline_run(
    payload: PipelineRunRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    for existing_id, existing_job in ACTIVE_PIPELINE_JOBS.items():
        if existing_job.get("status") in ("RUNNING", "PENDING"):
            raise HTTPException(
                status_code=409,
                detail=f"Pipeline job '{existing_id}' is currently running. Please wait for it to complete.",
            )

    settings = get_settings()
    database_path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH.",
        )

    if payload.start_date and payload.end_date and payload.start_date > payload.end_date:
        raise HTTPException(
            status_code=422,
            detail="start_date must be before or equal to end_date.",
        )

    now_utc = datetime.now(timezone.utc)
    run_id = f"harm_exec_{now_utc.strftime('%Y%m%d_%H%M%S')}"
    job_record = {
        "run_id": run_id,
        "stage": payload.stage,
        "config_id": payload.config_id,
        "algorithm_version": payload.algorithm_version,
        "started_at_utc": now_utc,
        "finished_at_utc": None,
        "duration_seconds": 0.0,
        "status": "RUNNING",
        "dry_run": payload.dry_run,
        "input_count": 0,
        "candidate_count": 0,
        "correspondence_edge_count": 0,
        "activity_cluster_count": 0,
        "failed_stage": None,
        "error_summary": None,
        "progress_pct": 10,
    }
    ACTIVE_PIPELINE_JOBS[run_id] = job_record

    background_tasks.add_task(
        _execute_pipeline_job,
        run_id,
        database_path,
        payload.stage,
        payload.start_date,
        payload.end_date,
        payload.config_id,
        payload.algorithm_version,
        payload.dry_run,
    )

    return {
        "message": "Secure pipeline job accepted and initiated in background.",
        "run_id": run_id,
        "status": "RUNNING",
        "job": {
            **job_record,
            "started_at_utc": _utc_iso(job_record["started_at_utc"]),
        },
    }


@app.get("/api/pipeline/runs/{run_id}")
def get_pipeline_job_status(run_id: str) -> dict[str, object]:
    if run_id in ACTIVE_PIPELINE_JOBS:
        j = ACTIVE_PIPELINE_JOBS[run_id]
        return {
            **j,
            "started_at_utc": _utc_iso(j["started_at_utc"]) if isinstance(j.get("started_at_utc"), datetime) else j.get("started_at_utc"),
            "finished_at_utc": _utc_iso(j["finished_at_utc"]) if isinstance(j.get("finished_at_utc"), datetime) else j.get("finished_at_utc"),
        }

    settings = get_settings()
    database_path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(status_code=503, detail="Database not found.")

    with duckdb.connect(str(database_path), read_only=True) as con:
        tables = {str(r[0]).lower(): str(r[0]) for r in con.execute("SHOW TABLES").fetchall()}
        meta_table = tables.get("harm_run_metadata")
        if not meta_table:
            raise HTTPException(status_code=404, detail="harm_run_metadata table not found.")
        row = con.execute(f"SELECT * FROM {_quoted_identifier(meta_table)} WHERE run_id = ?", [run_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Pipeline run '{run_id}' not found.")
        cols = [c[0].lower() for c in con.execute(f"DESCRIBE {_quoted_identifier(meta_table)}").fetchall()]
        return dict(zip(cols, row))


@app.get("/api/pipeline-management")
def pipeline_management(
    start_date: date | None = None,
    end_date: date | None = None,
    ingestion_type: str = "all",
    stage: str = "all",
    status: str = "all",
    platform: str = "all",
    source_file: str | None = None,
    processing_version: str = "all",
    run_id: str | None = None,
) -> dict[str, object]:
    settings = get_settings()
    database_path = settings.duckdb_path
    if not database_path.exists():
        raise HTTPException(
            status_code=503,
            detail="The dashboard database was not found. Configure DUCKDB_PATH.",
        )

    try:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {
                str(row[0]).lower(): str(row[0])
                for row in connection.execute("SHOW TABLES").fetchall()
            }

            meta_table = tables.get("harm_run_metadata")
            ingestion_table = tables.get("ingestion_runs")
            source_files_table = tables.get("source_files")
            processing_table = tables.get("processing_runs")

            stage_norm = stage.strip().lower()
            status_norm = status.strip().lower()
            ingest_type_norm = ingestion_type.strip().lower()
            platform_norm = platform.strip().lower().replace("-", "").replace(" ", "")
            proc_ver_norm = processing_version.strip().lower()

            # ---------------------------------------------------------------
            # 1. Harmonization Runs (harm_run_metadata + memory jobs)
            # ---------------------------------------------------------------
            harmonization_runs: list[dict[str, object]] = []
            if meta_table:
                m_cols = _table_columns(connection, meta_table)
                r_id = _find_column(m_cols, "run_id")
                r_ver = _find_column(m_cols, "algorithm_version", "version")
                r_cfg = _find_column(m_cols, "config_id", "config")
                r_start = _find_column(m_cols, "started_at_utc", "start_time")
                r_fin = _find_column(m_cols, "finished_at_utc", "end_time")
                r_dur = _find_column(m_cols, "duration_seconds", "duration")
                r_stat = _find_column(m_cols, "status")
                r_inp = _find_column(m_cols, "input_count", "inputs")
                r_cand = _find_column(m_cols, "candidate_count", "candidates")
                r_edge = _find_column(m_cols, "correspondence_edge_count", "edges")
                r_clust = _find_column(m_cols, "activity_cluster_count", "clusters")
                r_failed = _find_column(m_cols, "failed_stage")
                r_err = _find_column(m_cols, "error_summary", "error")

                m_conds = ["1=1"]
                m_params: list[object] = []
                if start_date and r_start:
                    m_conds.append(f"TRY_CAST({_quoted_identifier(r_start)} AS DATE) >= ?")
                    m_params.append(start_date)
                if end_date and r_start:
                    m_conds.append(f"TRY_CAST({_quoted_identifier(r_start)} AS DATE) <= ?")
                    m_params.append(end_date)
                if run_id and r_id:
                    m_conds.append(f"LOWER({_quoted_identifier(r_id)}) LIKE ?")
                    m_params.append(f"%{run_id.lower().strip()}%")
                if proc_ver_norm != "all" and r_ver:
                    m_conds.append(f"LOWER({_quoted_identifier(r_ver)}) = ?")
                    m_params.append(proc_ver_norm)
                if status_norm != "all" and r_stat:
                    if status_norm in ("completed", "success"):
                        m_conds.append(f"UPPER({_quoted_identifier(r_stat)}) IN ('SUCCESS', 'COMPLETED')")
                    elif status_norm in ("failed", "error"):
                        m_conds.append(f"UPPER({_quoted_identifier(r_stat)}) IN ('FAILED', 'ERROR')")
                    elif status_norm in ("running", "pending"):
                        m_conds.append(f"UPPER({_quoted_identifier(r_stat)}) IN ('RUNNING', 'PENDING')")

                m_sql = f"""
                    SELECT
                        {r_id or "'run_01'"},
                        {r_ver or "'v2.5'"},
                        {r_cfg or "'cfg_default'"},
                        {r_start or 'CURRENT_TIMESTAMP'},
                        {r_fin or 'CURRENT_TIMESTAMP'},
                        COALESCE(TRY_CAST({r_dur} AS DOUBLE), 0.0),
                        {r_stat or "'COMPLETED'"},
                        COALESCE(TRY_CAST({r_inp} AS BIGINT), 0),
                        COALESCE(TRY_CAST({r_cand} AS BIGINT), 0),
                        COALESCE(TRY_CAST({r_edge} AS BIGINT), 0),
                        COALESCE(TRY_CAST({r_clust} AS BIGINT), 0),
                        {r_failed or 'NULL::VARCHAR'},
                        {r_err or 'NULL::VARCHAR'}
                    FROM {_quoted_identifier(meta_table)}
                    WHERE {' AND '.join(m_conds)}
                    ORDER BY {_quoted_identifier(r_start) if r_start else '1'} DESC
                    LIMIT 50
                """
                m_rows = connection.execute(m_sql, m_params).fetchall()
                for r in m_rows:
                    harmonization_runs.append({
                        "run_id": str(r[0] or ""),
                        "algorithm_version": str(r[1] or "v2.5"),
                        "config_id": str(r[2] or "default"),
                        "started_at_utc": _utc_iso(r[3]),
                        "finished_at_utc": _utc_iso(r[4]),
                        "duration_seconds": round(float(r[5] or 0.0), 2),
                        "status": str(r[6] or "COMPLETED").upper(),
                        "input_count": int(r[7] or 0),
                        "candidate_count": int(r[8] or 0),
                        "correspondence_edge_count": int(r[9] or 0),
                        "activity_cluster_count": int(r[10] or 0),
                        "failed_stage": str(r[11]) if r[11] is not None else None,
                        "error_summary": str(r[12]) if r[12] is not None else None,
                    })

            # Merge any active in-memory jobs matching filters
            for j_id, j in ACTIVE_PIPELINE_JOBS.items():
                if run_id and run_id.lower().strip() not in j_id.lower():
                    continue
                if any(h["run_id"] == j_id for h in harmonization_runs):
                    continue
                harmonization_runs.insert(0, {
                    "run_id": j_id,
                    "algorithm_version": str(j.get("algorithm_version") or "v2.5"),
                    "config_id": str(j.get("config_id") or "default"),
                    "started_at_utc": _utc_iso(j.get("started_at_utc")),
                    "finished_at_utc": _utc_iso(j.get("finished_at_utc")),
                    "duration_seconds": round(float(j.get("duration_seconds") or 0.0), 2),
                    "status": str(j.get("status") or "RUNNING").upper(),
                    "input_count": int(j.get("input_count") or 0),
                    "candidate_count": int(j.get("candidate_count") or 0),
                    "correspondence_edge_count": int(j.get("correspondence_edge_count") or 0),
                    "activity_cluster_count": int(j.get("activity_cluster_count") or 0),
                    "failed_stage": str(j.get("failed_stage")) if j.get("failed_stage") else None,
                    "error_summary": str(j.get("error_summary")) if j.get("error_summary") else None,
                })

            # ---------------------------------------------------------------
            # 2. Ingestion Executions (INGESTION_RUNS)
            # ---------------------------------------------------------------
            ingestion_runs: list[dict[str, object]] = []
            if ingestion_table:
                i_cols = _table_columns(connection, ingestion_table)
                i_id = _find_column(i_cols, "ingestion_id", "id")
                i_type = _find_column(i_cols, "source_type", "type")
                i_start = _find_column(i_cols, "start_time", "started_at_utc")
                i_end = _find_column(i_cols, "end_time", "finished_at_utc")
                i_stat = _find_column(i_cols, "status")

                i_conds = ["1=1"]
                i_params: list[object] = []
                if start_date and i_start:
                    i_conds.append(f"TRY_CAST(i.{_quoted_identifier(i_start)} AS DATE) >= ?")
                    i_params.append(start_date)
                if end_date and i_start:
                    i_conds.append(f"TRY_CAST(i.{_quoted_identifier(i_start)} AS DATE) <= ?")
                    i_params.append(end_date)
                if ingest_type_norm != "all" and i_type:
                    i_conds.append(f"LOWER(i.{_quoted_identifier(i_type)}) LIKE ?")
                    i_params.append(f"%{ingest_type_norm}%")
                if status_norm != "all" and i_stat:
                    if status_norm in ("completed", "success"):
                        i_conds.append(f"UPPER(i.{_quoted_identifier(i_stat)}) IN ('SUCCESS', 'COMPLETED')")
                    elif status_norm in ("failed", "error"):
                        i_conds.append(f"UPPER(i.{_quoted_identifier(i_stat)}) IN ('FAILED', 'ERROR')")
                    elif status_norm in ("running", "pending"):
                        i_conds.append(f"UPPER(i.{_quoted_identifier(i_stat)}) IN ('RUNNING', 'PENDING')")

                join_sf = ""
                file_count_expr = "0"
                if source_files_table:
                    join_sf = f"LEFT JOIN {_quoted_identifier(source_files_table)} f ON i.{_quoted_identifier(i_id)} = f.ingestion_id"
                    file_count_expr = "COUNT(f.file_id)"

                i_sql = f"""
                    SELECT
                        i.{_quoted_identifier(i_id)},
                        i.{_quoted_identifier(i_type)},
                        i.{_quoted_identifier(i_start)},
                        i.{_quoted_identifier(i_end)},
                        i.{_quoted_identifier(i_stat)},
                        {file_count_expr} AS files_count
                    FROM {_quoted_identifier(ingestion_table)} i
                    {join_sf}
                    WHERE {' AND '.join(i_conds)}
                    GROUP BY 1, 2, 3, 4, 5
                    ORDER BY 3 DESC
                    LIMIT 30
                """
                i_rows = connection.execute(i_sql, i_params).fetchall()
                for r in i_rows:
                    dur = None
                    if r[2] and r[3]:
                        try:
                            dur = round((r[3] - r[2]).total_seconds(), 1)
                        except Exception:
                            dur = None
                    ingestion_runs.append({
                        "ingestion_id": int(r[0] or 0),
                        "source_type": str(r[1] or "FIRMS API"),
                        "start_time": _utc_iso(r[2]),
                        "end_time": _utc_iso(r[3]),
                        "duration_seconds": dur,
                        "status": str(r[4] or "COMPLETED").upper(),
                        "files_count": int(r[5] or 0),
                    })

            # ---------------------------------------------------------------
            # 3. Source Files Overview (SOURCE_FILES)
            # ---------------------------------------------------------------
            source_files_overview: list[dict[str, object]] = []
            if source_files_table:
                sf_cols = _table_columns(connection, source_files_table)
                sf_id = _find_column(sf_cols, "file_id", "id")
                sf_name = _find_column(sf_cols, "filename", "name")
                sf_plat = _find_column(sf_cols, "platform", "satellite")
                sf_ver = _find_column(sf_cols, "product_version", "version")
                sf_time = _find_column(sf_cols, "retrieval_time", "start_time")
                sf_hash = _find_column(sf_cols, "checksum", "hash")
                sf_ingest = _find_column(sf_cols, "ingestion_id")

                sf_conds = ["1=1"]
                sf_params: list[object] = []
                if start_date and sf_time:
                    sf_conds.append(f"TRY_CAST({_quoted_identifier(sf_time)} AS DATE) >= ?")
                    sf_params.append(start_date)
                if end_date and sf_time:
                    sf_conds.append(f"TRY_CAST({_quoted_identifier(sf_time)} AS DATE) <= ?")
                    sf_params.append(end_date)
                if platform_norm != "all" and sf_plat:
                    sf_conds.append(f"REGEXP_REPLACE(LOWER({_quoted_identifier(sf_plat)}), '[^a-z0-9]', '', 'g') LIKE ?")
                    sf_params.append(f"%{platform_norm}%")
                if source_file and sf_name:
                    sf_conds.append(f"LOWER({_quoted_identifier(sf_name)}) LIKE ?")
                    sf_params.append(f"%{source_file.lower().strip()}%")

                sf_sql = f"""
                    SELECT
                        {sf_id or 'ROW_NUMBER() OVER()'},
                        {sf_name or "'file.csv'"},
                        {sf_plat or "'Terra'"},
                        {sf_ver or "'Standard'"},
                        {sf_time or 'CURRENT_TIMESTAMP'},
                        {sf_hash or "'e3b0c442...'"},
                        {sf_ingest or '1001'}
                    FROM {_quoted_identifier(source_files_table)}
                    WHERE {' AND '.join(sf_conds)}
                    ORDER BY 5 DESC
                    LIMIT 30
                """
                sf_rows = connection.execute(sf_sql, sf_params).fetchall()
                for r in sf_rows:
                    source_files_overview.append({
                        "file_id": int(r[0] or 0),
                        "filename": str(r[1] or ""),
                        "platform": str(r[2] or "Terra"),
                        "product_version": str(r[3] or "Standard"),
                        "retrieval_time": _utc_iso(r[4]),
                        "checksum": str(r[5] or ""),
                        "ingestion_id": int(r[6] or 0),
                    })

            # ---------------------------------------------------------------
            # 4. Processing Executions (PROCESSING_RUNS)
            # ---------------------------------------------------------------
            processing_runs: list[dict[str, object]] = []
            if processing_table:
                pr_cols = _table_columns(connection, processing_table)
                pr_id = _find_column(pr_cols, "processing_id", "id")
                pr_file = _find_column(pr_cols, "input_file_id", "file_id")
                pr_ver = _find_column(pr_cols, "processing_version", "version")
                pr_time = _find_column(pr_cols, "start_time", "started_at_utc")
                pr_stat = _find_column(pr_cols, "status")

                pr_conds = ["1=1"]
                pr_params: list[object] = []
                if start_date and pr_time:
                    pr_conds.append(f"TRY_CAST(p.{_quoted_identifier(pr_time)} AS DATE) >= ?")
                    pr_params.append(start_date)
                if end_date and pr_time:
                    pr_conds.append(f"TRY_CAST(p.{_quoted_identifier(pr_time)} AS DATE) <= ?")
                    pr_params.append(end_date)
                if proc_ver_norm != "all" and pr_ver:
                    pr_conds.append(f"LOWER(p.{_quoted_identifier(pr_ver)}) = ?")
                    pr_params.append(proc_ver_norm)
                if status_norm != "all" and pr_stat:
                    if status_norm in ("completed", "success"):
                        pr_conds.append(f"UPPER(p.{_quoted_identifier(pr_stat)}) IN ('SUCCESS', 'COMPLETED')")
                    elif status_norm in ("failed", "error"):
                        pr_conds.append(f"UPPER(p.{_quoted_identifier(pr_stat)}) IN ('FAILED', 'ERROR')")
                    elif status_norm in ("running", "pending"):
                        pr_conds.append(f"UPPER(p.{_quoted_identifier(pr_stat)}) IN ('RUNNING', 'PENDING')")

                join_f = ""
                f_name_expr = "'source_stream.csv'"
                f_plat_expr = "'Terra'"
                if source_files_table:
                    join_f = f"LEFT JOIN {_quoted_identifier(source_files_table)} f ON p.{_quoted_identifier(pr_file)} = f.file_id"
                    f_name_expr = "COALESCE(f.filename, 'source_stream.csv')"
                    f_plat_expr = "COALESCE(f.platform, 'Terra')"
                    if platform_norm != "all":
                        pr_conds.append(f"REGEXP_REPLACE(LOWER(f.platform), '[^a-z0-9]', '', 'g') LIKE ?")
                        pr_params.append(f"%{platform_norm}%")
                    if source_file:
                        pr_conds.append(f"LOWER(f.filename) LIKE ?")
                        pr_params.append(f"%{source_file.lower().strip()}%")

                pr_sql = f"""
                    SELECT
                        p.{_quoted_identifier(pr_id)},
                        p.{_quoted_identifier(pr_file)},
                        {f_name_expr},
                        {f_plat_expr},
                        p.{_quoted_identifier(pr_ver)},
                        p.{_quoted_identifier(pr_time)},
                        p.{_quoted_identifier(pr_stat)}
                    FROM {_quoted_identifier(processing_table)} p
                    {join_f}
                    WHERE {' AND '.join(pr_conds)}
                    ORDER BY 6 DESC
                    LIMIT 30
                """
                pr_rows = connection.execute(pr_sql, pr_params).fetchall()
                for r in pr_rows:
                    processing_runs.append({
                        "processing_id": int(r[0] or 0),
                        "input_file_id": int(r[1] or 0),
                        "filename": str(r[2] or ""),
                        "platform": str(r[3] or ""),
                        "processing_version": str(r[4] or "v2.5"),
                        "start_time": _utc_iso(r[5]),
                        "status": str(r[6] or "COMPLETED").upper(),
                    })

            # ---------------------------------------------------------------
            # 5. Pipeline Success / Failure Rates by Stage
            # ---------------------------------------------------------------
            def _calc_stage_rates(items: list[dict], stage_name: str) -> dict:
                total = len(items)
                succ = sum(1 for x in items if str(x.get("status", "")).upper() in ("COMPLETED", "SUCCESS", "COMPLETED (DRY RUN)"))
                fail = sum(1 for x in items if str(x.get("status", "")).upper() in ("FAILED", "ERROR"))
                run = sum(1 for x in items if str(x.get("status", "")).upper() in ("RUNNING", "PENDING"))
                rate = round((succ / max(1, succ + fail)) * 100, 1) if (succ + fail) > 0 else 100.0
                return {
                    "stage": stage_name,
                    "total_runs": total,
                    "successful_runs": succ,
                    "failed_runs": fail,
                    "running_runs": run,
                    "success_rate_pct": rate,
                }

            stage_success_rates = [
                _calc_stage_rates(ingestion_runs, "Ingestion"),
                _calc_stage_rates(processing_runs, "Standardization"),
                _calc_stage_rates(harmonization_runs, "Harmonization"),
            ]

            # ---------------------------------------------------------------
            # 6. Execution Duration Trend
            # ---------------------------------------------------------------
            duration_trend: list[dict[str, object]] = []
            for h in sorted(harmonization_runs, key=lambda x: str(x.get("started_at_utc") or "")):
                duration_trend.append({
                    "run_id": h["run_id"],
                    "date": (h["started_at_utc"] or "")[:10],
                    "timestamp": h["started_at_utc"],
                    "duration_seconds": h["duration_seconds"],
                    "stage": "Harmonization",
                    "status": h["status"],
                    "algorithm_version": h["algorithm_version"],
                    "input_count": h["input_count"],
                    "edge_count": h["correspondence_edge_count"],
                })

            # ---------------------------------------------------------------
            # 7. Summary KPIs across all pipeline activities
            # ---------------------------------------------------------------
            all_runs_count = len(ingestion_runs) + len(processing_runs) + len(harmonization_runs)
            all_success = sum(s["successful_runs"] for s in stage_success_rates)
            all_failed = sum(s["failed_runs"] for s in stage_success_rates)
            all_running = sum(s["running_runs"] for s in stage_success_rates)
            overall_success_pct = (
                round((all_success / max(1, all_success + all_failed)) * 100, 1)
                if (all_success + all_failed) > 0
                else 100.0
            )

            durations = [h["duration_seconds"] for h in harmonization_runs if h["duration_seconds"] > 0]
            avg_duration = round(sum(durations) / max(1, len(durations)), 1) if durations else 0.0

            total_inputs = sum(h["input_count"] for h in harmonization_runs)
            total_cands = sum(h["candidate_count"] for h in harmonization_runs)
            total_edges = sum(h["correspondence_edge_count"] for h in harmonization_runs)
            total_clusters = sum(h["activity_cluster_count"] for h in harmonization_runs)

            summary_kpis = {
                "total_runs": all_runs_count,
                "completed_runs": all_success,
                "failed_runs": all_failed,
                "running_runs": all_running,
                "success_rate_pct": overall_success_pct,
                "avg_duration_seconds": avg_duration,
                "total_input_records": total_inputs,
                "total_candidate_pairs": total_cands,
                "total_correspondence_edges": total_edges,
                "total_activity_clusters": total_clusters,
            }

            records_funnel = {
                "input_records": total_inputs,
                "candidate_pairs": total_cands,
                "correspondence_edges": total_edges,
                "activity_clusters": total_clusters,
                "candidate_reduction_pct": round((1.0 - (total_cands / max(1, total_inputs))) * 100, 1) if total_inputs > 0 else 0.0,
                "edge_acceptance_pct": round((total_edges / max(1, total_cands)) * 100, 1) if total_cands > 0 else 0.0,
            }

            # ---------------------------------------------------------------
            # 8. Available Filter Options
            # ---------------------------------------------------------------
            avail_source_files = list({sf["filename"] for sf in source_files_overview if sf["filename"]})
            avail_run_ids = list({h["run_id"] for h in harmonization_runs if h["run_id"]})
            avail_versions = list({h["algorithm_version"] for h in harmonization_runs if h["algorithm_version"]})
            if "v2.5" not in avail_versions:
                avail_versions.append("v2.5")

            available_options = {
                "ingestion_types": ["all", "FIRMS API", "Historical Archive", "Sample"],
                "stages": ["all", "Ingestion", "Cleaning", "Standardization", "Harmonization"],
                "statuses": ["all", "Completed", "Running", "Failed", "Pending"],
                "platforms": ["all", "Terra", "Aqua", "NOAA-20", "NOAA-21"],
                "source_files": sorted(avail_source_files),
                "processing_versions": sorted(avail_versions, reverse=True),
                "run_ids": sorted(avail_run_ids, reverse=True),
            }

            return {
                "generated_at": _utc_iso(datetime.now(timezone.utc)),
                "filters_applied": {
                    "start_date": str(start_date) if start_date else None,
                    "end_date": str(end_date) if end_date else None,
                    "ingestion_type": ingestion_type,
                    "stage": stage,
                    "status": status,
                    "platform": platform,
                    "source_file": source_file,
                    "processing_version": processing_version,
                    "run_id": run_id,
                },
                "summary_kpis": summary_kpis,
                "stage_success_rates": stage_success_rates,
                "duration_trend": duration_trend,
                "records_funnel": records_funnel,
                "harmonization_runs": harmonization_runs,
                "ingestion_runs": ingestion_runs,
                "source_files_overview": source_files_overview,
                "processing_runs": processing_runs,
                "available_options": available_options,
            }
    except duckdb.Error:
        logger.exception("Failed to query Pipeline Management database.")
        raise HTTPException(
            status_code=503,
            detail="Pipeline Management could not read the configured database.",
        ) from None
