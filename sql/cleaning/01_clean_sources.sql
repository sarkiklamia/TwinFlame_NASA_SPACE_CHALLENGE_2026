
-- ============================================================
-- PYROSYNC - SOURCE CLEANING AND QUALITY FLAGGING
--
-- INPUTS:
--   c2_raw and api_raw temporary tables created by the caller
--
-- OUTPUTS:
--   Paths supplied through CLEANED_OUTPUT, QUARANTINE_OUTPUT,
--   and CLEANING_REPORT_OUTPUT template values
--
-- PRINCIPLES:
--   1. Raw files are never modified.
--   2. Exact duplicates are removed within each source.
--   3. Original source filename is preserved for provenance.
--   4. Invalid records are quarantined with reasons.
--   5. Suspicious records are retained with quality flags.
--   6. Native brightness measurements are never substituted.
--   7. C2-only "type" is excluded from cleaned detections.
--   8. source_type means API or ARCHIVE, never detection type.
-- ============================================================


-- ============================================================
-- 1. RAW INPUT TABLES
-- ============================================================
-- The caller creates c2_raw and api_raw from an explicit input-file list.
-- This lets both the full archive rebuild and incremental API import use
-- exactly the same cleaning rules without scanning unrelated old files.


-- ============================================================
-- 2. REMOVE EXACT DUPLICATES IN EACH ORIGINAL SOURCE
-- ============================================================
-- Filename is excluded from duplicate comparison.
-- The lexicographically first filename is retained as the
-- representative provenance file for each distinct record.
--
-- C2 "type" remains part of the original-record comparison.
-- No cross-source deduplication is performed.

CREATE OR REPLACE TEMP TABLE c2_raw_dedup AS
SELECT
    * EXCLUDE (filename),
    MIN(filename) AS source_file
FROM c2_raw
GROUP BY ALL;

CREATE OR REPLACE TEMP TABLE api_raw_dedup AS
SELECT
    * EXCLUDE (filename),
    MIN(filename) AS source_file
FROM api_raw
GROUP BY ALL;


-- ============================================================
-- 3. MAP SOURCES TO A COMMON STAGING SCHEMA
-- ============================================================
-- source_type:
--   ARCHIVE = C2 archive/sample CSV
--   API     = FIRMS API Parquet
--
-- C2 detection "type" is excluded from the detection schema.
-- Dates and versions remain VARCHAR.
-- Acquisition time remains BIGINT.
-- Brightness measurements remain separate.

CREATE OR REPLACE TEMP TABLE raw_records AS

SELECT
    'C2_SAMPLE' AS source,
    'ARCHIVE' AS source_type,

    regexp_extract(
        replace(source_file, chr(92), '/'),
        '[^/]+$'
    ) AS source_file,

    CAST(latitude AS DOUBLE) AS latitude,
    CAST(longitude AS DOUBLE) AS longitude,
    CAST(brightness AS DOUBLE) AS brightness,
    CAST(bright_t31 AS DOUBLE) AS bright_t31,
    CAST(NULL AS DOUBLE) AS bright_ti4,
    CAST(NULL AS DOUBLE) AS bright_ti5,
    CAST(frp AS DOUBLE) AS frp,
    CAST(scan AS DOUBLE) AS scan,
    CAST(track AS DOUBLE) AS track,
    CAST(acq_date AS VARCHAR) AS acq_date,
    CAST(acq_time AS BIGINT) AS acq_time,
    CAST(satellite AS VARCHAR) AS satellite,
    CAST(instrument AS VARCHAR) AS instrument,
    CAST(confidence AS VARCHAR) AS confidence,
    CAST(version AS VARCHAR) AS version,
    CAST(daynight AS VARCHAR) AS daynight

FROM c2_raw_dedup

UNION ALL

SELECT
    'FIRMS_API' AS source,
    'API' AS source_type,

    regexp_extract(
        replace(source_file, chr(92), '/'),
        '[^/]+$'
    ) AS source_file,

    CAST(latitude AS DOUBLE),
    CAST(longitude AS DOUBLE),
    CAST(brightness AS DOUBLE),
    CAST(bright_t31 AS DOUBLE),
    CAST(bright_ti4 AS DOUBLE),
    CAST(bright_ti5 AS DOUBLE),
    CAST(frp AS DOUBLE),
    CAST(scan AS DOUBLE),
    CAST(track AS DOUBLE),
    CAST(acq_date AS VARCHAR),
    CAST(acq_time AS BIGINT),
    CAST(satellite AS VARCHAR),
    CAST(instrument AS VARCHAR),
    CAST(confidence AS VARCHAR),
    CAST(version AS VARCHAR),
    CAST(daynight AS VARCHAR)

FROM api_raw_dedup;


-- ============================================================
-- 4. CLASSIFY INVALID RECORDS
-- ============================================================
-- Critical problems -> quarantine.
-- Suspicious but usable values -> retained and flagged later.
-- Non-applicable brightness NULLs are expected.

CREATE OR REPLACE TEMP TABLE classified_records AS

SELECT
    *,

    NULLIF(
        CONCAT_WS(
            ' | ',

            CASE
                WHEN latitude IS NULL OR longitude IS NULL
                THEN 'Missing coordinates'
            END,

            CASE
                WHEN acq_date IS NULL
                     OR TRY_CAST(acq_date AS DATE) IS NULL
                THEN 'Missing or invalid acquisition date'
            END,

            CASE
                WHEN acq_time IS NULL
                THEN 'Missing acquisition time'
            END,

            CASE
                WHEN confidence IS NULL OR TRIM(confidence) = ''
                THEN 'Missing confidence'
            END,

            CASE
                WHEN version IS NULL OR TRIM(version) = ''
                THEN 'Missing version'
            END,

            CASE
                WHEN daynight IS NULL
                THEN 'Missing daynight'
            END,

            CASE
                WHEN satellite IS NULL OR instrument IS NULL
                THEN 'Missing satellite or instrument'
            END,

            CASE
                WHEN scan IS NULL OR track IS NULL OR frp IS NULL
                THEN 'Missing scan, track or FRP'
            END,

            CASE
                WHEN source = 'C2_SAMPLE'
                     AND (brightness IS NULL OR bright_t31 IS NULL)
                THEN 'Missing required C2 brightness'
            END,

            CASE
                WHEN source = 'FIRMS_API'
                     AND instrument = 'MODIS'
                     AND (brightness IS NULL OR bright_t31 IS NULL)
                THEN 'Missing required MODIS brightness'
            END,

            CASE
                WHEN source = 'FIRMS_API'
                     AND instrument = 'VIIRS'
                     AND (bright_ti4 IS NULL OR bright_ti5 IS NULL)
                THEN 'Missing required VIIRS brightness'
            END,

            CASE
                WHEN latitude IS NOT NULL
                     AND NOT isfinite(latitude)
                THEN 'Non-finite latitude'
            END,

            CASE
                WHEN longitude IS NOT NULL
                     AND NOT isfinite(longitude)
                THEN 'Non-finite longitude'
            END,

            CASE
                WHEN latitude IS NOT NULL
                     AND (latitude < -90 OR latitude > 90)
                THEN 'Latitude outside valid range'
            END,

            CASE
                WHEN longitude IS NOT NULL
                     AND (longitude < -180 OR longitude > 180)
                THEN 'Longitude outside valid range'
            END,

            CASE
                WHEN acq_time IS NOT NULL
                     AND (
                         acq_time < 0
                         OR acq_time > 2359
                         OR acq_time % 100 >= 60
                         OR acq_time // 100 > 23
                     )
                THEN 'Invalid HHMM acquisition time'
            END,

            CASE
                WHEN scan IS NOT NULL
                     AND (NOT isfinite(scan) OR scan <= 0)
                THEN 'Invalid scan'
            END,

            CASE
                WHEN track IS NOT NULL
                     AND (NOT isfinite(track) OR track <= 0)
                THEN 'Invalid track'
            END,

            CASE
                WHEN frp IS NOT NULL
                     AND (NOT isfinite(frp) OR frp < 0)
                THEN 'Invalid FRP'
            END,

            CASE
                WHEN brightness IS NOT NULL
                     AND (NOT isfinite(brightness) OR brightness < 0)
                THEN 'Invalid brightness'
            END,

            CASE
                WHEN bright_t31 IS NOT NULL
                     AND (NOT isfinite(bright_t31) OR bright_t31 < 0)
                THEN 'Invalid bright_t31'
            END,

            CASE
                WHEN bright_ti4 IS NOT NULL
                     AND (NOT isfinite(bright_ti4) OR bright_ti4 < 0)
                THEN 'Invalid bright_ti4'
            END,

            CASE
                WHEN bright_ti5 IS NOT NULL
                     AND (NOT isfinite(bright_ti5) OR bright_ti5 < 0)
                THEN 'Invalid bright_ti5'
            END,

            CASE
                WHEN NOT COALESCE(
                    (satellite = 'Aqua' AND instrument = 'MODIS')
                    OR (satellite = 'Terra' AND instrument = 'MODIS')
                    OR (satellite = 'N20' AND instrument = 'VIIRS')
                    OR (satellite = 'N21' AND instrument = 'VIIRS'),
                    FALSE
                )
                THEN 'Unknown satellite/instrument combination'
            END,

            CASE
                WHEN instrument = 'MODIS'
                     AND (
                         TRY_CAST(confidence AS DOUBLE) IS NULL
                         OR TRY_CAST(confidence AS DOUBLE) NOT BETWEEN 0 AND 100
                     )
                THEN 'Invalid MODIS confidence'
            END,

            CASE
                WHEN instrument = 'VIIRS'
                     AND LOWER(TRIM(confidence)) NOT IN ('l', 'n', 'h')
                THEN 'Invalid VIIRS confidence'
            END,

            CASE
                WHEN daynight NOT IN ('D', 'N')
                THEN 'Invalid daynight value'
            END,

            CASE
                WHEN source_type NOT IN ('API', 'ARCHIVE')
                THEN 'Invalid source type'
            END,

            CASE
                WHEN source_file IS NULL OR TRIM(source_file) = ''
                THEN 'Missing source filename'
            END
        ),
        ''
    ) AS quarantine_reason

FROM raw_records;


-- ============================================================
-- 5. SEPARATE VALID AND QUARANTINED RECORDS
-- ============================================================

CREATE OR REPLACE TEMP TABLE valid_records AS
SELECT *
FROM classified_records
WHERE quarantine_reason IS NULL;

CREATE OR REPLACE TEMP TABLE quarantined_records AS
SELECT *
FROM classified_records
WHERE quarantine_reason IS NOT NULL;


-- ============================================================
-- 6. PREPARE NATIVE MEASUREMENTS FOR INVESTIGATION
-- ============================================================
-- Positive values only for percentile analysis.
-- Zero values are handled as separate quality flags.

CREATE OR REPLACE TEMP TABLE investigation_values AS

SELECT source, satellite, 'brightness' AS metric, brightness AS value
FROM valid_records
WHERE brightness IS NOT NULL AND brightness > 0

UNION ALL

SELECT source, satellite, 'bright_t31', bright_t31
FROM valid_records
WHERE bright_t31 IS NOT NULL AND bright_t31 > 0

UNION ALL

SELECT source, satellite, 'bright_ti4', bright_ti4
FROM valid_records
WHERE bright_ti4 IS NOT NULL AND bright_ti4 > 0

UNION ALL

SELECT source, satellite, 'bright_ti5', bright_ti5
FROM valid_records
WHERE bright_ti5 IS NOT NULL AND bright_ti5 > 0

UNION ALL

SELECT source, satellite, 'frp', frp
FROM valid_records
WHERE frp IS NOT NULL AND frp > 0;


-- ============================================================
-- 7. CALCULATE OR REUSE INVESTIGATION THRESHOLDS
-- ============================================================
-- Lower 1st percentile: low-tail review candidates.
-- Upper Q3 + 1.5 * IQR: high-value review candidates.
-- Thresholds are source/satellite-specific.

CREATE OR REPLACE TEMP TABLE computed_investigation_thresholds AS

SELECT
    source,
    satellite,
    metric,
    COUNT(*) AS observation_count,
    QUANTILE_CONT(value, 0.01) AS lower_percentile,
    QUANTILE_CONT(value, 0.25) AS q1,
    QUANTILE_CONT(value, 0.75) AS q3

FROM investigation_values
GROUP BY source, satellite, metric;

-- A full rebuild calculates these thresholds from its complete input set.
-- Incremental API batches reuse the saved baseline thresholds. New
-- source/satellite/metric combinations fall back to batch-derived values.
CREATE OR REPLACE TEMP TABLE investigation_thresholds AS
SELECT *
FROM cleaning_threshold_overrides

UNION ALL

SELECT computed.*
FROM computed_investigation_thresholds AS computed
WHERE NOT EXISTS (
    SELECT 1
    FROM cleaning_threshold_overrides AS fixed
    WHERE fixed.source = computed.source
      AND fixed.satellite = computed.satellite
      AND fixed.metric = computed.metric
);


-- ============================================================
-- 8. ORGANIZE THRESHOLDS BY MEASUREMENT
-- ============================================================

CREATE OR REPLACE TEMP TABLE investigation_limits AS

SELECT
    source,
    satellite,

    MAX(CASE WHEN metric = 'brightness'
        THEN lower_percentile END) AS brightness_low,

    MAX(CASE WHEN metric = 'brightness'
        THEN q3 + 1.5 * (q3 - q1) END) AS brightness_high,

    MAX(CASE WHEN metric = 'bright_t31'
        THEN lower_percentile END) AS bright_t31_low,

    MAX(CASE WHEN metric = 'bright_t31'
        THEN q3 + 1.5 * (q3 - q1) END) AS bright_t31_high,

    MAX(CASE WHEN metric = 'bright_ti4'
        THEN lower_percentile END) AS bright_ti4_low,

    MAX(CASE WHEN metric = 'bright_ti4'
        THEN q3 + 1.5 * (q3 - q1) END) AS bright_ti4_high,

    MAX(CASE WHEN metric = 'bright_ti5'
        THEN lower_percentile END) AS bright_ti5_low,

    MAX(CASE WHEN metric = 'bright_ti5'
        THEN q3 + 1.5 * (q3 - q1) END) AS bright_ti5_high,

    MAX(CASE WHEN metric = 'frp'
        THEN q3 + 1.5 * (q3 - q1) END) AS frp_high

FROM investigation_thresholds
GROUP BY source, satellite;


-- ============================================================
-- 9. ATTACH QUALITY FLAGS
-- ============================================================
-- All flagged records remain in the cleaned dataset.
-- Multiple flags can apply to one record.

CREATE OR REPLACE TEMP TABLE investigated_records AS

SELECT
    v.*,

    NULLIF(
        CONCAT_WS(
            ' | ',

            CASE
                WHEN v.frp = 0
                THEN 'ZERO_FRP'
            END,

            CASE
                WHEN v.brightness = 0
                THEN 'ZERO_BRIGHTNESS'
            END,

            CASE
                WHEN v.bright_t31 = 0
                THEN 'ZERO_BRIGHT_T31'
            END,

            CASE
                WHEN v.bright_ti4 = 0
                THEN 'ZERO_BRIGHT_TI4'
            END,

            CASE
                WHEN v.bright_ti5 = 0
                THEN 'ZERO_BRIGHT_TI5'
            END,

            CASE
                WHEN v.brightness > 0
                     AND v.brightness <= l.brightness_low
                THEN 'LOW_BRIGHTNESS_REVIEW'
            END,

            CASE
                WHEN v.brightness > l.brightness_high
                THEN 'HIGH_BRIGHTNESS_REVIEW'
            END,

            CASE
                WHEN v.bright_t31 > 0
                     AND v.bright_t31 <= l.bright_t31_low
                THEN 'LOW_BRIGHT_T31_REVIEW'
            END,

            CASE
                WHEN v.bright_t31 > l.bright_t31_high
                THEN 'HIGH_BRIGHT_T31_REVIEW'
            END,

            CASE
                WHEN v.bright_ti4 > 0
                     AND v.bright_ti4 <= l.bright_ti4_low
                THEN 'LOW_BRIGHT_TI4_REVIEW'
            END,

            CASE
                WHEN v.bright_ti4 > l.bright_ti4_high
                THEN 'HIGH_BRIGHT_TI4_REVIEW'
            END,

            CASE
                WHEN v.bright_ti5 > 0
                     AND v.bright_ti5 <= l.bright_ti5_low
                THEN 'LOW_BRIGHT_TI5_REVIEW'
            END,

            CASE
                WHEN v.bright_ti5 > l.bright_ti5_high
                THEN 'HIGH_BRIGHT_TI5_REVIEW'
            END,

            CASE
                WHEN v.frp > l.frp_high
                THEN 'HIGH_FRP_REVIEW'
            END,

            CASE
                WHEN
                    (
                        v.source = 'C2_SAMPLE'
                        AND (
                            (v.satellite IN ('Aqua', 'Terra')
                                AND v.version <> '61.03')
                            OR
                            (v.satellite IN ('N20', 'N21')
                                AND v.version <> '2.0')
                        )
                    )
                    OR
                    (
                        v.source = 'FIRMS_API'
                        AND (
                            (v.satellite IN ('Aqua', 'Terra')
                                AND v.version <> '6.1NRT')
                            OR
                            (v.satellite = 'N20'
                                AND v.version <> '2.0NRT')
                            OR
                            (v.satellite = 'N21'
                                AND v.version NOT IN ('2.0NRT', '2.0URT'))
                        )
                    )
                THEN 'UNRECOGNIZED_VERSION_REVIEW'
            END
        ),
        ''
    ) AS quality_flags

FROM valid_records v

LEFT JOIN investigation_limits l
    ON v.source = l.source
   AND v.satellite = l.satellite;


-- ============================================================
-- 10. BUILD CLEANED DATASET
-- ============================================================
-- Preserve source provenance for downstream metadata mapping.
-- C2 detection "type" is intentionally excluded.

CREATE OR REPLACE TEMP TABLE cleaned_records AS

SELECT
    source,
    source_type,
    source_file,
    latitude,
    longitude,
    brightness,
    bright_t31,
    bright_ti4,
    bright_ti5,
    frp,
    scan,
    track,
    acq_date,
    acq_time,
    satellite,
    instrument,
    confidence,
    version,
    daynight,
    quality_flags

FROM investigated_records;


-- ============================================================
-- 11. WRITE CLEANED DATASET
-- ============================================================

COPY (
    SELECT *
    FROM cleaned_records
)
TO '{{CLEANED_OUTPUT}}'
(FORMAT PARQUET, COMPRESSION ZSTD, OVERWRITE_OR_IGNORE TRUE);


-- ============================================================
-- 12. WRITE QUARANTINED RECORDS
-- ============================================================
-- Includes source_type and source_file for audit traceability.

COPY (
    SELECT *
    FROM quarantined_records
)
TO '{{QUARANTINE_OUTPUT}}'
(FORMAT PARQUET, COMPRESSION ZSTD, OVERWRITE_OR_IGNORE TRUE);


-- ============================================================
-- 13. WRITE CLEANING REPORT
-- ============================================================

COPY (

    SELECT 'input_rows' AS metric,
           (SELECT COUNT(*) FROM c2_raw)
           + (SELECT COUNT(*) FROM api_raw) AS value

    UNION ALL

    SELECT 'duplicate_rows_removed',
           (SELECT COUNT(*) FROM c2_raw)
           - (SELECT COUNT(*) FROM c2_raw_dedup)
           + (SELECT COUNT(*) FROM api_raw)
           - (SELECT COUNT(*) FROM api_raw_dedup)

    UNION ALL

    SELECT 'retained_after_cleaning',
           COUNT(*)
    FROM cleaned_records

    UNION ALL

    SELECT 'quarantined_rows',
           COUNT(*)
    FROM quarantined_records

    UNION ALL

    SELECT 'zero_frp_flagged_rows',
           COUNT(*) FILTER (WHERE frp = 0)
    FROM cleaned_records

    UNION ALL

    SELECT 'zero_brightness_flagged_rows',
           COUNT(*) FILTER (
               WHERE brightness = 0
                  OR bright_t31 = 0
                  OR bright_ti4 = 0
                  OR bright_ti5 = 0
           )
    FROM cleaned_records

    UNION ALL

    SELECT 'low_brightness_review_rows',
           COUNT(*) FILTER (
               WHERE contains(quality_flags, 'LOW_')
           )
    FROM cleaned_records

    UNION ALL

    SELECT 'high_measurement_review_rows',
           COUNT(*) FILTER (
               WHERE contains(quality_flags, 'HIGH_')
           )
    FROM cleaned_records

)
TO '{{CLEANING_REPORT_OUTPUT}}'
(HEADER, DELIMITER ',', OVERWRITE_OR_IGNORE TRUE);


-- ============================================================
-- 14. DISPLAY CLEANING SUMMARY
-- ============================================================

SELECT 'Input' AS stage,
       (SELECT COUNT(*) FROM c2_raw)
       + (SELECT COUNT(*) FROM api_raw) AS records

UNION ALL

SELECT 'Duplicate copies removed',
       (SELECT COUNT(*) FROM c2_raw)
       - (SELECT COUNT(*) FROM c2_raw_dedup)
       + (SELECT COUNT(*) FROM api_raw)
       - (SELECT COUNT(*) FROM api_raw_dedup)

UNION ALL

SELECT 'Retained after cleaning',
       COUNT(*)
FROM cleaned_records

UNION ALL

SELECT 'Quarantined',
       COUNT(*)
FROM quarantined_records;


-- ============================================================
-- 15. DISPLAY INVESTIGATION FLAG COUNTS
-- ============================================================

SELECT
    source,
    satellite,

    COUNT(*) FILTER (
        WHERE contains(quality_flags, 'ZERO_FRP')
    ) AS zero_frp,

    COUNT(*) FILTER (
        WHERE contains(quality_flags, 'ZERO_BRIGHTNESS')
           OR contains(quality_flags, 'ZERO_BRIGHT_T31')
           OR contains(quality_flags, 'ZERO_BRIGHT_TI4')
           OR contains(quality_flags, 'ZERO_BRIGHT_TI5')
    ) AS zero_brightness,

    COUNT(*) FILTER (
        WHERE contains(quality_flags, 'LOW_')
    ) AS low_value_reviews,

    COUNT(*) FILTER (
        WHERE contains(quality_flags, 'HIGH_')
    ) AS high_value_reviews,

    COUNT(*) FILTER (
        WHERE contains(quality_flags, 'UNRECOGNIZED_VERSION')
    ) AS version_reviews

FROM cleaned_records
GROUP BY source, satellite
ORDER BY source, satellite;


-- ============================================================
-- 16. DISPLAY QUARANTINE REASONS
-- ============================================================

SELECT
    source,
    quarantine_reason,
    COUNT(*) AS affected_records

FROM quarantined_records
GROUP BY source, quarantine_reason
ORDER BY source, quarantine_reason;


-- ============================================================
-- 17. INDIVIDUAL QUALITY FLAG BREAKDOWN
-- ============================================================

SELECT
    source,
    satellite,
    TRIM(flag) AS quality_flag,
    COUNT(*) AS flagged_records

FROM cleaned_records,
UNNEST(STRING_SPLIT(quality_flags, ' | ')) AS t(flag)

WHERE quality_flags IS NOT NULL

GROUP BY source, satellite, TRIM(flag)
ORDER BY source, satellite, quality_flag;
