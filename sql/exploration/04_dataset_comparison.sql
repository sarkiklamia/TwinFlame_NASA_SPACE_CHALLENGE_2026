
-- ============================================================
-- 04_dataset_comparison.sql
-- Purpose: Detailed comparison of C2 sample and FIRMS API data
-- Read-only exploration. Raw files are never modified.
-- ============================================================

-- Load each raw dataset once.
CREATE OR REPLACE TEMP TABLE sample_data AS
SELECT *
FROM read_csv_auto(
    'data/raw/sample/*.csv',
    union_by_name = true
);

CREATE OR REPLACE TEMP TABLE api_data AS
SELECT *
FROM read_parquet(
    'data/raw/api/**/*.parquet',
    union_by_name = true
);


-- RESULT 1: SCHEMA COMPARISON
-- Shows whether each column exists and its detected data type.

WITH sample_schema AS (
    SELECT name AS column_name, type AS sample_type
    FROM pragma_table_info('sample_data')
),
api_schema AS (
    SELECT name AS column_name, type AS api_type
    FROM pragma_table_info('api_data')
)
SELECT
    COALESCE(s.column_name, a.column_name) AS column_name,
    s.sample_type,
    a.api_type,
    CASE
        WHEN s.column_name IS NULL THEN 'API_ONLY'
        WHEN a.column_name IS NULL THEN 'C2_ONLY'
        WHEN s.sample_type <> a.api_type THEN 'TYPE_DIFFERENCE'
        ELSE 'COMMON'
    END AS comparison
FROM sample_schema s
FULL OUTER JOIN api_schema a
    ON s.column_name = a.column_name
ORDER BY comparison, column_name;


-- RESULT 2: COMMON NUMERIC COLUMNS
-- Compares record counts and value ranges.
-- Date ranges are included separately in this result.

SELECT
    'C2_SAMPLE' AS source,
    'latitude' AS column_name,
    COUNT(latitude) AS non_null_count,
    MIN(latitude) AS minimum,
    MAX(latitude) AS maximum,
    AVG(latitude) AS average
FROM sample_data

UNION ALL
SELECT 'FIRMS_API', 'latitude',
    COUNT(latitude), MIN(latitude), MAX(latitude), AVG(latitude)
FROM api_data

UNION ALL
SELECT 'C2_SAMPLE', 'longitude',
    COUNT(longitude), MIN(longitude), MAX(longitude), AVG(longitude)
FROM sample_data

UNION ALL
SELECT 'FIRMS_API', 'longitude',
    COUNT(longitude), MIN(longitude), MAX(longitude), AVG(longitude)
FROM api_data

UNION ALL
SELECT 'C2_SAMPLE', 'brightness',
    COUNT(brightness), MIN(brightness), MAX(brightness), AVG(brightness)
FROM sample_data

UNION ALL
SELECT 'FIRMS_API', 'brightness',
    COUNT(brightness), MIN(brightness), MAX(brightness), AVG(brightness)
FROM api_data

UNION ALL
SELECT 'C2_SAMPLE', 'bright_t31',
    COUNT(bright_t31), MIN(bright_t31), MAX(bright_t31), AVG(bright_t31)
FROM sample_data

UNION ALL
SELECT 'FIRMS_API', 'bright_t31',
    COUNT(bright_t31), MIN(bright_t31), MAX(bright_t31), AVG(bright_t31)
FROM api_data

UNION ALL
SELECT 'C2_SAMPLE', 'frp',
    COUNT(frp), MIN(frp), MAX(frp), AVG(frp)
FROM sample_data

UNION ALL
SELECT 'FIRMS_API', 'frp',
    COUNT(frp), MIN(frp), MAX(frp), AVG(frp)
FROM api_data

UNION ALL
SELECT 'C2_SAMPLE', 'scan',
    COUNT(scan), MIN(scan), MAX(scan), AVG(scan)
FROM sample_data

UNION ALL
SELECT 'FIRMS_API', 'scan',
    COUNT(scan), MIN(scan), MAX(scan), AVG(scan)
FROM api_data

UNION ALL
SELECT 'C2_SAMPLE', 'track',
    COUNT(track), MIN(track), MAX(track), AVG(track)
FROM sample_data

UNION ALL
SELECT 'FIRMS_API', 'track',
    COUNT(track), MIN(track), MAX(track), AVG(track)
FROM api_data

UNION ALL
SELECT 'C2_SAMPLE', 'acq_time',
    COUNT(acq_time),
    MIN(acq_time)::DOUBLE,
    MAX(acq_time)::DOUBLE,
    AVG(acq_time::DOUBLE)
FROM sample_data

UNION ALL
SELECT 'FIRMS_API', 'acq_time',
    COUNT(acq_time),
    MIN(acq_time)::DOUBLE,
    MAX(acq_time)::DOUBLE,
    AVG(acq_time::DOUBLE)
FROM api_data

ORDER BY source, column_name;


-- RESULT 3: SOURCE-SPECIFIC COLUMNS
-- C2-only: type
-- API-only: bright_ti4 and bright_ti5
-- Brightness values are summarized by satellite.

SELECT
    'C2_SAMPLE' AS source,
    CAST(satellite AS VARCHAR) AS satellite,
    'type' AS column_name,
    COUNT(*) AS record_count,
    COUNT(type) AS non_null_count,
    COUNT(DISTINCT type) AS distinct_values,
    CAST(MIN(type) AS VARCHAR) AS minimum,
    CAST(MAX(type) AS VARCHAR) AS maximum,
    CAST(type AS VARCHAR) AS value
FROM sample_data
GROUP BY satellite, type

UNION ALL

SELECT
    'FIRMS_API',
    CAST(satellite AS VARCHAR),
    'bright_ti4',
    COUNT(*),
    COUNT(bright_ti4),
    COUNT(DISTINCT bright_ti4),
    CAST(MIN(bright_ti4) AS VARCHAR),
    CAST(MAX(bright_ti4) AS VARCHAR),
    NULL
FROM api_data
GROUP BY satellite

UNION ALL

SELECT
    'FIRMS_API',
    CAST(satellite AS VARCHAR),
    'bright_ti5',
    COUNT(*),
    COUNT(bright_ti5),
    COUNT(DISTINCT bright_ti5),
    CAST(MIN(bright_ti5) AS VARCHAR),
    CAST(MAX(bright_ti5) AS VARCHAR),
    NULL
FROM api_data
GROUP BY satellite

ORDER BY source, satellite, column_name, value;


-- RESULT 4: CATEGORICAL VALUE DISTRIBUTIONS
-- Shows the 15 most frequent values per source, satellite and column.
-- distinct_values reports the full number of distinct values.

WITH categorical_values AS (
    SELECT
        'C2_SAMPLE' AS source,
        CAST(satellite AS VARCHAR) AS satellite,
        'confidence' AS column_name,
        CAST(confidence AS VARCHAR) AS value
    FROM sample_data

    UNION ALL
    SELECT 'FIRMS_API', CAST(satellite AS VARCHAR),
        'confidence', CAST(confidence AS VARCHAR)
    FROM api_data

    UNION ALL
    SELECT 'C2_SAMPLE', CAST(satellite AS VARCHAR),
        'satellite', CAST(satellite AS VARCHAR)
    FROM sample_data

    UNION ALL
    SELECT 'FIRMS_API', CAST(satellite AS VARCHAR),
        'satellite', CAST(satellite AS VARCHAR)
    FROM api_data

    UNION ALL
    SELECT 'C2_SAMPLE', CAST(satellite AS VARCHAR),
        'instrument', CAST(instrument AS VARCHAR)
    FROM sample_data

    UNION ALL
    SELECT 'FIRMS_API', CAST(satellite AS VARCHAR),
        'instrument', CAST(instrument AS VARCHAR)
    FROM api_data

    UNION ALL
    SELECT 'C2_SAMPLE', CAST(satellite AS VARCHAR),
        'daynight', CAST(daynight AS VARCHAR)
    FROM sample_data

    UNION ALL
    SELECT 'FIRMS_API', CAST(satellite AS VARCHAR),
        'daynight', CAST(daynight AS VARCHAR)
    FROM api_data

    UNION ALL
    SELECT 'C2_SAMPLE', CAST(satellite AS VARCHAR),
        'version', CAST(version AS VARCHAR)
    FROM sample_data

    UNION ALL
    SELECT 'FIRMS_API', CAST(satellite AS VARCHAR),
        'version', CAST(version AS VARCHAR)
    FROM api_data
),
value_counts AS (
    SELECT
        source,
        satellite,
        column_name,
        value,
        COUNT(*) AS record_count
    FROM categorical_values
    GROUP BY source, satellite, column_name, value
),
ranked_values AS (
    SELECT
        *,
        COUNT(*) OVER (
            PARTITION BY source, satellite, column_name
        ) AS distinct_values,
        ROW_NUMBER() OVER (
            PARTITION BY source, satellite, column_name
            ORDER BY record_count DESC, value
        ) AS value_rank
    FROM value_counts
)
SELECT
    source,
    satellite,
    column_name,
    value,
    record_count,
    distinct_values
FROM ranked_values
WHERE value_rank <= 15
ORDER BY source, satellite, column_name, value_rank;


-- RESULT 5: BRIGHTNESS AVAILABILITY BY SENSOR
-- Zero means the field exists in the schema but has no populated values.
-- The C2 source does not contain the two VIIRS-specific fields.

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    instrument,
    'brightness' AS column_name,
    COUNT(*) AS total_records,
    COUNT(brightness) AS populated_records
FROM sample_data
GROUP BY satellite, instrument

UNION ALL
SELECT 'C2_SAMPLE', satellite, instrument, 'bright_t31',
    COUNT(*), COUNT(bright_t31)
FROM sample_data
GROUP BY satellite, instrument

UNION ALL
SELECT 'C2_SAMPLE', satellite, instrument, 'bright_ti4',
    COUNT(*), 0
FROM sample_data
GROUP BY satellite, instrument

UNION ALL
SELECT 'C2_SAMPLE', satellite, instrument, 'bright_ti5',
    COUNT(*), 0
FROM sample_data
GROUP BY satellite, instrument

UNION ALL
SELECT 'FIRMS_API', satellite, instrument, 'brightness',
    COUNT(*), COUNT(brightness)
FROM api_data
GROUP BY satellite, instrument

UNION ALL
SELECT 'FIRMS_API', satellite, instrument, 'bright_t31',
    COUNT(*), COUNT(bright_t31)
FROM api_data
GROUP BY satellite, instrument

UNION ALL
SELECT 'FIRMS_API', satellite, instrument, 'bright_ti4',
    COUNT(*), COUNT(bright_ti4)
FROM api_data
GROUP BY satellite, instrument

UNION ALL
SELECT 'FIRMS_API', satellite, instrument, 'bright_ti5',
    COUNT(*), COUNT(bright_ti5)
FROM api_data
GROUP BY satellite, instrument

ORDER BY source, satellite, column_name;
