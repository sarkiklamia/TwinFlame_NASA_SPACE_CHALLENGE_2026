
-- ============================================================
-- 06_spatial_coverage.sql
-- Purpose: Explore geographic coverage and coordinate quality.
-- Read-only: source files are never modified.
-- ============================================================

CREATE OR REPLACE TEMP TABLE spatial_data AS

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    instrument,
    latitude,
    longitude
FROM read_csv_auto(
    'data/raw/sample/*.csv',
    union_by_name = true
)

UNION ALL

SELECT
    'FIRMS_API' AS source,
    satellite,
    instrument,
    latitude,
    longitude
FROM read_parquet(
    'data/raw/api/**/*.parquet',
    union_by_name = true
);


-- 1. Coordinate ranges and invalid values
SELECT
    source,
    satellite,
    COUNT(*) AS total_rows,
    ROUND(MIN(latitude), 4) AS min_lat,
    ROUND(MAX(latitude), 4) AS max_lat,
    ROUND(MIN(longitude), 4) AS min_lon,
    ROUND(MAX(longitude), 4) AS max_lon,
    COUNT(*) FILTER (
        WHERE latitude < -90 OR latitude > 90
    ) AS invalid_latitudes,
    COUNT(*) FILTER (
        WHERE longitude < -180 OR longitude > 180
    ) AS invalid_longitudes,
    COUNT(*) FILTER (
        WHERE latitude IS NULL OR longitude IS NULL
    ) AS null_coordinates
FROM spatial_data
GROUP BY source, satellite
ORDER BY source, satellite;


-- 2. Distribution by hemisphere
SELECT
    source,
    satellite,
    COUNT(*) FILTER (WHERE latitude >= 0) AS northern,
    COUNT(*) FILTER (WHERE latitude < 0) AS southern,
    COUNT(*) FILTER (WHERE longitude >= 0) AS eastern,
    COUNT(*) FILTER (WHERE longitude < 0) AS western
FROM spatial_data
GROUP BY source, satellite
ORDER BY source, satellite;


-- 3. Approximate geographic-region distribution
-- Regions are broad bounding boxes, not precise continent boundaries.
SELECT
    source,
    satellite,
    CASE
        WHEN latitude BETWEEN  35 AND  72
         AND longitude BETWEEN -12 AND  45 THEN 'Europe'
        WHEN latitude BETWEEN -35 AND  37
         AND longitude BETWEEN -18 AND  52 THEN 'Africa'
        WHEN latitude BETWEEN   5 AND  83
         AND longitude BETWEEN  45 AND 180 THEN 'Asia'
        WHEN latitude BETWEEN -56 AND  13
         AND longitude BETWEEN -82 AND -34 THEN 'South America'
        WHEN latitude BETWEEN   5 AND  84
         AND longitude BETWEEN -170 AND -50 THEN 'North America'
        WHEN latitude BETWEEN -50 AND -10
         AND longitude BETWEEN 110 AND 180 THEN 'Oceania'
        WHEN latitude BETWEEN -90 AND -60 THEN 'Antarctica'
        ELSE 'Other / overlapping boundaries'
    END AS approximate_region,
    COUNT(*) AS detections
FROM spatial_data
WHERE latitude BETWEEN -90 AND 90
  AND longitude BETWEEN -180 AND 180
GROUP BY source, satellite, approximate_region
ORDER BY source, satellite, detections DESC;


-- 4. Exact repeated coordinate pairs
-- Counts how many coordinate pairs occur more than once.
WITH coordinate_counts AS (
    SELECT
        source,
        satellite,
        latitude,
        longitude,
        COUNT(*) AS occurrences
    FROM spatial_data
    WHERE latitude IS NOT NULL
      AND longitude IS NOT NULL
    GROUP BY source, satellite, latitude, longitude
)
SELECT
    source,
    satellite,
    COUNT(*) AS unique_coordinate_pairs,
    COUNT(*) FILTER (WHERE occurrences > 1) AS repeated_pairs,
    SUM(occurrences - 1) FILTER (
        WHERE occurrences > 1
    ) AS rows_beyond_first_occurrence,
    MAX(occurrences) AS max_occurrences
FROM coordinate_counts
GROUP BY source, satellite
ORDER BY source, satellite;


-- 5. Geographic distribution in 30-degree grid cells
SELECT
    source,
    satellite,
    FLOOR((latitude + 90) / 30) AS latitude_band,
    FLOOR((longitude + 180) / 30) AS longitude_band,
    COUNT(*) AS detections
FROM spatial_data
WHERE latitude BETWEEN -90 AND 90
  AND longitude BETWEEN -180 AND 180
GROUP BY
    source,
    satellite,
    latitude_band,
    longitude_band
ORDER BY source, satellite, detections DESC
LIMIT 100;
