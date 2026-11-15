
-- ============================================================
-- 08_categorical_consistency.sql
-- Purpose: Inspect categorical values and source consistency.
-- Read-only: source files are never modified.
-- ============================================================

CREATE OR REPLACE TEMP TABLE categorical_data AS

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    instrument,
    confidence,
    CAST(version AS VARCHAR) AS version,
    daynight
FROM read_csv_auto(
    'data/raw/sample/*.csv',
    union_by_name = true
)

UNION ALL

SELECT
    'FIRMS_API' AS source,
    satellite,
    instrument,
    confidence,
    CAST(version AS VARCHAR) AS version,
    daynight
FROM read_parquet(
    'data/raw/api/**/*.parquet',
    union_by_name = true
);


-- 1. Satellite and instrument combinations
SELECT
    source,
    satellite,
    instrument,
    COUNT(*) AS detections
FROM categorical_data
GROUP BY source, satellite, instrument
ORDER BY source, satellite, instrument;


-- 2. Confidence value distributions
SELECT
    source,
    satellite,
    confidence,
    COUNT(*) AS detections
FROM categorical_data
GROUP BY source, satellite, confidence
ORDER BY source, satellite, detections DESC;


-- 3. Product version distributions
SELECT
    source,
    satellite,
    version,
    COUNT(*) AS detections
FROM categorical_data
GROUP BY source, satellite, version
ORDER BY source, satellite, version;


-- 4. Day/night value distributions
SELECT
    source,
    satellite,
    daynight,
    COUNT(*) AS detections
FROM categorical_data
GROUP BY source, satellite, daynight
ORDER BY source, satellite, daynight;


-- 5. Missing or empty categorical values
SELECT
    source,
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (
        WHERE satellite IS NULL OR TRIM(satellite) = ''
    ) AS missing_satellite,
    COUNT(*) FILTER (
        WHERE instrument IS NULL OR TRIM(instrument) = ''
    ) AS missing_instrument,
    COUNT(*) FILTER (
        WHERE confidence IS NULL OR TRIM(confidence) = ''
    ) AS missing_confidence,
    COUNT(*) FILTER (
        WHERE version IS NULL OR TRIM(version) = ''
    ) AS missing_version,
    COUNT(*) FILTER (
        WHERE daynight IS NULL OR TRIM(daynight) = ''
    ) AS missing_daynight
FROM categorical_data
GROUP BY source
ORDER BY source;
