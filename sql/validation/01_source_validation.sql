
-- ============================================================
-- 01_source_validation.sql
-- PyroSync - Source validation
-- READ ONLY: Does not modify raw files or records.
-- ============================================================

-- 1. Load raw datasets once

CREATE OR REPLACE TEMP TABLE c2_raw AS
SELECT *
FROM read_csv_auto(
    'data/raw/sample/*.csv',
    union_by_name = true
);

CREATE OR REPLACE TEMP TABLE api_raw AS
SELECT *
FROM read_parquet(
    'data/raw/api/**/*.parquet',
    union_by_name = true
);


-- 2. Build a common validation table

CREATE OR REPLACE TEMP TABLE validation_data AS

SELECT
    'C2_SAMPLE' AS source,
    satellite,
    instrument,
    confidence,
    CAST(version AS VARCHAR) AS version,
    daynight,
    TRY_CAST(acq_date AS DATE) AS acq_date,
    TRY_CAST(acq_time AS BIGINT) AS acq_time,
    latitude,
    longitude,
    brightness,
    bright_t31,
    CAST(NULL AS DOUBLE) AS bright_ti4,
    CAST(NULL AS DOUBLE) AS bright_ti5,
    frp,
    scan,
    track
FROM c2_raw

UNION ALL

SELECT
    'FIRMS_API' AS source,
    satellite,
    instrument,
    confidence,
    CAST(version AS VARCHAR) AS version,
    daynight,
    TRY_CAST(acq_date AS DATE) AS acq_date,
    TRY_CAST(acq_time AS BIGINT) AS acq_time,
    latitude,
    longitude,
    brightness,
    bright_t31,
    bright_ti4,
    bright_ti5,
    frp,
    scan,
    track
FROM api_raw;


-- 3. Structural validation

SELECT
    'C2_SAMPLE' AS source,
    COUNT(*) AS column_count
FROM pragma_table_info('c2_raw')

UNION ALL

SELECT
    'FIRMS_API',
    COUNT(*)
FROM pragma_table_info('api_raw');


-- 4. Required-field completeness

SELECT
    source,
    satellite,
    COUNT(*) AS total_rows,

    COUNT(*) FILTER (WHERE latitude IS NULL) AS missing_latitude,
    COUNT(*) FILTER (WHERE longitude IS NULL) AS missing_longitude,
    COUNT(*) FILTER (WHERE acq_date IS NULL) AS missing_or_invalid_date,
    COUNT(*) FILTER (WHERE acq_time IS NULL) AS missing_time,
    COUNT(*) FILTER (
        WHERE confidence IS NULL OR TRIM(confidence) = ''
    ) AS missing_confidence,
    COUNT(*) FILTER (
        WHERE version IS NULL OR TRIM(version) = ''
    ) AS missing_version,
    COUNT(*) FILTER (
        WHERE daynight IS NULL OR TRIM(daynight) = ''
    ) AS missing_daynight,
    COUNT(*) FILTER (
        WHERE instrument IS NULL OR TRIM(instrument) = ''
    ) AS missing_instrument,
    COUNT(*) FILTER (WHERE scan IS NULL) AS missing_scan,
    COUNT(*) FILTER (WHERE track IS NULL) AS missing_track,
    COUNT(*) FILTER (WHERE frp IS NULL) AS missing_frp,

    COUNT(*) FILTER (
        WHERE (
            source = 'C2_SAMPLE'
            OR (source = 'FIRMS_API' AND instrument = 'MODIS')
        )
        AND brightness IS NULL
    ) AS missing_brightness,

    COUNT(*) FILTER (
        WHERE (
            source = 'C2_SAMPLE'
            OR (source = 'FIRMS_API' AND instrument = 'MODIS')
        )
        AND bright_t31 IS NULL
    ) AS missing_bright_t31,

    COUNT(*) FILTER (
        WHERE source = 'FIRMS_API'
          AND instrument = 'VIIRS'
          AND bright_ti4 IS NULL
    ) AS missing_bright_ti4,

    COUNT(*) FILTER (
        WHERE source = 'FIRMS_API'
          AND instrument = 'VIIRS'
          AND bright_ti5 IS NULL
    ) AS missing_bright_ti5

FROM validation_data
GROUP BY source, satellite
ORDER BY source, satellite;


-- 5. Coordinate and numerical validation

SELECT
    source,
    satellite,
    COUNT(*) AS total_rows,

    COUNT(*) FILTER (
        WHERE latitude < -90 OR latitude > 90
    ) AS invalid_latitude,

    COUNT(*) FILTER (
        WHERE longitude < -180 OR longitude > 180
    ) AS invalid_longitude,

    COUNT(*) FILTER (
        WHERE latitude IS NOT NULL AND NOT isfinite(latitude)
    ) AS nonfinite_latitude,

    COUNT(*) FILTER (
        WHERE longitude IS NOT NULL AND NOT isfinite(longitude)
    ) AS nonfinite_longitude,

    COUNT(*) FILTER (
        WHERE brightness IS NOT NULL AND NOT isfinite(brightness)
    ) AS nonfinite_brightness,

    COUNT(*) FILTER (
        WHERE bright_t31 IS NOT NULL AND NOT isfinite(bright_t31)
    ) AS nonfinite_bright_t31,

    COUNT(*) FILTER (
        WHERE bright_ti4 IS NOT NULL AND NOT isfinite(bright_ti4)
    ) AS nonfinite_bright_ti4,

    COUNT(*) FILTER (
        WHERE bright_ti5 IS NOT NULL AND NOT isfinite(bright_ti5)
    ) AS nonfinite_bright_ti5,

    COUNT(*) FILTER (
        WHERE frp IS NOT NULL AND NOT isfinite(frp)
    ) AS nonfinite_frp,

    COUNT(*) FILTER (
        WHERE scan IS NOT NULL AND NOT isfinite(scan)
    ) AS nonfinite_scan,

    COUNT(*) FILTER (
        WHERE track IS NOT NULL AND NOT isfinite(track)
    ) AS nonfinite_track,

    COUNT(*) FILTER (
        WHERE brightness < 0
           OR bright_t31 < 0
           OR bright_ti4 < 0
           OR bright_ti5 < 0
    ) AS negative_brightness_rows,

    COUNT(*) FILTER (WHERE frp < 0) AS negative_frp,
    COUNT(*) FILTER (WHERE frp = 0) AS zero_frp,
    COUNT(*) FILTER (WHERE scan <= 0) AS invalid_scan,
    COUNT(*) FILTER (WHERE track <= 0) AS invalid_track

FROM validation_data
GROUP BY source, satellite
ORDER BY source, satellite;


-- 6. Acquisition time validation
-- Keep acq_time as BIGINT. No formatting is performed.

SELECT
    source,
    satellite,
    COUNT(*) AS total_rows,

    COUNT(*) FILTER (
        WHERE acq_time IS NULL
    ) AS missing_time,

    COUNT(*) FILTER (
        WHERE acq_time < 0
           OR acq_time > 2359
           OR acq_time % 100 > 59
    ) AS invalid_hhmm

FROM validation_data
GROUP BY source, satellite
ORDER BY source, satellite;


-- 7. Satellite / instrument consistency

SELECT
    source,
    satellite,
    instrument,
    COUNT(*) AS affected_rows
FROM validation_data
WHERE NOT (
    (satellite = 'Aqua' AND instrument = 'MODIS')
    OR (satellite = 'Terra' AND instrument = 'MODIS')
    OR (satellite = 'N20' AND instrument = 'VIIRS')
    OR (satellite = 'N21' AND instrument = 'VIIRS')
)
GROUP BY source, satellite, instrument
ORDER BY source, satellite, instrument;


-- 8. Confidence validation

SELECT
    source,
    satellite,
    instrument,
    confidence,
    COUNT(*) AS affected_rows
FROM validation_data
WHERE
    (
        instrument = 'MODIS'
        AND (
            TRY_CAST(confidence AS DOUBLE) IS NULL
            OR TRY_CAST(confidence AS DOUBLE) NOT BETWEEN 0 AND 100
        )
    )
    OR
    (
        instrument = 'VIIRS'
        AND LOWER(TRIM(confidence)) NOT IN ('l', 'n', 'h')
    )
GROUP BY source, satellite, instrument, confidence
ORDER BY source, satellite, confidence;


-- 9. Version validation

SELECT
    source,
    satellite,
    version,
    COUNT(*) AS affected_rows
FROM validation_data
WHERE NOT (
    (
        source = 'C2_SAMPLE'
        AND satellite IN ('Aqua', 'Terra')
        AND version = '61.03'
    )
    OR
    (
        source = 'C2_SAMPLE'
        AND satellite IN ('N20', 'N21')
        AND version = '2.0'
    )
    OR
    (
        source = 'FIRMS_API'
        AND satellite IN ('Aqua', 'Terra')
        AND version = '6.1NRT'
    )
    OR
    (
        source = 'FIRMS_API'
        AND satellite = 'N20'
        AND version = '2.0NRT'
    )
    OR
    (
        source = 'FIRMS_API'
        AND satellite = 'N21'
        AND version IN ('2.0NRT', '2.0URT')
    )
)
GROUP BY source, satellite, version
ORDER BY source, satellite, version;


-- 10. Day/night validation

SELECT
    source,
    satellite,
    daynight,
    COUNT(*) AS affected_rows
FROM validation_data
WHERE daynight IS NULL
   OR daynight NOT IN ('D', 'N')
GROUP BY source, satellite, daynight
ORDER BY source, satellite, daynight;



-- 11. Exact duplicate records in C2
-- Group by every original column, then count repeated groups.

SELECT
    'C2_SAMPLE' AS source,
    COUNT(*) FILTER (WHERE n > 1) AS duplicate_groups,
    COALESCE(
        SUM(n - 1) FILTER (WHERE n > 1),
        0
    ) AS duplicate_rows
FROM (
    SELECT
        *,
        COUNT(*) AS n
    FROM c2_raw
    GROUP BY ALL
);


-- 12. Exact duplicate records in API

SELECT
    'FIRMS_API' AS source,
    COUNT(*) FILTER (WHERE n > 1) AS duplicate_groups,
    COALESCE(
        SUM(n - 1) FILTER (WHERE n > 1),
        0
    ) AS duplicate_rows
FROM (
    SELECT
        *,
        COUNT(*) AS n
    FROM api_raw
    GROUP BY ALL
);
