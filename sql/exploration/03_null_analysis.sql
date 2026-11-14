
-- ============================================================
-- 03_null_analysis.sql
-- Purpose: Measure NULL values and missing-value percentages
-- Sources: C2 sample CSV and FIRMS API Parquet
-- Read-only exploration
-- ============================================================

-- 1. C2 sample CSV files: NULL analysis by file

WITH sample_data AS (
    SELECT *
    FROM read_csv_auto(
        'data/raw/sample/*.csv',
        union_by_name = true,
        filename = true
    )
),
sample_nulls AS (
    SELECT
        filename,
        v.column_name,
        v.column_value
    FROM sample_data
    CROSS JOIN LATERAL (
        VALUES
            ('latitude',    CAST(latitude AS VARCHAR)),
            ('longitude',   CAST(longitude AS VARCHAR)),
            ('brightness',  CAST(brightness AS VARCHAR)),
            ('scan',        CAST(scan AS VARCHAR)),
            ('track',       CAST(track AS VARCHAR)),
            ('acq_date',    CAST(acq_date AS VARCHAR)),
            ('acq_time',    CAST(acq_time AS VARCHAR)),
            ('satellite',   CAST(satellite AS VARCHAR)),
            ('instrument',  CAST(instrument AS VARCHAR)),
            ('confidence',  CAST(confidence AS VARCHAR)),
            ('version',     CAST(version AS VARCHAR)),
            ('bright_t31',  CAST(bright_t31 AS VARCHAR)),
            ('frp',         CAST(frp AS VARCHAR)),
            ('daynight',    CAST(daynight AS VARCHAR)),
            ('type',        CAST(type AS VARCHAR))
    ) AS v(column_name, column_value)
)
SELECT
    'sample_csv' AS source,
    filename AS source_file,
    column_name,
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (
        WHERE column_value IS NULL
    ) AS null_count,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE column_value IS NULL
        ) / COUNT(*),
        4
    ) AS null_percentage
FROM sample_nulls
GROUP BY filename, column_name

UNION ALL

-- 2. FIRMS API Parquet files: NULL analysis by satellite

SELECT
    'firms_api' AS source,
    satellite AS source_file,
    column_name,
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (
        WHERE column_value IS NULL
    ) AS null_count,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE column_value IS NULL
        ) / COUNT(*),
        4
    ) AS null_percentage
FROM (
    SELECT
        satellite,
        v.column_name,
        v.column_value
    FROM read_parquet(
        'data/raw/api/**/*.parquet',
        union_by_name = true
    )
    CROSS JOIN LATERAL (
        VALUES
            ('latitude',    CAST(latitude AS VARCHAR)),
            ('longitude',   CAST(longitude AS VARCHAR)),
            ('brightness',  CAST(brightness AS VARCHAR)),
            ('bright_t31',  CAST(bright_t31 AS VARCHAR)),
            ('bright_ti4',  CAST(bright_ti4 AS VARCHAR)),
            ('bright_ti5',  CAST(bright_ti5 AS VARCHAR)),
            ('scan',        CAST(scan AS VARCHAR)),
            ('track',       CAST(track AS VARCHAR)),
            ('acq_date',    CAST(acq_date AS VARCHAR)),
            ('acq_time',    CAST(acq_time AS VARCHAR)),
            ('satellite',   CAST(satellite AS VARCHAR)),
            ('instrument',  CAST(instrument AS VARCHAR)),
            ('confidence',  CAST(confidence AS VARCHAR)),
            ('version',     CAST(version AS VARCHAR)),
            ('frp',         CAST(frp AS VARCHAR)),
            ('daynight',    CAST(daynight AS VARCHAR))
    ) AS v(column_name, column_value)
)
GROUP BY satellite, column_name

ORDER BY source, source_file, column_name;
