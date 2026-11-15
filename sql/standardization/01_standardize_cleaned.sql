-- ============================================================
-- PyroSync — Standardization
-- Input : {{CLEANED_INPUT}}
-- Output: temporary Parquet file, verified before replacement
--
-- IMPORTANT:
--   - Original brightness columns are preserved independently.
--   - No brightness_native field is generated.
--   - Raw source files are never modified.
-- ============================================================


-- ------------------------------------------------------------
-- 1. Read cleaned data and standardize the schema
-- ------------------------------------------------------------

COPY (
    SELECT
        -- Source provenance
        CAST(source_file AS VARCHAR) AS source_file,
        CAST(source_type AS VARCHAR) AS source_type,
        CAST(source AS VARCHAR) AS source,

        -- Original satellite and instrument identifiers
        CAST(satellite AS VARCHAR) AS satellite,
        CAST(instrument AS VARCHAR) AS instrument,

        -- Standardized platform and sensor
        CASE UPPER(TRIM(satellite))
            WHEN 'AQUA'  THEN 'MODIS_AQUA'
            WHEN 'TERRA' THEN 'MODIS_TERRA'
            WHEN 'N20'   THEN 'VIIRS_NOAA20'
            WHEN 'N21'   THEN 'VIIRS_NOAA21'
            ELSE NULL
        END AS platform,

        CASE UPPER(TRIM(satellite))
            WHEN 'AQUA'  THEN 'MODIS'
            WHEN 'TERRA' THEN 'MODIS'
            WHEN 'N20'   THEN 'VIIRS'
            WHEN 'N21'   THEN 'VIIRS'
            ELSE NULL
        END AS sensor,

        -- Geographic coordinates
        CAST(latitude AS FLOAT) AS latitude,
        CAST(longitude AS FLOAT) AS longitude,

        -- Preserve original date and time values
        acq_date,
        acq_time,

        -- Standardized acquisition timestamp.
        -- HHMM is zero-padded before parsing.
        -- The resulting TIMESTAMP represents UTC.
        STRPTIME(
            CAST(acq_date AS VARCHAR)
            || LPAD(CAST(acq_time AS VARCHAR), 4, '0'),
            '%Y-%m-%d%H%M'
        )::TIMESTAMP AS acquisition_time_utc,

        -- Native confidence is preserved as text
        CAST(confidence AS VARCHAR) AS confidence_native,

        -- Confidence classification.
        -- MODIS and VIIRS retain their separate native scales.
        CASE
            WHEN UPPER(TRIM(instrument)) = 'MODIS' THEN
                CASE
                    WHEN TRY_CAST(TRIM(confidence) AS DOUBLE)
                         BETWEEN 0 AND 29 THEN 'LOW'
                    WHEN TRY_CAST(TRIM(confidence) AS DOUBLE)
                         BETWEEN 30 AND 79 THEN 'NOMINAL'
                    WHEN TRY_CAST(TRIM(confidence) AS DOUBLE)
                         BETWEEN 80 AND 100 THEN 'HIGH'
                    ELSE 'UNKNOWN'
                END

            WHEN UPPER(TRIM(instrument)) = 'VIIRS' THEN
                CASE LOWER(TRIM(confidence))
                    WHEN 'l' THEN 'LOW'
                    WHEN 'n' THEN 'NOMINAL'
                    WHEN 'h' THEN 'HIGH'
                    ELSE 'UNKNOWN'
                END

            ELSE 'UNKNOWN'
        END AS confidence_class,

        -- Native brightness measurements.
        -- No assignment between channels or sensors.
        CAST(brightness AS FLOAT) AS brightness,
        CAST(bright_t31 AS FLOAT) AS bright_t31,
        CAST(bright_ti4 AS FLOAT) AS bright_ti4,
        CAST(bright_ti5 AS FLOAT) AS bright_ti5,

        -- Fire radiative power
        CAST(frp AS FLOAT) AS frp_mw,

        -- Pixel dimensions in kilometres.
        -- Values are retained without unit conversion.
        CAST(scan AS FLOAT) AS scan_km,
        CAST(track AS FLOAT) AS track_km,

        -- Standardized day/night indicator
        CASE UPPER(TRIM(daynight))
            WHEN 'D' THEN 'DAY'
            WHEN 'N' THEN 'NIGHT'
            ELSE NULL
        END AS daynight,

        -- Preserve the product version, including NRT/URT suffixes
        CAST(version AS VARCHAR) AS product_version,

        -- Preserve cleaning flags
        CAST(quality_flags AS VARCHAR) AS quality_flags

    FROM read_parquet(
        '{{CLEANED_INPUT}}'
    )

) TO '{{STANDARDIZED_OUTPUT}}'
(FORMAT PARQUET, COMPRESSION ZSTD);


-- ------------------------------------------------------------
-- 2. Verification — row count
-- ------------------------------------------------------------

SELECT
    'ROW_COUNT' AS check_name,
    (
        SELECT COUNT(*)
        FROM read_parquet(
            '{{CLEANED_INPUT}}'
        )
    ) AS original_rows,
    (
        SELECT COUNT(*)
        FROM read_parquet(
            '{{STANDARDIZED_OUTPUT}}'
        )
    ) AS standardized_rows;


-- ------------------------------------------------------------
-- 3. Verification — standardized fields
-- ------------------------------------------------------------

SELECT
    COUNT(*) AS total_rows,

    COUNT(*) FILTER (
        WHERE acquisition_time_utc IS NULL
    ) AS invalid_timestamps,

    COUNT(*) FILTER (
        WHERE platform IS NULL
    ) AS unmapped_platforms,

    COUNT(*) FILTER (
        WHERE sensor IS NULL
    ) AS unmapped_sensors,

    COUNT(*) FILTER (
        WHERE confidence_class = 'UNKNOWN'
    ) AS unknown_confidence_classes,

    COUNT(*) FILTER (
        WHERE daynight IS NULL
    ) AS invalid_daynight_values

FROM read_parquet(
    '{{STANDARDIZED_OUTPUT}}'
);


-- ------------------------------------------------------------
-- 4. Verification — satellite and instrument consistency
-- ------------------------------------------------------------

SELECT
    satellite,
    instrument,
    platform,
    sensor,
    COUNT(*) AS record_count

FROM read_parquet(
    '{{STANDARDIZED_OUTPUT}}'
)

GROUP BY
    satellite,
    instrument,
    platform,
    sensor

ORDER BY
    satellite,
    instrument;


-- ------------------------------------------------------------
-- 5. Verification — confidence classification
-- ------------------------------------------------------------

SELECT
    instrument,
    confidence_class,
    COUNT(*) AS record_count

FROM read_parquet(
    '{{STANDARDIZED_OUTPUT}}'
)

GROUP BY
    instrument,
    confidence_class

ORDER BY
    instrument,
    confidence_class;


-- ------------------------------------------------------------
-- 6. Verification — native brightness preservation
-- ------------------------------------------------------------

SELECT
    COUNT(*) AS total_rows,

    COUNT(brightness) AS brightness_non_null,
    COUNT(bright_t31) AS bright_t31_non_null,
    COUNT(bright_ti4) AS bright_ti4_non_null,
    COUNT(bright_ti5) AS bright_ti5_non_null,

    COUNT(*) FILTER (
        WHERE brightness IS NULL
          AND bright_t31 IS NULL
          AND bright_ti4 IS NULL
          AND bright_ti5 IS NULL
    ) AS rows_without_brightness_measurements

FROM read_parquet(
    '{{STANDARDIZED_OUTPUT}}'
);


-- ------------------------------------------------------------
-- 7. Verification — final schema
-- ------------------------------------------------------------

DESCRIBE
SELECT *
FROM read_parquet(
    '{{STANDARDIZED_OUTPUT}}'
);


-- ------------------------------------------------------------
-- 8. Preview
-- ------------------------------------------------------------

SELECT *
FROM read_parquet(
    '{{STANDARDIZED_OUTPUT}}'
)
LIMIT 10;