
-- ============================================================
-- 07_temporal_coverage.sql
-- Purpose: Explore acquisition dates, times, and temporal gaps.
-- Read-only: source files are never modified.
-- ============================================================

CREATE OR REPLACE TEMP TABLE temporal_data AS

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    TRY_CAST(acq_date AS DATE) AS acq_date,
    TRY_CAST(acq_time AS BIGINT) AS acq_time
FROM read_csv_auto(
    'data/raw/sample/*.csv',
    union_by_name = true
)

UNION ALL

SELECT
    'FIRMS_API' AS source,
    satellite,
    TRY_CAST(acq_date AS DATE) AS acq_date,
    TRY_CAST(acq_time AS BIGINT) AS acq_time
FROM read_parquet(
    'data/raw/api/**/*.parquet',
    union_by_name = true
);


-- 1. Date coverage and parsing
SELECT
    source,
    satellite,
    COUNT(*) AS total_rows,
    COUNT(acq_date) AS valid_dates,
    COUNT(*) FILTER (WHERE acq_date IS NULL) AS invalid_dates,
    MIN(acq_date) AS first_date,
    MAX(acq_date) AS last_date,
    COUNT(DISTINCT acq_date) AS distinct_dates
FROM temporal_data
GROUP BY source, satellite
ORDER BY source, satellite;


-- 2. Acquisition time validity (HHMM)
SELECT
    source,
    satellite,
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE acq_time IS NULL) AS null_times,
    COUNT(*) FILTER (
        WHERE acq_time < 0
           OR acq_time > 2359
           OR acq_time % 100 > 59
    ) AS invalid_hhmm,
    MIN(acq_time) AS min_raw_time,
    MAX(acq_time) AS max_raw_time
FROM temporal_data
GROUP BY source, satellite
ORDER BY source, satellite;


-- 3. Detections per acquisition date
SELECT
    source,
    satellite,
    acq_date,
    COUNT(*) AS detections
FROM temporal_data
WHERE acq_date IS NOT NULL
GROUP BY source, satellite, acq_date
ORDER BY source, satellite, acq_date;


-- 4. Missing calendar dates within each source/satellite range
WITH date_ranges AS (
    SELECT
        source,
        satellite,
        MIN(acq_date) AS first_date,
        MAX(acq_date) AS last_date
    FROM temporal_data
    WHERE acq_date IS NOT NULL
    GROUP BY source, satellite
),
calendar AS (
    SELECT
        r.source,
        r.satellite,
        CAST(d.day AS DATE) AS calendar_date
    FROM date_ranges r,
    LATERAL generate_series(
        r.first_date,
        r.last_date,
        INTERVAL 1 DAY
    ) AS d(day)
),
observed_dates AS (
    SELECT DISTINCT
        source,
        satellite,
        acq_date
    FROM temporal_data
    WHERE acq_date IS NOT NULL
)
SELECT
    c.source,
    c.satellite,
    COUNT(*) AS missing_dates
FROM calendar c
LEFT JOIN observed_dates o
    ON c.source = o.source
   AND c.satellite = o.satellite
   AND c.calendar_date = o.acq_date
WHERE o.acq_date IS NULL
GROUP BY c.source, c.satellite
ORDER BY c.source, c.satellite;


-- 5. Detection distribution by acquisition hour
SELECT
    source,
    satellite,
    FLOOR(acq_time / 100) AS acquisition_hour,
    COUNT(*) AS detections
FROM temporal_data
WHERE acq_time BETWEEN 0 AND 2359
  AND acq_time % 100 <= 59
GROUP BY source, satellite, acquisition_hour
ORDER BY source, satellite, acquisition_hour;
