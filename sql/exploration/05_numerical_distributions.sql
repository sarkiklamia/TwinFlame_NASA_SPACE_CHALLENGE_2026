
-- ============================================================
-- 05_numerical_distributions.sql
-- Purpose: Explore numerical distributions by source and satellite
-- Read-only exploration
-- ============================================================

-- Load each dataset once.
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


-- RESULT 1: BRIGHTNESS
-- Compare brightness distributions by source and satellite.

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    COUNT(brightness) AS populated,
    MIN(brightness) AS minimum,
    QUANTILE_CONT(brightness, 0.01) AS p01,
    QUANTILE_CONT(brightness, 0.25) AS p25,
    QUANTILE_CONT(brightness, 0.50) AS median,
    QUANTILE_CONT(brightness, 0.75) AS p75,
    QUANTILE_CONT(brightness, 0.99) AS p99,
    MAX(brightness) AS maximum,
    AVG(brightness) AS average,
    STDDEV_SAMP(brightness) AS stddev,
    COUNT(*) FILTER (WHERE brightness = 0) AS zero_count,
    COUNT(*) FILTER (WHERE brightness < 0) AS negative_count
FROM sample_data
GROUP BY satellite

UNION ALL

SELECT
    'FIRMS_API',
    satellite,
    COUNT(brightness),
    MIN(brightness),
    QUANTILE_CONT(brightness, 0.01),
    QUANTILE_CONT(brightness, 0.25),
    QUANTILE_CONT(brightness, 0.50),
    QUANTILE_CONT(brightness, 0.75),
    QUANTILE_CONT(brightness, 0.99),
    MAX(brightness),
    AVG(brightness),
    STDDEV_SAMP(brightness),
    COUNT(*) FILTER (WHERE brightness = 0),
    COUNT(*) FILTER (WHERE brightness < 0)
FROM api_data
GROUP BY satellite
ORDER BY source, satellite;


-- RESULT 2: BRIGHT_T31

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    COUNT(bright_t31) AS populated,
    MIN(bright_t31) AS minimum,
    QUANTILE_CONT(bright_t31, 0.01) AS p01,
    QUANTILE_CONT(bright_t31, 0.25) AS p25,
    QUANTILE_CONT(bright_t31, 0.50) AS median,
    QUANTILE_CONT(bright_t31, 0.75) AS p75,
    QUANTILE_CONT(bright_t31, 0.99) AS p99,
    MAX(bright_t31) AS maximum,
    AVG(bright_t31) AS average,
    STDDEV_SAMP(bright_t31) AS stddev,
    COUNT(*) FILTER (WHERE bright_t31 = 0) AS zero_count,
    COUNT(*) FILTER (WHERE bright_t31 < 0) AS negative_count
FROM sample_data
GROUP BY satellite

UNION ALL

SELECT
    'FIRMS_API',
    satellite,
    COUNT(bright_t31),
    MIN(bright_t31),
    QUANTILE_CONT(bright_t31, 0.01),
    QUANTILE_CONT(bright_t31, 0.25),
    QUANTILE_CONT(bright_t31, 0.50),
    QUANTILE_CONT(bright_t31, 0.75),
    QUANTILE_CONT(bright_t31, 0.99),
    MAX(bright_t31),
    AVG(bright_t31),
    STDDEV_SAMP(bright_t31),
    COUNT(*) FILTER (WHERE bright_t31 = 0),
    COUNT(*) FILTER (WHERE bright_t31 < 0)
FROM api_data
GROUP BY satellite
ORDER BY source, satellite;


-- RESULT 3: BRIGHT_TI4
-- This field exists only in the API dataset.

SELECT
    'FIRMS_API' AS source,
    satellite,
    COUNT(bright_ti4) AS populated,
    MIN(bright_ti4) AS minimum,
    QUANTILE_CONT(bright_ti4, 0.01) AS p01,
    QUANTILE_CONT(bright_ti4, 0.25) AS p25,
    QUANTILE_CONT(bright_ti4, 0.50) AS median,
    QUANTILE_CONT(bright_ti4, 0.75) AS p75,
    QUANTILE_CONT(bright_ti4, 0.99) AS p99,
    MAX(bright_ti4) AS maximum,
    AVG(bright_ti4) AS average,
    STDDEV_SAMP(bright_ti4) AS stddev,
    COUNT(*) FILTER (WHERE bright_ti4 = 0) AS zero_count,
    COUNT(*) FILTER (WHERE bright_ti4 < 0) AS negative_count
FROM api_data
GROUP BY satellite
ORDER BY satellite;


-- RESULT 4: BRIGHT_TI5
-- This field exists only in the API dataset.

SELECT
    'FIRMS_API' AS source,
    satellite,
    COUNT(bright_ti5) AS populated,
    MIN(bright_ti5) AS minimum,
    QUANTILE_CONT(bright_ti5, 0.01) AS p01,
    QUANTILE_CONT(bright_ti5, 0.25) AS p25,
    QUANTILE_CONT(bright_ti5, 0.50) AS median,
    QUANTILE_CONT(bright_ti5, 0.75) AS p75,
    QUANTILE_CONT(bright_ti5, 0.99) AS p99,
    MAX(bright_ti5) AS maximum,
    AVG(bright_ti5) AS average,
    STDDEV_SAMP(bright_ti5) AS stddev,
    COUNT(*) FILTER (WHERE bright_ti5 = 0) AS zero_count,
    COUNT(*) FILTER (WHERE bright_ti5 < 0) AS negative_count
FROM api_data
GROUP BY satellite
ORDER BY satellite;


-- RESULT 5: FIRE RADIATIVE POWER (FRP)

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    COUNT(frp) AS populated,
    MIN(frp) AS minimum,
    QUANTILE_CONT(frp, 0.01) AS p01,
    QUANTILE_CONT(frp, 0.25) AS p25,
    QUANTILE_CONT(frp, 0.50) AS median,
    QUANTILE_CONT(frp, 0.75) AS p75,
    QUANTILE_CONT(frp, 0.99) AS p99,
    MAX(frp) AS maximum,
    AVG(frp) AS average,
    STDDEV_SAMP(frp) AS stddev,
    COUNT(*) FILTER (WHERE frp = 0) AS zero_count,
    COUNT(*) FILTER (WHERE frp < 0) AS negative_count
FROM sample_data
GROUP BY satellite

UNION ALL

SELECT
    'FIRMS_API',
    satellite,
    COUNT(frp),
    MIN(frp),
    QUANTILE_CONT(frp, 0.01),
    QUANTILE_CONT(frp, 0.25),
    QUANTILE_CONT(frp, 0.50),
    QUANTILE_CONT(frp, 0.75),
    QUANTILE_CONT(frp, 0.99),
    MAX(frp),
    AVG(frp),
    STDDEV_SAMP(frp),
    COUNT(*) FILTER (WHERE frp = 0),
    COUNT(*) FILTER (WHERE frp < 0)
FROM api_data
GROUP BY satellite
ORDER BY source, satellite;


-- RESULT 6: SCAN

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    COUNT(scan) AS populated,
    MIN(scan) AS minimum,
    QUANTILE_CONT(scan, 0.01) AS p01,
    QUANTILE_CONT(scan, 0.25) AS p25,
    QUANTILE_CONT(scan, 0.50) AS median,
    QUANTILE_CONT(scan, 0.75) AS p75,
    QUANTILE_CONT(scan, 0.99) AS p99,
    MAX(scan) AS maximum,
    AVG(scan) AS average,
    STDDEV_SAMP(scan) AS stddev,
    COUNT(*) FILTER (WHERE scan = 0) AS zero_count,
    COUNT(*) FILTER (WHERE scan < 0) AS negative_count
FROM sample_data
GROUP BY satellite

UNION ALL

SELECT
    'FIRMS_API',
    satellite,
    COUNT(scan),
    MIN(scan),
    QUANTILE_CONT(scan, 0.01),
    QUANTILE_CONT(scan, 0.25),
    QUANTILE_CONT(scan, 0.50),
    QUANTILE_CONT(scan, 0.75),
    QUANTILE_CONT(scan, 0.99),
    MAX(scan),
    AVG(scan),
    STDDEV_SAMP(scan),
    COUNT(*) FILTER (WHERE scan = 0),
    COUNT(*) FILTER (WHERE scan < 0)
FROM api_data
GROUP BY satellite
ORDER BY source, satellite;


-- RESULT 7: TRACK

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    COUNT(track) AS populated,
    MIN(track) AS minimum,
    QUANTILE_CONT(track, 0.01) AS p01,
    QUANTILE_CONT(track, 0.25) AS p25,
    QUANTILE_CONT(track, 0.50) AS median,
    QUANTILE_CONT(track, 0.75) AS p75,
    QUANTILE_CONT(track, 0.99) AS p99,
    MAX(track) AS maximum,
    AVG(track) AS average,
    STDDEV_SAMP(track) AS stddev,
    COUNT(*) FILTER (WHERE track = 0) AS zero_count,
    COUNT(*) FILTER (WHERE track < 0) AS negative_count
FROM sample_data
GROUP BY satellite

UNION ALL

SELECT
    'FIRMS_API',
    satellite,
    COUNT(track),
    MIN(track),
    QUANTILE_CONT(track, 0.01),
    QUANTILE_CONT(track, 0.25),
    QUANTILE_CONT(track, 0.50),
    QUANTILE_CONT(track, 0.75),
    QUANTILE_CONT(track, 0.99),
    MAX(track),
    AVG(track),
    STDDEV_SAMP(track),
    COUNT(*) FILTER (WHERE track = 0),
    COUNT(*) FILTER (WHERE track < 0)
FROM api_data
GROUP BY satellite
ORDER BY source, satellite;
