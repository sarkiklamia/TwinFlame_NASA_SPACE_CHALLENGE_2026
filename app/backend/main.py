"""Read-only API endpoints for the TwinFlame dashboard."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

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
    platform: Platform = "all",
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
        "retrieved_at_utc",
        "retrieved_at",
        "retrieval_timestamp_utc",
        "retrieval_timestamp",
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
    platform: Platform = "all",
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
            sensor_column = _find_column(columns, "instrument", "sensor")
            confidence_column = _find_column(
                columns, "native_confidence", "confidence", "confidence_level"
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

            if platform != "all":
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
                    "noaa20": "%NOAA20%",
                    "noaa21": "%NOAA21%",
                }[platform]
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
